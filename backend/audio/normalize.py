"""Seslendirme öncesi metin düzeltme.

Piper rakamları ve sembolleri iyi okuyamaz. Bu katman "%44", "19:30",
"12.6 GB" gibi ifadeleri okunabilir Türkçeye çevirir, böylece dil modeline
"sayıları yazıyla yaz" gibi kırılgan bir talimat vermek gerekmez.
"""
from __future__ import annotations

import re

BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
BASAMAK = ["", "bin", "milyon", "milyar", "trilyon"]


def _uclu(n: int) -> str:
    """0-999 arası bir sayıyı yazıya çevirir."""
    parts: list[str] = []
    yuz, kalan = divmod(n, 100)
    if yuz == 1:
        parts.append("yüz")
    elif yuz > 1:
        parts.extend([BIRLER[yuz], "yüz"])

    on, bir = divmod(kalan, 10)
    if on:
        parts.append(ONLAR[on])
    if bir:
        parts.append(BIRLER[bir])
    return " ".join(parts)


def sayi_oku(n: int) -> str:
    """Tam sayıyı Türkçe okunuşuna çevirir."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + sayi_oku(-n)
    if n >= 10**15:
        return str(n)  # çok büyük; olduğu gibi bırak

    gruplar: list[int] = []
    while n:
        n, kalan = divmod(n, 1000)
        gruplar.append(kalan)

    parts: list[str] = []
    for index in range(len(gruplar) - 1, -1, -1):
        deger = gruplar[index]
        if deger == 0:
            continue
        # "bir bin" değil "bin"
        if index == 1 and deger == 1:
            parts.append("bin")
        else:
            parts.append(_uclu(deger))
            if index:
                parts.append(BASAMAK[index])
    return " ".join(p for p in parts if p)


def _ondalik_oku(tam: str, kesir: str) -> str:
    kesir = kesir.rstrip("0")
    if not kesir:                      # 17.0 -> "on yedi"
        return sayi_oku(int(tam))
    return f"{sayi_oku(int(tam))} virgül {sayi_oku(int(kesir))}"


BIRIMLER = {
    "gb": "gigabayt", "mb": "megabayt", "kb": "kilobayt", "tb": "terabayt",
    "ghz": "gigahertz", "mhz": "megahertz",
    "ms": "milisaniye", "sn": "saniye", "dk": "dakika", "sa": "saat",
    "km": "kilometre", "cm": "santimetre", "mm": "milimetre",
    "kg": "kilogram", "gr": "gram",
    "c": "santigrat derece", "°c": "santigrat derece",
}

_KISALTMALAR = {
    "vb.": "ve benzeri", "vs.": "vesaire", "örn.": "örneğin",
    "saat.": "saat", "TL": "lira", "USD": "dolar", "EUR": "euro",
}


def _saat(match: re.Match) -> str:
    saat, dakika = int(match.group(1)), int(match.group(2))
    if dakika == 0:
        return sayi_oku(saat)
    return f"{sayi_oku(saat)} {sayi_oku(dakika)}"


def _yuzde(match: re.Match) -> str:
    sayi = match.group(1)
    if "." in sayi or "," in sayi:
        tam, kesir = re.split(r"[.,]", sayi, maxsplit=1)
        return f"yüzde {_ondalik_oku(tam, kesir)}"
    return f"yüzde {sayi_oku(int(sayi))}"


def _birimli(match: re.Match) -> str:
    sayi, birim = match.group(1), match.group(2).lower()
    okunus = BIRIMLER.get(birim, birim)
    if "." in sayi or "," in sayi:
        tam, kesir = re.split(r"[.,]", sayi, maxsplit=1)
        return f"{_ondalik_oku(tam, kesir)} {okunus}"
    return f"{sayi_oku(int(sayi))} {okunus}"


def _ondalik(match: re.Match) -> str:
    return _ondalik_oku(match.group(1), match.group(2))


def _tamsayi(match: re.Match) -> str:
    raw = match.group(0).replace(".", "")
    if len(raw) > 12:
        return match.group(0)
    return sayi_oku(int(raw))


_BIRIM_DESEN = "|".join(sorted(BIRIMLER, key=len, reverse=True))

_ADIMLAR: list[tuple[re.Pattern, object]] = [
    # Önce URL: adresten sadece alan adını bırak
    (re.compile(r"https?://(?:www\.)?([^/\s]+)[^\s]*"), r"\1"),
    # Dosya yolları konuşmada anlamsız; sadece dosya adını bırak.
    # Sürücü harfinden önce başka harf gelmemeli ki "https:/" ile eşleşmesin.
    (re.compile(r"(?<![A-Za-z])[A-Za-z]:\\[^\s,;]+\\([^\\\s,;]+)"), r"\1"),
    (re.compile(r"(?<![A-Za-z])[A-Za-z]:/[^\s,;]+/([^/\s,;]+)"), r"\1"),
    # 19:30 -> on dokuz otuz
    (re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b"), _saat),
    # %44 ve 44%
    (re.compile(r"%\s*(\d+(?:[.,]\d+)?)"), _yuzde),
    (re.compile(r"\b(\d+(?:[.,]\d+)?)\s*%"), _yuzde),
    # 12.6 GB
    (re.compile(rf"\b(\d+(?:[.,]\d+)?)\s*({_BIRIM_DESEN})\b", re.IGNORECASE), _birimli),
    # 3,5 / 3.5
    (re.compile(r"\b(\d+)[.,](\d+)\b"), _ondalik),
    # 1.234 veya 1234
    (re.compile(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\b"), _tamsayi),
]

# Türkçe okunduğunda yanlış çıkan özel isimler. Ekrandaki yazı değişmez,
# sadece hoparlöre giden metin bu okunuşları kullanır.
OKUNUSLAR = {
    "Riley": "Rayli",
    "riley": "rayli",
    "RILEY": "Rayli",
    "Whisper": "Vispır",
    "Ollama": "Ollama",
    "Google": "Gugıl",
    "Chrome": "Krom",
    "YouTube": "Yutup",
    "Spotify": "Spotifay",
    "Discord": "Diskord",
    "Steam": "Istim",
    "Windows": "Vindovs",
    "Wi-Fi": "Vayfay",
    "WiFi": "Vayfay",
}

_SEMBOLLER = {
    "&": " ve ", "@": " et ", "#": " diyez ", "+": " artı ", "=": " eşittir ",
    "→": " ", "…": ".", "–": "-", "—": "-", "“": '"', "”": '"', "’": "'",
}


def seslendirme_icin_hazirla(text: str) -> str:
    """Metni Piper'a vermeden önce okunabilir hâle getirir."""
    if not text:
        return ""

    out = text
    for yazilis, okunus in OKUNUSLAR.items():
        out = out.replace(yazilis, okunus)
    for kisa, uzun in _KISALTMALAR.items():
        out = out.replace(kisa, uzun)
    for sembol, karsilik in _SEMBOLLER.items():
        out = out.replace(sembol, karsilik)

    for desen, karsilik in _ADIMLAR:
        out = desen.sub(karsilik, out)

    out = re.sub(r"\s+", " ", out).strip()
    return out


if __name__ == "__main__":  # hızlı deneme
    ornekler = [
        "Sistem durumu: işlemci %44, bellek %74 (12.6/17.0 GB), C diski %69 dolu.",
        "Saat 19:30. Toplantı 21:00'de başlıyor.",
        "Ekran görüntüsü kaydedildi: C:\\Users\\Esad\\Desktop\\ekran_2026.png",
        "1250 dosya bulundu, toplam 3.4 GB.",
        "Kaynak: https://www.example.com/haber/123",
    ]
    for ornek in ornekler:
        print(f"  {ornek}\n-> {seslendirme_icin_hazirla(ornek)}\n")
