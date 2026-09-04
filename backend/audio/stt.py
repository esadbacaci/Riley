"""Konuşmadan metne. faster-whisper, önce GPU dener, olmazsa CPU'ya düşer.

Not: Blackwell nesli ekran kartlarında (RTX 50xx) CTranslate2'nin CUDA desteği
her sürümde çalışmayabilir; bu yüzden hata yakalanıp sessizce CPU'ya geçilir.
"""
from __future__ import annotations

import re
import os
import time
from pathlib import Path

import numpy as np

from config import CFG, MODELS_DIR
from core.bus import bus

_WHISPER_CACHE = MODELS_DIR / "whisper"


def _cuda_dll_dizinlerini_tanit() -> list[str]:
    """CTranslate2'nin ihtiyaç duyduğu CUDA kütüphanelerini bulunur kılar.

    Windows'ta cuBLAS ve cuDNN DLL'leri pip paketlerinin içinde gelir ama
    sistem arama yoluna eklenmez. Sonuç: model GPU'ya yüklenir, ilk
    çözümlemede "cublas64_12.dll bulunamadı" diye çöker. Süreç başlarken
    bu dizinleri tanıtmak sorunu kökten çözer.
    """
    import site

    bulunanlar: list[str] = []
    adaylar: list[Path] = []
    for kok in {*site.getsitepackages(), site.getusersitepackages()}:
        nvidia = Path(kok) / "nvidia"
        if nvidia.exists():
            adaylar.extend(nvidia.rglob("bin"))

    for dizin in adaylar:
        if not any(dizin.glob("*.dll")):
            continue
        try:
            os.add_dll_directory(str(dizin))
            bulunanlar.append(dizin.name)
        except (OSError, AttributeError):
            continue
        os.environ["PATH"] = str(dizin) + os.pathsep + os.environ.get("PATH", "")

    return bulunanlar


def _ensure_hf_reachable() -> None:
    """huggingface.co engelliyse ayna adresi kullan."""
    if os.environ.get("HF_ENDPOINT"):
        return
    import socket

    try:
        socket.getaddrinfo("huggingface.co", 443)
    except OSError:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        bus.log_threadsafe(
            "huggingface.co erişilemedi, model indirmede hf-mirror.com kullanılacak.",
            "warn",
        )


