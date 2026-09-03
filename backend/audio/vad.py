"""Konuşma var mı yok mu kararı.

webrtcvad ham ses genliğine bakıyor: klavye sesi, fan, kapı çarpması gibi
şeyleri konuşma sanıyor, kısık konuşmayı ise kaçırıyor. Silero VAD küçük
bir sinir ağı ve gerçek konuşmayı belirgin biçimde daha iyi ayırt ediyor;
model 1.8 MB ve işlemcide çerçeve başına bir milisaniyenin altında çalışıyor.

Silero yüklenemezse webrtcvad'a, o da yoksa basit enerji eşiğine düşülür;
Riley hiçbir durumda sağır kalmaz.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from config import CFG, MODELS_DIR
from core.bus import bus

SILERO_YOLU = MODELS_DIR / "wakeword" / "silero_vad.onnx"

# Silero v4 16 kHz'de bu pencere boyutlarını kabul eder
SILERO_PENCERE = 512


class SileroVAD:
    """Silero VAD sarmalayıcısı. Durum (LSTM) çerçeveler arasında taşınır."""

    def __init__(self, yol: Path = SILERO_YOLU) -> None:
        import onnxruntime as ort

        secenekler = ort.SessionOptions()
        secenekler.inter_op_num_threads = 1
        secenekler.intra_op_num_threads = 1
        secenekler.log_severity_level = 4

        self._oturum = ort.InferenceSession(
            str(yol), sess_options=secenekler, providers=["CPUExecutionProvider"]
        )
        self._sr = np.array(CFG.audio.sample_rate, dtype=np.int64)
        self.sifirla()

    def sifirla(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def olasilik(self, frame: np.ndarray) -> float:
        """Çerçevede konuşma olma olasılığı (0-1)."""
        ses = frame.astype(np.float32) / 32768.0
        if ses.size < SILERO_PENCERE:
            ses = np.pad(ses, (0, SILERO_PENCERE - ses.size))
        elif ses.size > SILERO_PENCERE:
            ses = ses[:SILERO_PENCERE]

        cikti, self._h, self._c = self._oturum.run(
            None,
            {
                "input": ses[None, :],
                "sr": self._sr,
                "h": self._h,
                "c": self._c,
            },
        )
        return float(cikti[0][0])


class KonusmaTespiti:
    """Riley'nin kullandığı arayüz: bir çerçeve ver, konuşma mı söyle."""

    def __init__(self) -> None:
        self.yontem = "enerji"
        self._silero: SileroVAD | None = None
        self._webrtc = None

        if CFG.stt.vad_yontemi in ("auto", "silero") and SILERO_YOLU.exists():
            try:
                self._silero = SileroVAD()
                self.yontem = "silero"
            except Exception as exc:
                bus.log_threadsafe(f"Silero VAD yüklenemedi: {exc}", "warn")

        if self._silero is None and CFG.stt.vad_yontemi != "enerji":
            try:
                import webrtcvad

                self._webrtc = webrtcvad.Vad(CFG.stt.vad_aggressiveness)
                self.yontem = "webrtcvad"
            except Exception:
                pass

    def sifirla(self) -> None:
        if self._silero is not None:
            self._silero.sifirla()

    def konusma_mi(self, frame: np.ndarray) -> bool:
        if self._silero is not None:
            return self._silero.olasilik(frame) >= CFG.stt.vad_esigi

        if self._webrtc is not None:
            try:
                return self._webrtc.is_speech(frame.tobytes(), CFG.audio.sample_rate)
            except Exception:
                pass

        # Son çare: basit enerji eşiği
        return bool(np.abs(frame).mean() > 400)
