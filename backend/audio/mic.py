"""Mikrofon hattı: sürekli dinleme, adıyla uyandırma, sessizlikle konuşma sonu
tespiti ve metne çevirme.

Tek bir ses akışı vardır ve şu sırayla işler:

  1. webrtcvad ile konuşma parçaları ayıklanır (sessizlik = cümle bitti).
  2. Parça Whisper'a verilir.
  3. Riley uykudaysa metnin başında adı aranır: "Riley, sesi kıs".
     Adı varsa ad ayıklanır, kalanı komut olarak işlenir.
  4. Riley az önce cevap verdiyse kısa bir "devam penceresi" açıktır;
     bu sürede adı söylemeden konuşmaya devam edilebilir.

İsteğe bağlı olarak openWakeWord ("hey jarvis" gibi hazır modeller) da
kullanılabilir; config.wake.mode ile seçilir.
"""
from __future__ import annotations

import collections
import queue
import re
import threading
import time

import numpy as np

from audio.stt import is_noise, transcriber
from config import CFG, MODELS_DIR
from core.bus import bus
from core.state import State, machine

FRAME_MS = CFG.audio.block_ms          # 30 ms
SR = CFG.audio.sample_rate             # 16000
FRAME_LEN = SR * FRAME_MS // 1000      # 480 örnek
WW_CHUNK = 1280                        # openWakeWord 80 ms'lik parça bekler
PREROLL_FRAMES = 10                    # konuşma başı kesilmesin diye ~300 ms

def _ad_kalibi_uret() -> re.Pattern:
    """Yapılandırmadaki sesleniş biçimlerinden bir kalıp üretir.

    Whisper aynı sesi her zaman aynı yazmaz, bu yüzden liste geniş tutulur.
    Sondaki ek deseni Türkçe ekleri yakalar: "Riley'e", "Rayli'ye".

    Burada Türkçe karakterler bilerek sadeleştirilmez: "raylı sistem" gibi
    gerçek tabirler "rayli" ile karışmasın diye ı ile i ayrı tutulur.
    """
    secenekler = sorted(
        (ad.lower() for ad in CFG.wake.names), key=len, reverse=True
    )
    govde = "|".join(re.escape(ad) for ad in secenekler)
    # IGNORECASE kullanılmaz: Unicode kurallarında 'ı' ile 'i' aynı büyük
    # harfe ('I') çıktığı için "raylı" ile "rayli" eşleşiyordu. Metin zaten
    # küçük harfe çevrilerek geliyor.
    return re.compile(
        r"^\s*(?:hey\s+|ey\s+|hey,\s*)?"
        rf"(?:{govde})"
        r"(?:['’][a-zçğıöşü]{1,3})?"      # "riley'e", "rayli'ye"
        r"(?![a-zçğıöşü])"                     # "asistanım" uyandırmasın
        r"\s*[,.!?:;]*\s*"
    )


def _fold(text: str) -> str:
    """Türkçe karakterleri sadeleştirir; kalıp eşleştirmesi için."""
    table = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
    return text.translate(table).lower()


_AD_KALIBI: re.Pattern | None = None


def ad_kalibi() -> re.Pattern:
    global _AD_KALIBI
    if _AD_KALIBI is None:
        _AD_KALIBI = _ad_kalibi_uret()
    return _AD_KALIBI


