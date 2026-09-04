"""Metinden konuşma. Birincil motor Piper (yerel, Türkçe), yedeği Windows SAPI.

Ses üretilirken RMS seviyesi olay veri yoluna basılır; HUD'daki dalga
Riley'in kendi sesiyle hareket eder.
"""
from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import threading
from pathlib import Path

import numpy as np

from audio.normalize import seslendirme_icin_hazirla
from config import CFG, MODELS_DIR, ROOT
from core.bus import bus
from core.state import State, machine

PIPER_EXE = ROOT / "tools" / "piper" / "piper.exe"
VOICE_DIR = MODELS_DIR / "piper"

_CREATE_NO_WINDOW = 0x08000000  # konsol penceresi açılmasın


class TTSUnavailable(RuntimeError):
    pass


class PiperEngine:
    """Piper'i süreç içinde çalıştırır ve sesi üretildikçe hoparlöre akıtır.

    Önceki sürüm her cümle için ayrı bir piper.exe süreci başlatıyordu.
    Ölçüldüğünde her seferinde ~240 ms model yükleme bedeli çıkıyor, üstelik
    cümleler arasında da boşluk oluşuyordu: metin ekranda görünüyor ama
    sesi gecikiyordu.

    Artık ses modeli bir kez belleğe alınıyor ve hoparlör akışı sürekli
    açık kalıyor. Piper sesi parça parça ürettiği için ilk parça hazır olur
    olmaz çalmaya başlıyoruz; cümlenin tamamının üretilmesini beklemiyoruz.
    """

    def __init__(self, voice: str) -> None:
        self.voice = voice
        self.model_path = VOICE_DIR / f"{voice}.onnx"
        self.config_path = VOICE_DIR / f"{voice}.onnx.json"

        if not self.model_path.exists():
            raise TTSUnavailable(f"Ses modeli bulunamadı: {self.model_path}")

        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise TTSUnavailable(
                "piper-tts paketi kurulu değil (pip install piper-tts)"
            ) from exc

        try:
            self._voice = PiperVoice.load(
                str(self.model_path),
                config_path=str(self.config_path) if self.config_path.exists() else None,
            )
        except Exception as exc:
            raise TTSUnavailable(f"Ses modeli yüklenemedi: {exc}") from exc

        self.sample_rate = int(getattr(self._voice.config, "sample_rate", 22050))

        self._stop = threading.Event()
        self._stream = None
        self._stream_lock = threading.Lock()

    # --- hoparlör akışı ---------------------------------------------------
    def _akis(self):
        """Sürekli açık kalan çıkış akışı; cümleler arası boşluğu önler."""
        import sounddevice as sd

        with self._stream_lock:
            if self._stream is None:
                self._stream = sd.RawOutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=0,          # sürücü kendi seçsin, daha az takılma
                    device=CFG.audio.output_device,
                    latency="low",        # sürücü tamponu küçük kalsın
                )
                self._stream.start()

                # "Ses gelmiyor" durumunda ilk bakılacak yer burası: sistem
                # varsayılanı kulaklık olabilir ama kullanıcı hoparlörden
                # dinliyor olabilir.
                try:
                    aygit = sd.query_devices(
                        self._stream.device, "output"
                    )["name"]
                except Exception:
                    aygit = str(CFG.audio.output_device)
                bus.log_threadsafe(
                    f"Ses çıkışı: {aygit} ({self.sample_rate} Hz)", "info"
                )
            return self._stream

    def _akisi_kapat(self) -> None:
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def stop(self) -> None:
        self._stop.set()
        # abort(): kuyrukta bekleyen sesi de at, yoksa durdurduktan sonra
        # birkaç yüz milisaniye daha konuşmaya devam ediyor.
        self._akisi_kapat()

    def isit(self) -> None:
        """İlk cümlenin gecikmemesi için modeli önden çalıştırır."""
        try:
            for _ in self._voice.synthesize("hazır", self._ayar()):
                break
        except Exception:
            pass

    def _ayar(self):
        from piper.config import SynthesisConfig

        return SynthesisConfig(
            length_scale=max(0.5, min(2.0, CFG.tts.speed)),
            noise_scale=CFG.tts.noise_scale,
            noise_w_scale=CFG.tts.noise_w,
            normalize_audio=True,
        )

    def speak(self, text: str) -> None:
        self._stop.clear()
        akis = self._akis()

        try:
            for parca in self._voice.synthesize(text, self._ayar()):
                if self._stop.is_set():
                    break
                ham = parca.audio_int16_bytes
                if not ham:
                    continue
                akis.write(ham)
                _emit_level(ham)
        except Exception as exc:
            bus.log_threadsafe(f"Seslendirme hatası: {exc}", "error")
            self._akisi_kapat()
        finally:
            bus.emit_threadsafe("audio.level", value=0.0, source="tts")


