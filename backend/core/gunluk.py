"""Diske yazılan günlük.

Konsol çıktısı uçucudur: Riley'yi tepside çalıştırınca kimse görmez.
Bu katman aynı olayları döndürmeli bir dosyaya da yazar, böylece bir
sorun olduğunda geriye dönüp bakılabilir ve dosya sınırsız büyümez.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import DATA_DIR

GUNLUK_DOSYASI = DATA_DIR / "logs" / "riley.log"
AZAMI_BOYUT = 2 * 1024 * 1024      # 2 MB
YEDEK_SAYISI = 3                   # riley.log.1 ... .3

_kaydedici: logging.Logger | None = None


def kaydedici() -> logging.Logger:
    """Döndürmeli dosya günlüğünü hazırlar (bir kez)."""
    global _kaydedici
    if _kaydedici is not None:
        return _kaydedici

    log = logging.getLogger("riley")
    log.setLevel(logging.DEBUG)
    log.propagate = False

    GUNLUK_DOSYASI.parent.mkdir(parents=True, exist_ok=True)
    try:
        tutamak = RotatingFileHandler(
            GUNLUK_DOSYASI,
            maxBytes=AZAMI_BOYUT,
            backupCount=YEDEK_SAYISI,
            encoding="utf-8",
        )
        tutamak.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        log.addHandler(tutamak)
    except Exception as exc:      # günlük yazamamak sistemi durdurmamalı
        print(f"[günlük] dosyaya yazılamıyor: {exc}", flush=True)

    _kaydedici = log
    return log


_SEVIYELER = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def yaz(mesaj: str, seviye: str = "info") -> None:
    try:
        kaydedici().log(_SEVIYELER.get(seviye, logging.INFO), mesaj)
    except Exception:
        pass
