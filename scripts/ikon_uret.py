# -*- coding: utf-8 -*-
"""Riley'nin uygulama ikonunu üretir.

Arayüzdeki reaktör motifini çizer: koyu zemin, parlayan çekirdek ve
çevresinde kesikli halkalar. Windows'un ihtiyaç duyduğu tüm boyutlarda
tek bir .ico dosyasına yazılır.

Çalıştırma:  python scripts/ikon_uret.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
CIKTI = ROOT / "build" / "icon.ico"
PNG_CIKTI = ROOT / "docs" / "ikon.png"

# Arayüzdeki renkler
ZEMIN = (7, 15, 26)
VURGU = (51, 214, 255)
PARLAK = (190, 240, 255)

CIZIM = 1024          # yüksek çözünürlükte çiz, sonra küçült
BOYUTLAR = [16, 24, 32, 48, 64, 128, 256]


def _halka(ciz: ImageDraw.ImageDraw, merkez: float, yaricap: float,
           kalinlik: int, renk: tuple, baslangic: float = 0,
           bitis: float = 360) -> None:
    kutu = [merkez - yaricap, merkez - yaricap, merkez + yaricap, merkez + yaricap]
    ciz.arc(kutu, baslangic, bitis, fill=renk, width=kalinlik)


def ikon_ciz() -> Image.Image:
    boyut = CIZIM
    m = boyut / 2

    # --- zemin: yuvarlak, hafif degradeli ---
    resim = Image.new("RGBA", (boyut, boyut), (0, 0, 0, 0))
    ciz = ImageDraw.Draw(resim)
    ciz.ellipse([0, 0, boyut, boyut], fill=ZEMIN + (255,))

    # kenar halkası
    ciz.ellipse([6, 6, boyut - 6, boyut - 6], outline=VURGU + (90,), width=6)

    # --- dış kesikli halka ---
    for i in range(4):
        _halka(ciz, m, boyut * 0.42, 10, VURGU + (150,),
               baslangic=i * 90 + 10, bitis=i * 90 + 70)

    # --- orta halka: ince ve tam ---
    _halka(ciz, m, boyut * 0.34, 5, VURGU + (110,))

    # --- ses çubukları: reaktörün imzası ---
    for i in range(48):
        aci = (i / 48) * 2 * math.pi
        uzunluk = boyut * (0.035 + 0.028 * abs(math.sin(i * 1.7)))
        ic = boyut * 0.26
        x1, y1 = m + math.cos(aci) * ic, m + math.sin(aci) * ic
        x2 = m + math.cos(aci) * (ic + uzunluk)
        y2 = m + math.sin(aci) * (ic + uzunluk)
        ciz.line([x1, y1, x2, y2], fill=VURGU + (200,), width=7)

    # --- parıltı katmanı ---
    parilti = Image.new("RGBA", (boyut, boyut), (0, 0, 0, 0))
    pciz = ImageDraw.Draw(parilti)
    pciz.ellipse([m - boyut * 0.22, m - boyut * 0.22,
                  m + boyut * 0.22, m + boyut * 0.22],
                 fill=VURGU + (170,))
    parilti = parilti.filter(ImageFilter.GaussianBlur(boyut * 0.06))
    resim = Image.alpha_composite(resim, parilti)

    # --- çekirdek ---
    ciz = ImageDraw.Draw(resim)
    ciz.ellipse([m - boyut * 0.16, m - boyut * 0.16,
                 m + boyut * 0.16, m + boyut * 0.16],
                fill=VURGU + (255,))
    ciz.ellipse([m - boyut * 0.085, m - boyut * 0.085,
                 m + boyut * 0.085, m + boyut * 0.085],
                fill=PARLAK + (255,))

    # --- çekirdek içindeki üçgen (arayüzdeki motif) ---
    ucgen = []
    for i in range(3):
        aci = -math.pi / 2 + i * (2 * math.pi / 3)
        ucgen.append((m + math.cos(aci) * boyut * 0.115,
                      m + math.sin(aci) * boyut * 0.115))
    ciz.polygon(ucgen, outline=ZEMIN + (200,))
    ciz.line(ucgen + [ucgen[0]], fill=ZEMIN + (210,), width=9)

    return resim


def main() -> None:
    resim = ikon_ciz()

    CIKTI.parent.mkdir(parents=True, exist_ok=True)
    PNG_CIKTI.parent.mkdir(parents=True, exist_ok=True)

    # Küçük boyutlarda ayrıntı kaybolmasın diye her boyut ayrı küçültülür
    kareler = [resim.resize((b, b), Image.LANCZOS) for b in BOYUTLAR]
    kareler[-1].save(CIKTI, format="ICO",
                     sizes=[(b, b) for b in BOYUTLAR])
    resim.resize((512, 512), Image.LANCZOS).save(PNG_CIKTI)

    print(f"ikon yazıldı : {CIKTI}  ({CIKTI.stat().st_size / 1024:.0f} KB)")
    print(f"önizleme     : {PNG_CIKTI}")
    print(f"boyutlar     : {', '.join(str(b) for b in BOYUTLAR)}")


if __name__ == "__main__":
    main()