class Transcriber:
    def __init__(self) -> None:
        self.model = None
        self.device = "cpu"
        self.compute_type = CFG.stt.compute_type_cpu

    def load(self) -> str:
        dll_dizinleri = _cuda_dll_dizinlerini_tanit()
        if dll_dizinleri:
            bus.log_threadsafe(
                f"CUDA kütüphaneleri tanıtıldı ({len(dll_dizinleri)} dizin).", "debug"
            )

        from faster_whisper import WhisperModel

        _ensure_hf_reachable()
        _WHISPER_CACHE.mkdir(parents=True, exist_ok=True)

        attempts: list[tuple[str, str]] = []
        if CFG.stt.device in ("auto", "cuda"):
            attempts.append(("cuda", CFG.stt.compute_type_gpu))
        attempts.append(("cpu", CFG.stt.compute_type_cpu))

        last_error: Exception | None = None
        for device, compute in attempts:
            try:
                started = time.time()
                self.model = WhisperModel(
                    CFG.stt.model_size,
                    device=device,
                    compute_type=compute,
                    download_root=str(_WHISPER_CACHE),
                    cpu_threads=max(2, (os.cpu_count() or 8) // 2),
                )
                self.device, self.compute_type = device, compute
                elapsed = time.time() - started
                bus.log_threadsafe(
                    f"Whisper '{CFG.stt.model_size}' {device}/{compute} üzerinde "
                    f"yüklendi ({elapsed:.1f} sn).",
                    "info",
                )
                return f"{CFG.stt.model_size}@{device}"
            except Exception as exc:
                last_error = exc
                if device == "cuda":
                    bus.log_threadsafe(
                        f"GPU'da Whisper başlatılamadı ({type(exc).__name__}), "
                        "işlemciye geçiliyor.",
                        "warn",
                    )

        raise RuntimeError(f"Whisper yüklenemedi: {last_error}")

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: 16 kHz, mono, float32, -1..1 aralığı."""
        if self.model is None:
            raise RuntimeError("Whisper modeli henüz yüklenmedi.")
        if audio.size == 0:
            return ""

        try:
            return self._coz(audio)
        except Exception as exc:
            # GPU yolu yüklenirken sorun vermeyip çözümleme anında çökebilir
            # (eksik CUDA DLL'i gibi). Bir kez CPU'ya düşüp devam et.
            if self.device != "cuda":
                raise
            bus.log_threadsafe(
                f"GPU çözümlemesi başarısız ({type(exc).__name__}); "
                "işlemciye kalıcı olarak geçiliyor.",
                "warn",
            )
            self._cpu_ya_dus()
            return self._coz(audio)

    def _cpu_ya_dus(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            CFG.stt.model_size,
            device="cpu",
            compute_type=CFG.stt.compute_type_cpu,
            download_root=str(_WHISPER_CACHE),
            cpu_threads=max(2, (os.cpu_count() or 8) // 2),
        )
        self.device, self.compute_type = "cpu", CFG.stt.compute_type_cpu
        bus.log_threadsafe("Whisper artık işlemci üzerinde çalışıyor.", "info")

    def _coz(self, audio: np.ndarray) -> str:
        ekstra = {}
        if CFG.stt.initial_prompt:
            ekstra["initial_prompt"] = CFG.stt.initial_prompt
        if CFG.stt.hotwords:
            ekstra["hotwords"] = CFG.stt.hotwords

        segments, _info = self.model.transcribe(
            audio,
            language=CFG.stt.language,
            beam_size=CFG.stt.beam_size,
            vad_filter=False,          # segmentasyonu zaten webrtcvad yapıyor
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.5,
            **ekstra,
        )

        parcalar: list[str] = []
        for seg in segments:
            # Model bazen kendisine verilen ipucunu cevabın içine kusuyor.
            # İpucu ayıklanır; geriye gerçek bir söz kalmadıysa parça atılır.
            temiz = _ipucunu_ayikla(seg.text)
            if not temiz:
                continue
            # Whisper sessizlikte veya gürültüde uydurma cümleler üretir.
            # Bu iki ölçü, üretilen metnin gerçekten duyulmuş olup olmadığını
            # gösterir: konuşma yokluğu olasılığı ve ortalama güven.
            if getattr(seg, "no_speech_prob", 0.0) > CFG.stt.no_speech_max:
                continue
            if getattr(seg, "avg_logprob", 0.0) < CFG.stt.min_logprob:
                continue
            parcalar.append(temiz)

        return " ".join(parcalar).strip()

    def isit(self) -> None:
        """İlk gerçek komut beklemesin diye GPU çekirdeklerini önden derle.

        Isıtılmazsa ilk çözümleme 15-20 saniye sürebiliyor."""
        if self.model is None:
            return
        try:
            started = time.time()
            sessizlik = np.zeros(16000, dtype=np.float32)
            self.transcribe(sessizlik)
            bus.log_threadsafe(
                f"Ses tanıma ısıtıldı ({time.time() - started:.1f} sn).", "debug"
            )
        except Exception as exc:
            bus.log_threadsafe(f"Isıtma başarısız: {exc}", "warn")


transcriber = Transcriber()

# Whisper'in sessizlikte uydurduğu klasik ifadeler; bunları yok say.
# Whisper sessizlik ve arka plan gürültüsünde bu kalıpları uydurur.
# Hepsi ASCII'ye indirgenmiş hâlde tutulur; is_noise de öyle karşılaştırır.
HALLUCINATIONS = {
    "altyazi m.k.", "altyazi m.k", "altyazi mk", "altyazi m k", "altyazi",
    "abone olmayi unutmayin", "abonelik", "abone ol",
    "izlediginiz icin tesekkurler", "izlediginiz icin tesekkur ederim",
    "tesekkurler", "tesekkur ederim",
    "merhaba turkler", "bir sonraki videoda gorusuruz",
    "bir sonraki videoda gorusmek uzere", "kanalima abone olun",
    "iyi seyirler", "hosca kalin", "gorusmek uzere",
    "...", ".", "!", "?", "-", "muzik", "alkis",
}

# Uydurma cümleler genelde bu parçaları içerir; tam eşleşme aranmaz.
HALLUCINATION_PARCALARI = (
    "sonraki videoda",
    "abone ol",
    "izlediginiz icin",
    "altyazi m",
    "merhaba turkler",
)


def _ipucunu_ayikla(text: str) -> str:
    """Modele verilen ipucu çıktıya sızdıysa temizler.

    Büyük modeller initial_prompt ve hotwords metnini bazen cevabın içine
    kopyalıyor. İpucu çıkarılır, geriye kalan gerçek söz döndürülür.
    """
    if not text:
        return ""

    temiz = text.strip()
    for ipucu in (CFG.stt.initial_prompt, CFG.stt.hotwords):
        ipucu = (ipucu or "").strip()
        if len(ipucu) < 8:
            continue
        yer = temiz.lower().find(ipucu.lower())
        while yer != -1:
            temiz = (temiz[:yer] + " " + temiz[yer + len(ipucu):]).strip()
            yer = temiz.lower().find(ipucu.lower())

    return temiz.strip(" ,.;:")


def is_noise(text: str) -> bool:
    """Metin gerçek bir konuşma mı, yoksa Whisper'ın uydurması mı?"""
    table = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
    # Önce sadeleştir, sonra küçült: "İ".lower() birleşik nokta bırakıyor
    # ve eşleştirmeyi bozuyor.
    sade = text.strip().translate(table).lower().strip(" .!?,")
    if len(sade) < 2:
        return True
    if sade in HALLUCINATIONS:
        return True
    if any(parca in sade for parca in HALLUCINATION_PARCALARI):
        return True

    # Aynı cümlenin tekrar tekrar yazılması da uydurmanın klasik işareti
    cumleler = [c.strip() for c in sade.split(".") if len(c.strip()) > 3]
    if len(cumleler) >= 3 and len(set(cumleler)) == 1:
        return True

    # Kelime düzeyinde tekrar. Gerçek kayıtlarda gürültüden "klasik, klasik,
    # klasik, klasik..." ya da "ekran, ekran, ekran, ekran" gibi çıktılar
    # geliyordu; bunlar noktayla ayrılmadığı için üstteki denetime takılmıyor.
    sozcukler = re.findall(r"[a-z0-9']+", sade)
    if len(sozcukler) >= 4:
        if len(set(sozcukler)) / len(sozcukler) <= 0.5:
            return True
        # Uzun bir sözcüğün üç kez geçmesi de uydurma işareti. Kısa sözcükler
        # ("bir", "ve", "de") gerçek cümlelerde de tekrar ettiği için
        # dörtten kısa olanlar sayılmaz.
        for s in set(sozcukler):
            if len(s) >= 4 and sozcukler.count(s) >= 3:
                return True

    return False
