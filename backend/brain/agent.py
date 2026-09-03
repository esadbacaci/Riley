"""Ajan döngüsü: kullanıcı metni -> LLM -> araç çağrıları -> sesli cevap.

Metin üretilirken cümle cümle TTS kuyruğuna aktarılır; böylece Riley
cevabın tamamını beklemeden konuşmaya başlar.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from brain.llm import OllamaError, llm
from brain.persona import build_system_prompt
from config import CFG
from core.bus import bus
from core.state import State, machine
from skills import needs_confirmation, run_skill, tool_schemas
from skills.misc import _load_memory

# Cümle sonu: nokta/soru/ünlem + boşluk, ya da satır sonu
_SENTENCE_END = re.compile(r"(?<=[.!?…:])\s+|\n+")
_MIN_SENTENCE = 10

# İlk parça için daha gevşek sınır: virgül ya da cümle sonu yeter.
# Böylece Riley cevabın ilk yarısını beklemeden konuşmaya başlar.
_ILK_PARCA = re.compile(r"(?<=[,;:.!?…])\s+")
_ILK_ASGARI = 18

# Kullanıcı açıkça "bunu unutma" dediğinde modelin remember aracını çağırdığına
# güvenilemiyor; çoğu zaman sadece "tamam, hatırlarım" diyor. Bu kalıp yakalanınca
# bilgi her hâlükârda kaydedilir.
_HAFIZA_KALIBI = re.compile(
    r"\b(?:bunu\s+unutma|unutma\s+bunu|akl[ıi]nda\s+tut|akl[ıi]na\s+yaz|"
    r"not\s+al|kaydet\s+bunu|hat[ıi]rla\s+bunu|bunu\s+hat[ıi]rla|"
    r"beni\s+tan[ıi]|hep\s+hat[ıi]rla|unutmaman[ıi]\s+istiyorum)\b",
    re.IGNORECASE,
)

_YES = {
    "evet", "e", "tamam", "olur", "yap", "devam", "onayliyorum", "onay", "tabii",
    "tabi", "aynen", "ok", "okey", "peki", "hadi", "yapalim", "onayla", "kabul",
}
_NO = {
    "hayir", "yok", "iptal", "dur", "vazgec", "vazgectim", "olmaz", "yapma",
    "gerek yok", "bosver", "hayirr", "no", "istemiyorum",
}


def _normalize(text: str) -> str:
    table = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
    return text.lower().translate(table).strip(" .!?,")


def is_affirmative(text: str) -> bool | None:
    """Evet -> True, hayir -> False, anlaşılmadı -> None."""
    norm = _normalize(text)
    if norm in _YES or any(norm.startswith(w + " ") for w in _YES):
        return True
    if norm in _NO or any(norm.startswith(w + " ") for w in _NO):
        return False
    return None


class Agent:
    def __init__(self, max_history: int = 24, tutulacak: int = 12) -> None:
        self.history: list[dict] = []
        self.max_history = max_history      # bu sayıyı aşınca kırpılır
        self.tutulacak = tutulacak          # kırpımdan sonra kalan mesaj sayısı
        # Kırpılan eski mesajların sıkıştırılmış özeti. Uzun sohbetlerde
        # bağlamın tamamen kaybolmasını engeller.
        self.ozet: str = ""
        self.speech_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._confirm_future: asyncio.Future[bool] | None = None
        self._busy = asyncio.Lock()

    # --- onay akışı -------------------------------------------------------
    @property
    def awaiting_confirmation(self) -> bool:
        return self._confirm_future is not None and not self._confirm_future.done()

    def resolve_confirmation(self, approved: bool) -> None:
        if self.awaiting_confirmation:
            self._confirm_future.set_result(approved)  # type: ignore[union-attr]

    async def _ask_confirmation(self, tool_name: str, args: dict) -> bool:
        question = f"{tool_name} işlemini onaylıyor musunuz?"
        detail = ", ".join(f"{k}={v}" for k, v in args.items())
        await bus.emit("confirm.request", tool=tool_name, args=args, question=question)
        await self.speak(f"Dikkat. {_describe(tool_name, args)} Onaylıyor musunuz?")

        loop = asyncio.get_running_loop()
        self._confirm_future = loop.create_future()
        try:
            approved = await asyncio.wait_for(self._confirm_future, timeout=45.0)
        except asyncio.TimeoutError:
            approved = False
            await bus.log(f"Onay zaman aşımına uğradı: {tool_name} ({detail})", "warn")
        finally:
            self._confirm_future = None

        await bus.emit("confirm.result", tool=tool_name, approved=approved)
        return approved

    # --- konuşma kuyruğu --------------------------------------------------
    async def speak(self, text: str) -> None:
        clean = _clean_for_speech(text)
        if clean:
            await self.speech_queue.put(clean)

    # --- ana giriş --------------------------------------------------------
    async def handle(self, user_text: str) -> str:
        if self._busy.locked():
            await bus.log("Önceki istek sürerken yeni istek geldi, sıraya alındı.", "warn")

        async with self._busy:
            machine.clear_cancel()
            try:
                return await self._run(user_text)
            except OllamaError as exc:
                await machine.set(State.ERROR, str(exc))
                message = "Dil modeline ulaşamıyorum. Ollama servisi çalışıyor mu?"
                await self.speak(message)
                await bus.emit("reply.done", text=message, error=True)
                return message
            except Exception as exc:  # beklenmeyen hata sistemi kilitlemesin
                await machine.set(State.ERROR, f"{type(exc).__name__}: {exc}")
                await bus.log(f"Ajan hatası: {type(exc).__name__}: {exc}", "error")
                message = "Bir aksilik oldu, tekrar dener misiniz?"
                await self.speak(message)
                await bus.emit("reply.done", text=message, error=True)
                return message
            finally:
                await machine.set(State.IDLE)

    async def _run(self, user_text: str) -> str:
        baslangic = time.perf_counter()
        ilk_belirtec: float | None = None
        ilk_konusma: float | None = None

        await bus.emit("user.said", text=user_text)
        await machine.set(State.THINKING)

        memories = [m["fact"] for m in _load_memory()]
        messages = [{"role": "system", "content": build_system_prompt(memories)}]
        if self.ozet:
            messages.append({
                "role": "system",
                "content": (
                    "KONUŞMANIN ÖNCEKİ BÖLÜMÜNÜN ÖZETİ (bunu kendiliğinden "
                    "tekrar etme, sadece gerektiğinde başvur):\n"
                    f"{self.ozet}"
                ),
            })
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        final_text = ""
        kullanilan_araclar: set[str] = set()
        zorlandi = False        # araç çağırması için bir kez zorlandı mı

        for round_index in range(CFG.llm.max_tool_rounds):
            buffer = ""          # TTS için cümle biriktirici
            visible = ""         # bu turda üretilen tum metin
            calls: list[dict] = []

            async for event in llm.chat_stream(messages, tools=tool_schemas()):
                if machine.cancelled:
                    await bus.log("Istek kullanıcı tarafından iptal edildi.", "warn")
                    return ""

                kind = event["kind"]
                if kind == "thinking":
                    continue                      # muhakeme metni seslendirilmez
                if kind == "delta":
                    piece = event["text"]
                    if ilk_belirtec is None:
                        ilk_belirtec = time.perf_counter() - baslangic
                    visible += piece
                    buffer += piece
                    await bus.emit("reply.delta", text=piece)

                    # Tam cümle oluştuysa hemen seslendirmeye gönder
                    # İlk parça daha erken gönderilir: kullanıcı cevabın
                    # tamamlanmasını beklemesin. Sonraki parçalarda tam cümle
                    # sınırı beklenir, böylece tonlama bozulmaz.
                    if ilk_konusma is None:
                        erken = _ILK_PARCA.split(buffer, maxsplit=1)
                        if len(erken) > 1 and len(erken[0].strip()) >= _ILK_ASGARI:
                            await self.speak(erken[0])
                            ilk_konusma = time.perf_counter() - baslangic
                            buffer = erken[1]

                    parts = _SENTENCE_END.split(buffer)
                    if len(parts) > 1:
                        for sentence in parts[:-1]:
                            if len(sentence.strip()) >= _MIN_SENTENCE:
                                await self.speak(sentence)
                                if ilk_konusma is None:
                                    ilk_konusma = time.perf_counter() - baslangic
                            elif sentence.strip():
                                parts[-1] = sentence + " " + parts[-1]
                        buffer = parts[-1]

                elif kind == "tool_calls":
                    calls = event["calls"]

                elif kind == "done":
                    if buffer.strip():
                        await self.speak(buffer)
                        if ilk_konusma is None:
                            ilk_konusma = time.perf_counter() - baslangic
                        buffer = ""

            if not calls:
                final_text = visible.strip()

                # Model bazen aracı çağırmak yerine çağıracağını anlatıyor
                # ("set_volume aracını çağırıyorum"). Bir kez daha, bu sefer
                # açık bir uyarıyla dene.
                if (
                    not kullanilan_araclar
                    and not zorlandi
                    and _arac_anonsu(final_text)
                    and round_index < CFG.llm.max_tool_rounds - 1
                ):
                    zorlandi = True
                    await self._konusmayi_bosalt()
                    await bus.log(
                        "Model aracı çağırmak yerine anlattı; yeniden deneniyor.",
                        "warn",
                    )
                    messages.append({"role": "assistant", "content": final_text})
                    messages.append({
                        "role": "system",
                        "content": (
                            "Az önce bir aracı çağıracağını söyledin ama "
                            "çağırmadın. Anlatma, şimdi doğrudan ilgili aracı "
                            "çağır. Araç sonucunu görmeden cevap yazma."
                        ),
                    })
                    continue

                messages.append({"role": "assistant", "content": final_text})
                break

            # --- araç çağrıları ---
            messages.append({
                "role": "assistant",
                "content": visible,
                "tool_calls": [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ],
            })

            await machine.set(State.ACTING)
            for call in calls:
                name, args = call["name"], call["arguments"]
                kullanilan_araclar.add(name)
                await bus.emit("tool.start", name=name, args=args)

                if needs_confirmation(name):
                    if not await self._ask_confirmation(name, args):
                        messages.append({
                            "role": "tool",
                            "name": name,
                            "content": "Kullanıcı bu işlemi onaylamadı, iptal edildi.",
                        })
                        await bus.emit("tool.end", name=name, ok=False, result="iptal")
                        continue

                outcome = await run_skill(name, args)
                payload = outcome.get("result") if outcome["ok"] else outcome["error"]
                await bus.emit(
                    "tool.end", name=name, ok=outcome["ok"], result=str(payload)[:400]
                )
                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": str(payload)[:4000],
                })

            await machine.set(State.THINKING)
        else:
            final_text = (
                "Bu istek için cok fazla adım gerekti, burada durdum. "
                "Daha küçük parçalara bölebilir miyiz?"
            )
            await self.speak(final_text)

        await self._hafizayi_guvenceye_al(user_text, kullanilan_araclar)

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": final_text})

        # Kırpma cevabı geciktirmesin; arka planda yapılır
        if len(self.history) > self.max_history:
            asyncio.create_task(self._gecmisi_kirp())

        await bus.emit(
            "reply.done",
            text=final_text,
            timing={
                "ilk_belirtec_ms": round((ilk_belirtec or 0) * 1000),
                "ilk_konusma_ms": round((ilk_konusma or 0) * 1000),
                "toplam_ms": round((time.perf_counter() - baslangic) * 1000),
                "arac_sayisi": len(kullanilan_araclar),
            },
        )
        return final_text

    async def _konusmayi_bosalt(self) -> None:
        """Seslendirme kuyruğunda bekleyenleri atar.

        Yanlış bir cevap seslendirilmek üzereyken kullanılır.
        """
        from audio.tts import speaker

        while not self.speech_queue.empty():
            try:
                self.speech_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        speaker.stop()

    async def _gecmisi_kirp(self) -> None:
        """Eski mesajları özete sıkıştırıp geçmişi kısaltır.

        Sohbet uzadıkça en eski mesajlar düşürülür. Onları tamamen atmak
        yerine dil modeline kısa bir özet çıkarttırıp saklarız; böylece
        yarım saat önce söylenen bir şey unutulmaz.
        """
        if len(self.history) <= self.max_history:
            return

        dusen = self.history[: len(self.history) - self.tutulacak]
        kalan = self.history[len(self.history) - self.tutulacak :]

        dokum = "\n".join(
            f"{'Kullanıcı' if m['role'] == 'user' else 'Riley'}: {m['content']}"
            for m in dusen
            if m.get("content") and m.get("role") in ("user", "assistant")
        )
        if not dokum.strip():
            self.history = kalan
            return

        istem = (
            "Aşağıda bir kullanıcı ile asistan arasındaki konuşmanın eski "
            "bölümü var. Bunu en fazla altı cümlede özetle. Kullanıcının "
            "kim olduğu, tercihleri, üzerinde çalışılan konular ve verilen "
            "kararlar kalsın; gündelik ayrıntılar düşsün. Sadece özeti yaz.\n\n"
            + (f"Daha önceki özet:\n{self.ozet}\n\n" if self.ozet else "")
            + f"Konuşma:\n{dokum}"
        )

        try:
            parcalar: list[str] = []
            async for olay in llm.chat_stream(
                [{"role": "user", "content": istem}], temperature=0.2
            ):
                if olay["kind"] == "done":
                    parcalar.append(olay["content"])
            yeni = "".join(parcalar).strip()
            if yeni:
                self.ozet = yeni
                await bus.log(
                    f"Sohbet geçmişi özetlendi ({len(dusen)} mesaj sıkıştırıldı).",
                    "debug",
                )
        except Exception as exc:
            await bus.log(f"Geçmiş özetlenemedi: {exc}", "warn")

        self.history = kalan

    async def _hafizayi_guvenceye_al(
        self, user_text: str, kullanilan_araclar: set[str]
    ) -> None:
        """Kullanıcı açıkça hatırlamamızı istediyse bilginin kaydını garantiler."""
        if "remember" in kullanilan_araclar:
            return
        if not _HAFIZA_KALIBI.search(user_text):
            return

        bilgi = _HAFIZA_KALIBI.sub("", user_text).strip(" ,.;:!?")
        if len(bilgi) < 4:
            return

        await bus.emit("tool.start", name="remember", args={"fact": bilgi})
        sonuc = await run_skill("remember", {"fact": bilgi})
        await bus.emit(
            "tool.end", name="remember", ok=sonuc["ok"],
            result=str(sonuc.get("result") or sonuc.get("error"))[:200],
        )

    def reset(self) -> None:
        self.history.clear()
        self.ozet = ""


_ANONS_FIILLERI = re.compile(
    r"(çağır|cagir|kullan|çalıştır|calistir|başlat|baslat)\w*",
    re.IGNORECASE,
)


def _arac_anonsu(text: str) -> bool:
    """Metin, bir aracı çağırmak yerine çağıracağını anlatıyor mu?

    Araç adları İngilizce ve alt çizgili olduğu için Türkçe bir cevapta
    kendiliğinden geçmez; geçiyorsa model aracı çağırmak yerine adını
    yazmış demektir.
    """
    if not text:
        return False
    from skills import REGISTRY

    # Model araç adını "system_stats" ya da "System stats" diye yazabilir
    dusuk = re.sub(r"[_\s]+", " ", text.lower())
    gecen = any(
        ad.replace("_", " ") in dusuk for ad in REGISTRY
    )
    if not gecen:
        return False
    return bool(_ANONS_FIILLERI.search(dusuk))


def _describe(tool: str, args: dict) -> str:
    """Onay sorusunu insan diline çevirir."""
    if tool == "delete_path":
        return f"{args.get('path', 'bir dosya')} kalıcı olarak silinecek."
    if tool == "shutdown":
        mode = args.get("mode", "shutdown")
        return (
            "Bilgisayar kapatılacak."
            if mode == "shutdown"
            else "Bilgisayar yeniden başlatılacak."
        )
    if tool == "kill_process":
        return f"{args.get('name', 'bir surec')} zorla sonlandırılacak."
    if tool == "run_command":
        return f"Su komut çalıştırılacak: {args.get('command', '')}"
    return f"{tool} işlemi çalıştırılacak. Parametreler: {json.dumps(args, ensure_ascii=False)}"


_MD_NOISE = re.compile(r"[*_`#>|]+")
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]", flags=re.UNICODE
)


def _clean_for_speech(text: str) -> str:
    """Model yine de markdown kaçırırsa TTS'e temiz metin gitsin."""
    out = _EMOJI.sub("", text)
    out = _MD_NOISE.sub("", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


agent = Agent()
