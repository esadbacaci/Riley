"""Zaman, hatırlatıcı ve kalıcı not becerileri."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import uuid

from config import DATA_DIR
from core.bus import bus
from skills.registry import SkillError, skill

MEMORY_FILE = DATA_DIR / "memory.json"

_GUNLER = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
]
_AYLAR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


@skill(
    name="get_datetime",
    description=(
        "Su anki tarih ve saati döndürür. Saat kac, bugün günlerden ne gibi "
        "sorularda kullan. Tarihi asla tahmin etme, her zaman bunu çağır."
    ),
    level="narrow",
)
def get_datetime() -> str:
    now = dt.datetime.now()
    return (
        f"{now.day} {_AYLAR[now.month - 1]} {now.year}, "
        f"{_GUNLER[now.weekday()]}, saat {now.hour:02d}:{now.minute:02d}."
    )


# --- Hatırlatıcı / zamanlayıcı -------------------------------------------
#
# Hatırlatıcılar diske yazılır. Riley kapanıp açılsa bile kurulmuş
# hatırlatmalar geri yüklenir; kapalıyken zamanı gelmiş olanlar açılışta
# gecikmiş olarak bildirilir.

TIMERS_FILE = DATA_DIR / "timers.json"

_TIMERS: dict[str, asyncio.Task] = {}      # çalışan görevler
_KAYITLAR: dict[str, dict] = {}            # diske yazılan kayıtlar

# Bundan daha eski kaçırılmış hatırlatmalar sessizce düşürülür
_BAYATLIK_SINIRI_SN = 12 * 3600


def _kayitlari_oku() -> dict[str, dict]:
    if not TIMERS_FILE.exists():
        return {}
    try:
        return json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _kayitlari_yaz() -> None:
    try:
        TIMERS_FILE.write_text(
            json.dumps(_KAYITLAR, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        bus.log_threadsafe(f"Hatırlatıcılar kaydedilemedi: {exc}", "warn")


def _parse_duration(text: str) -> int:
    """'5 dakika', '1 saat 30 dk', '90 saniye' -> saniye."""
    raw = str(text).lower().replace(",", ".")
    total = 0
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:saat|sa\b|h\b|hour)", 3600),
        (r"(\d+(?:\.\d+)?)\s*(?:dakika|dakka|dk\b|min|m\b)", 60),
        (r"(\d+(?:\.\d+)?)\s*(?:saniye|sn\b|sec|s\b)", 1),
    ]
    for pattern, factor in patterns:
        for value in re.findall(pattern, raw):
            total += float(value) * factor

    if total == 0:
        bare = re.findall(r"\d+(?:\.\d+)?", raw)
        if bare:
            total = float(bare[0]) * 60  # birim yoksa dakika varsay
    if total <= 0:
        raise SkillError("Süreyi anlayamadım. Örnek: 5 dakika, 1 saat 30 dakika.")
    return int(total)


async def _fire(timer_id: str, seconds: int, label: str, gecikmis: bool = False) -> None:
    try:
        if seconds > 0:
            await asyncio.sleep(seconds)
        await bus.emit("timer.fired", id=timer_id, label=label, late=gecikmis)
        onek = "Kaçırdığım bir hatırlatma vardı: " if gecikmis else "Hatırlatma zamanı: "
        await bus.emit("assistant.say", text=onek + label)
    except asyncio.CancelledError:
        pass
    finally:
        _TIMERS.pop(timer_id, None)
        if _KAYITLAR.pop(timer_id, None) is not None:
            _kayitlari_yaz()


async def _spawn(timer_id: str, seconds: int, label: str,
                 gecikmis: bool = False) -> asyncio.Task:
    return asyncio.create_task(_fire(timer_id, seconds, label, gecikmis))


async def hatirlaticilari_geri_yukle() -> int:
    """Açılışta diskteki hatırlatıcıları geri kurar.

    Zamanı geçmiş olanlar 'kaçırıldı' diye hemen bildirilir; çok eskiler
    sessizce düşürülür.
    """
    global _KAYITLAR
    _KAYITLAR = _kayitlari_oku()
    if not _KAYITLAR:
        return 0

    simdi = dt.datetime.now()
    geri_yuklenen = 0
    dusen = 0

    for timer_id, kayit in list(_KAYITLAR.items()):
        try:
            zaman = dt.datetime.fromisoformat(kayit["fire_at"])
        except Exception:
            _KAYITLAR.pop(timer_id, None)
            continue

        kalan = (zaman - simdi).total_seconds()
        if kalan < -_BAYATLIK_SINIRI_SN:
            _KAYITLAR.pop(timer_id, None)
            dusen += 1
            continue

        _TIMERS[timer_id] = await _spawn(
            timer_id, max(0, int(kalan)), kayit.get("label", "hatırlatma"),
            gecikmis=kalan <= 0,
        )
        geri_yuklenen += 1

    _kayitlari_yaz()
    if geri_yuklenen or dusen:
        await bus.log(
            f"{geri_yuklenen} hatırlatıcı geri yüklendi"
            + (f", {dusen} bayat kayıt düşürüldü" if dusen else "") + ".",
            "info",
        )
    return geri_yuklenen


@skill(
    name="set_timer",
    description=(
        "Belirtilen süre sonra sesli hatırlatma kurar. Kullanıcı 'bana şu kadar "
        "sonra şunu hatırlat' dediğinde kullan. Hatırlatıcılar Riley kapansa "
        "bile korunur."
    ),
    params={
        "duration": {"type": "string", "description": "Süre, örn: 10 dakika, 1 saat"},
        "label": {"type": "string", "description": "Hatırlatılacak şey"},
    },
    required=["duration"],
)
def set_timer(duration: str, label: str = "zamanlayıcı") -> str:
    seconds = _parse_duration(duration)
    timer_id = uuid.uuid4().hex[:8]

    loop = bus.loop
    if loop is None:
        raise SkillError("Zamanlayıcı şu an kurulamıyor.")

    zaman = dt.datetime.now() + dt.timedelta(seconds=seconds)
    _KAYITLAR[timer_id] = {
        "label": label,
        "fire_at": zaman.isoformat(timespec="seconds"),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    _kayitlari_yaz()

    task = asyncio.run_coroutine_threadsafe(
        _spawn(timer_id, seconds, label), loop
    ).result(timeout=5)
    _TIMERS[timer_id] = task

    return (
        f"Tamam, {zaman.hour:02d}:{zaman.minute:02d} için kuruldu: {label} "
        f"(kod {timer_id})"
    )


@skill(
    name="list_timers",
    description="Kurulmuş hatırlatıcıları ve ne zaman çalacaklarını listeler.",
    level="narrow",
)
def list_timers() -> str:
    if not _KAYITLAR:
        return "Aktif hatırlatıcı yok."

    simdi = dt.datetime.now()
    satirlar = []
    for timer_id, kayit in sorted(_KAYITLAR.items(), key=lambda kv: kv[1]["fire_at"]):
        try:
            zaman = dt.datetime.fromisoformat(kayit["fire_at"])
        except Exception:
            continue
        kalan = int((zaman - simdi).total_seconds())
        if kalan >= 3600:
            ne_zaman = f"{kalan // 3600} saat {(kalan % 3600) // 60} dakika sonra"
        elif kalan >= 60:
            ne_zaman = f"{kalan // 60} dakika sonra"
        elif kalan > 0:
            ne_zaman = f"{kalan} saniye sonra"
        else:
            ne_zaman = "zamanı geçti"
        satirlar.append(f"{kayit.get('label', 'hatırlatma')} — {ne_zaman} ({timer_id})")

    return "Hatırlatıcılar:\n" + "\n".join(satirlar)


@skill(
    name="cancel_timer",
    description="Bir hatırlatıcıyı iptal eder. Kod verilmezse hepsini iptal eder.",
    params={"timer_id": {"type": "string", "description": "İptal edilecek hatırlatıcı kodu"}},
)
def cancel_timer(timer_id: str = "") -> str:
    if not timer_id:
        sayi = len(_KAYITLAR)
        for task in list(_TIMERS.values()):
            task.cancel()
        _TIMERS.clear()
        _KAYITLAR.clear()
        _kayitlari_yaz()
        return f"{sayi} hatırlatıcı iptal edildi."

    kayit = _KAYITLAR.pop(timer_id, None)
    task = _TIMERS.pop(timer_id, None)
    if kayit is None and task is None:
        raise SkillError(f"{timer_id} kodlu hatırlatıcı yok.")
    if task is not None:
        task.cancel()
    _kayitlari_yaz()
    etiket = (kayit or {}).get("label", timer_id)
    return f"İptal edildi: {etiket}"


# --- Kalıcı hafıza -------------------------------------------------------


def _load_memory() -> list[dict]:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_memory(items: list[dict]) -> None:
    MEMORY_FILE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@skill(
    name="remember",
    description=(
        "Kullanıcı hakkında kalıcı bir bilgi kaydeder; sonraki oturumlarda da "
        "hatırlanır. Kullanıcı bunu unutma, sunu aklında tut dediğinde kullan."
    ),
    params={"fact": {"type": "string", "description": "Hatırlanacak bilgi"}},
    required=["fact"],
)
def remember(fact: str) -> str:
    items = _load_memory()
    items.append({"fact": fact.strip(), "at": dt.datetime.now().isoformat(timespec="seconds")})
    _save_memory(items[-200:])
    return f"Aklımda tuttum: {fact}"


@skill(
    name="recall",
    description=(
        "Daha önce kaydedilmiş bilgileri getirir. Kullanıcı geçmişte söylediği "
        "bir şeyi sorduğunda kullan."
    ),
    params={"query": {"type": "string", "description": "Aranacak kelime, boş ise hepsi"}},
    level="narrow",
)
def recall(query: str = "") -> str:
    items = _load_memory()
    if query:
        needle = query.lower()
        items = [i for i in items if needle in i["fact"].lower()]
    if not items:
        return "Bu konuda kayıtlı bir şey yok."
    return "Hatırladıklarım:\n" + "\n".join(f"- {i['fact']}" for i in items[-25:])


@skill(
    name="forget",
    description="Kayıtlı bir bilgiyi siler.",
    params={"query": {"type": "string", "description": "Silinecek kaydın içerdiği kelime"}},
    required=["query"],
)
def forget(query: str) -> str:
    items = _load_memory()
    needle = query.lower()
    kept = [i for i in items if needle not in i["fact"].lower()]
    removed = len(items) - len(kept)
    if removed == 0:
        raise SkillError(f"{query} ile eşleşen kayıt yok.")
    _save_memory(kept)
    return f"{removed} kayıt silindi."
