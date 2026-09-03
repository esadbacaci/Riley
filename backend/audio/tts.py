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
    """Piper'i alt süreç olarak çalıştırıp ham PCM'i hoparlöre akıtır."""

    def __init__(self, voice: str) -> None:
        self.voice = voice
        self.model_path = VOICE_DIR / f"{voice}.onnx"
        self.config_path = VOICE_DIR / f"{voice}.onnx.json"

        if not PIPER_EXE.exists():
            raise TTSUnavailable(f"Piper bulunamadı: {PIPER_EXE}")
        if not self.model_path.exists():
            raise TTSUnavailable(f"Ses modeli bulunamadı: {self.model_path}")

        self.sample_rate = 22050
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.sample_rate = int(cfg.get("audio", {}).get("sample_rate", 22050))
            except Exception:
                pass

        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        import sounddevice as sd

        self._stop.clear()
        length_scale = max(0.5, min(2.0, CFG.tts.speed))

        cmd = [
            str(PIPER_EXE),
            "--model", str(self.model_path),
            "--output-raw",
            "--length_scale", str(length_scale),
            "--sentence_silence", str(CFG.tts.sentence_silence),
            "--noise_scale", str(CFG.tts.noise_scale),
            "--noise_w", str(CFG.tts.noise_w),
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(PIPER_EXE.parent),
            creationflags=_CREATE_NO_WINDOW,
        )
        proc = self._proc

        try:
            proc.stdin.write(text.encode("utf-8") + b"\n")
            proc.stdin.flush()
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            return

        stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=1024,
            device=CFG.audio.output_device,
        )
        stream.start()
        try:
            while not self._stop.is_set():
                chunk = proc.stdout.read(2048)
                if not chunk:
                    break
                stream.write(chunk)
                _emit_level(chunk)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()
            self._proc = None
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