class SapiEngine:
    """Yedek motor: Windows'un kendi sesi. Türkçe ses paketi yoksa aksanlı okur."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def stop(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        safe = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$tr = $s.GetInstalledVoices() | Where-Object { "
            "$_.VoiceInfo.Culture.Name -eq 'tr-TR' } | Select-Object -First 1; "
            "if ($tr) { $s.SelectVoice($tr.VoiceInfo.Name) }; "
            f"$s.Speak('{safe}')"
        )
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=_CREATE_NO_WINDOW,
        )
        self._proc.wait()
        self._proc = None


def _emit_level(pcm: bytes) -> None:
    """Ham PCM'den 0-1 arası ses seviyesi çıkarıp HUD'a gönderir."""
    if len(pcm) < 2:
        return
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return
    rms = float(np.sqrt(np.mean(samples**2))) / 32768.0
    level = min(1.0, rms * 5.0)
    bus.emit_threadsafe("audio.level", value=round(level, 3), source="tts")


class Speaker:
    """TTS is parçacığı. Cümleler kuyruğa girer, sırayla seslendirilir."""

    def __init__(self) -> None:
        self.engine = None
        self.engine_name = "yok"
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._speaking = threading.Event()

    def init(self) -> str:
        if CFG.tts.engine == "piper":
            try:
                self.engine = PiperEngine(CFG.tts.voice)
                self.engine.isit()          # ilk cümle beklemesin
                self.engine_name = f"piper:{CFG.tts.voice}"
                return self.engine_name
            except TTSUnavailable as exc:
                bus.log_threadsafe(f"Piper kullanılamıyor ({exc}); SAPI'ye düşülüyor.", "warn")
        self.engine = SapiEngine()
        self.engine_name = "sapi"
        return self.engine_name

    def start(self) -> None:
        if self.engine is None:
            self.init()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tts")
        self._thread.start()

    def cikisi_yenile(self) -> None:
        """Çıkış aygıtı değişince akışı kapatır; sonraki cümlede yenisi açılır."""
        kapat = getattr(self.engine, "_akisi_kapat", None)
        if callable(kapat):
            kapat()

    def _loop(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                break
            if not text.strip():
                continue

            self._speaking.set()
            machine.set_threadsafe(State.SPEAKING)
            bus.emit_threadsafe("speech.start", text=text)
            try:
                # Ekranda özgün metin görünür, hoparlöre okunabilir hâli gider
                self.engine.speak(seslendirme_icin_hazirla(text))
            except Exception as exc:
                bus.log_threadsafe(f"Seslendirme hatası: {exc}", "error")
            finally:
                self._speaking.clear()
                bus.emit_threadsafe("speech.end", text=text)
                if self._queue.empty():
                    machine.set_threadsafe(State.IDLE)

    # --- dış arayüz -------------------------------------------------------
    def say(self, text: str) -> None:
        self._queue.put(text)

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set() or not self._queue.empty()

    def stop(self) -> None:
        """Konuşmayı anında kes ve bekleyen cümleleri at (barge-in)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if self.engine:
            self.engine.stop()
        self._speaking.clear()


speaker = Speaker()


async def speech_pump(speech_queue: asyncio.Queue) -> None:
    """Ajanin async kuyruğunu TTS is parçacığının kuyruğuna aktarır."""
    while True:
        sentence = await speech_queue.get()
        if sentence is None:
            break
        speaker.say(sentence)