class WakeWord:
    """openWakeWord sarmalayıcısı. Model yoksa sessizce devre dışı kalır."""

    def __init__(self) -> None:
        self.model = None
        self.ready = False
        self._buffer = np.zeros(0, dtype=np.int16)
        self._last_fire = 0.0

    def load(self) -> bool:
        if CFG.wake.mode != "wakeword":
            return False
        try:
            import openwakeword
            from openwakeword.model import Model

            target = MODELS_DIR / "wakeword"
            target.mkdir(parents=True, exist_ok=True)
            try:
                openwakeword.utils.download_models(
                    model_names=[CFG.wake.model], target_directory=str(target)
                )
            except Exception as exc:
                bus.log_threadsafe(f"Uyandırma modeli indirilemedi: {exc}", "warn")

            wake_models = list(target.glob(f"*{CFG.wake.model}*.onnx"))
            melspec = target / "melspectrogram.onnx"
            embedding = target / "embedding_model.onnx"
            if not wake_models or not melspec.exists() or not embedding.exists():
                bus.log_threadsafe(
                    "Uyandırma modeli dosyaları eksik; adla uyandırma kullanılacak.",
                    "warn",
                )
                return False

            # Yardımcı modellerin yolu açıkça verilmezse kütüphane kendi paket
            # dizininde arar ve bulamaz.
            self.model = Model(
                wakeword_models=[str(wake_models[0])],
                melspec_model_path=str(melspec),
                embedding_model_path=str(embedding),
                inference_framework="onnx",
            )
            self.ready = True
            bus.log_threadsafe(f"Uyandırma kelimesi hazır: {CFG.wake.model}", "info")
            return True
        except Exception as exc:
            bus.log_threadsafe(f"Uyandırma kelimesi devre dışı: {exc}", "warn")
            return False

    def feed(self, frame: np.ndarray) -> float:
        if not self.ready:
            return 0.0

        self._buffer = np.concatenate([self._buffer, frame])
        best = 0.0
        while self._buffer.size >= WW_CHUNK:
            chunk, self._buffer = self._buffer[:WW_CHUNK], self._buffer[WW_CHUNK:]
            scores = self.model.predict(chunk)
            best = max(best, max(scores.values()) if scores else 0.0)

        if best >= CFG.wake.threshold:
            now = time.time()
            if now - self._last_fire < CFG.wake.cooldown_s:
                return 0.0
            self._last_fire = now
            self.model.reset()
            self._buffer = np.zeros(0, dtype=np.int16)
        return best


