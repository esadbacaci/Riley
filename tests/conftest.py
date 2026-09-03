"""Testler için ortak hazırlık.

Riley'nin modülleri 'backend' dizini yolda olacak şekilde yazılmıştır
(config, audio.stt gibi düz importlar). Testler de aynı düzeni kurar.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