class Listener:
    def __init__(self, on_utterance) -> None:
        """on_utterance: komut metni hazır olduğunda çağrılan geri arama."""
        self.on_utterance = on_utterance
        self.wake = WakeWord()
        self.vad = None

        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stream = None
        self._worker: threading.Thread | None = None
        self._running = threading.Event()

        self._capturing = False
        self._speech: list[np.ndarray] = []
        self._preroll: collections.deque[np.ndarray] = collections.deque(
            maxlen=PREROLL_FRAMES
        )
        self._silence_ms = 0
        self._voiced_ms = 0
        self._level_tick = 0

        self._armed_until = 0.0   # bu ana kadar ad söylemeden konuşulabilir
        self._forced = False      # kısayol / arayüz ile zorla dinleme

    # --- kurulum ----------------------------------------------------------
    def start(self) -> None:
        import sounddevice as sd
        import webrtcvad

        self.vad = webrtcvad.Vad(CFG.stt.vad_aggressiveness)
        self.wake.load()

        def callback(indata, frames, time_info, status):
            try:
                self._frames.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        self._stream = sd.InputStream(
            samplerate=SR,
            channels=1,
            dtype="int16",
            blocksize=FRAME_LEN,
            device=CFG.audio.input_device,
            callback=callback,
        )
        self._stream.start()

        self._running.set()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="mic")
        self._worker.start()

        nasil = CFG.wake.model if self.wake.ready else f"\"{CFG.persona.name}\" de"
        bus.log_threadsafe(f"Mikrofon dinlemede — uyandırma: {nasil}", "info")

    def stop(self) -> None:
        self._running.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    # --- dış tetikleyici (kısayol tuşu / arayüz düğmesi) ------------------
    def trigger(self) -> None:
        self._forced = True
        self._armed_until = time.time() + CFG.wake.follow_up_s

    def arm_follow_up(self) -> None:
        """Riley cevabını bitirdi; kısa süre ad söylemeden devam edilebilsin."""
        self._armed_until = time.time() + CFG.wake.follow_up_s

    @property
    def _armed(self) -> bool:
        return self._forced or time.time() < self._armed_until

    # --- ana döngü --------------------------------------------------------
    def _loop(self) -> None:
        from audio.tts import speaker

        while self._running.is_set():
            try:
                frame = self._frames.get(timeout=0.5)
            except queue.Empty:
                continue

            self._emit_level(frame)

            # Riley konuşurken kendi sesini yazmasın. Sözü ancak hazır
            # uyandırma modeli varsa kesilebilir.
            if speaker.is_speaking:
                if self.wake.ready and self.wake.feed(frame) >= CFG.wake.threshold:
                    speaker.stop()
                    bus.emit_threadsafe("wake", score=1.0, barge_in=True)
                    self._armed_until = time.time() + CFG.wake.follow_up_s
                    self._begin_capture("söz kesme")
                continue

            if not self._capturing:
                self._preroll.append(frame)
                if self.wake.ready and self.wake.feed(frame) >= CFG.wake.threshold:
                    bus.emit_threadsafe("wake", score=1.0, barge_in=False)
                    self._armed_until = time.time() + CFG.wake.follow_up_s
                    self._begin_capture("uyandırma")
                    continue

            self._consume(frame)

    def _emit_level(self, frame: np.ndarray) -> None:
        self._level_tick += 1
        if self._level_tick % 2:            # ~60 ms'de bir yeter
            return
        from audio.tts import speaker

        if speaker.is_speaking:
            return                          # dalgayı TTS sürüyor
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) / 32768.0
        bus.emit_threadsafe(
            "audio.level", value=round(min(1.0, rms * 8.0), 3), source="mic"
        )

    def _begin_capture(self, kaynak: str) -> None:
        self._capturing = True
        self._speech = list(self._preroll)
        self._silence_ms = 0
        self._voiced_ms = 0
        if self._armed:
            machine.set_threadsafe(State.LISTENING, kaynak)

    def _consume(self, frame: np.ndarray) -> None:
        try:
            is_speech = self.vad.is_speech(frame.tobytes(), SR)
        except Exception:
            is_speech = bool(np.abs(frame).mean() > 400)

        if not self._capturing:
            if not is_speech:
                return
            self._begin_capture("ses")

        self._speech.append(frame)
        if is_speech:
            self._voiced_ms += FRAME_MS
            self._silence_ms = 0
        else:
            self._silence_ms += FRAME_MS

        total_ms = len(self._speech) * FRAME_MS
        too_long = total_ms >= CFG.stt.max_utterance_s * 1000
        finished = self._silence_ms >= CFG.stt.silence_ms and self._voiced_ms > 0
        gave_up = self._silence_ms >= 1500 and self._voiced_ms == 0

        if gave_up:
            self._end_capture(transcribe=False)
        elif finished or too_long:
            self._end_capture(transcribe=self._voiced_ms >= CFG.stt.min_utterance_ms)

    def _end_capture(self, transcribe: bool) -> None:
        chunks, self._speech = self._speech, []
        self._capturing = False
        armed = self._armed
        self._forced = False

        if not transcribe or not chunks:
            machine.set_threadsafe(State.IDLE)
            return

        audio = np.concatenate(chunks).astype(np.float32) / 32768.0
        if armed:
            machine.set_threadsafe(State.THINKING, "çözümleniyor")

        started = time.time()
        try:
            text = transcriber.transcribe(audio)
        except Exception as exc:
            bus.log_threadsafe(f"Çözümleme hatası: {exc}", "error")
            machine.set_threadsafe(State.IDLE)
            return

        elapsed = time.time() - started
        if not text or is_noise(text):
            machine.set_threadsafe(State.IDLE)
            return

        komut = self._komuta_cevir(text, armed)
        if komut is None:
            bus.log_threadsafe(f"(bana değil) {text[:70]}", "debug")
            machine.set_threadsafe(State.IDLE)
            return

        bus.emit_threadsafe(
            "transcript", text=komut, final=True, seconds=round(elapsed, 2)
        )
        self.on_utterance(komut)

    def _komuta_cevir(self, text: str, armed: bool) -> str | None:
        """Söz bize mi söylendi? Öyleyse adı ayıklayıp komutu döndürür."""
        eslesme = ad_kalibi().match(text.lower())
        if eslesme:
            kalan = text[eslesme.end():].strip(" ,.!?:;")
            self._armed_until = time.time() + CFG.wake.follow_up_s
            if kalan:
                return kalan
            # Sadece adı söylenmiş: dinlemeye geç ve karşılık ver
            bus.emit_threadsafe("wake", score=1.0, barge_in=False)
            machine.set_threadsafe(State.LISTENING, "adıyla çağrıldı")
            return None

        return text if armed else None
