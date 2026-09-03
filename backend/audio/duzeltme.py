"""Konuşma tanıma sonrası düzeltme.

Whisper Türkçe konuşma içindeki yabancı marka ve uygulama adlarını sık
yanlış yazar: "Chrome" yerine "Krom", "Jehrome", "Kroym" gibi. Bu katman
iki aşamada düzeltir:

  1. Bilinen karışıklık sözlüğü — kesin ve hızlı.
  2. Bilgisayarda gerçekten kurulu uygulama adlarına benzerlik eşleştirmesi
     — yalnızca "aç / kapat / başlat" gibi bir fiilin yanındaki sözcüklerde
     çalışır ki normal Türkçe kelimeler bozulmasın.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

# Whisper'ın Türkçe konuşmada bu adları yazma biçimleri.
# Anahtarlar sadeleştirilmiş (Türkçe karakterleri açılmış) küçük harftir.
KARISIKLIKLAR: dict[str, str] = {
    # Chrome
    "krom": "Chrome", "kroom": "Chrome", "kroym": "Chrome", "krum": "Chrome",
    "kroma": "Chrome", "jehrome": "Chrome", "cehrome": "Chrome",
    "gehrome": "Chrome", "chrom": "Chrome", "krome": "Chrome",
    "krumac": "Chrome", "kromu": "Chrome", "kromo": "Chrome",
    # Google
    "gugil": "Google", "gugl": "Google", "gogle": "Google", "gugil'e": "Google",
    "gobi": "Google", "gorge": "Google", "gorg": "Google", "kog": "Google",
    "guguel": "Google", "gugle": "Google",
    # Spotify
    "spotifay": "Spotify", "spotify'i": "Spotify", "spatify": "Spotify",
    "sportify": "Spotify", "spotifai": "Spotify",
    # YouTube
    "yutup": "YouTube", "yutub": "YouTube", "youtub": "YouTube",
    "yutube": "YouTube", "yu tüp": "YouTube",
    # Diğer sık kullanılanlar
    "diskord": "Discord", "diskort": "Discord",
    "vatsap": "WhatsApp", "votsap": "WhatsApp", "watsap": "WhatsApp",
    "telegram'i": "Telegram",
    "istim": "Steam", "stim": "Steam", "sitim": "Steam",
    "fayrfoks": "Firefox", "firefoks": "Firefox",
    "vs kod": "VSCode", "vs code": "VSCode", "vskod": "VSCode",
    "eksel": "Excel", "excell": "Excel",
    "vörd": "Word", "vord": "Word",
    "fotoşop": "Photoshop", "fotosop": "Photoshop",
    "netflix'i": "Netflix",
    "not tefteri": "not defteri", "note tefteri": "not defteri",
    "nottefteri": "not defteri", "not tefterini": "not defterini",
    "note tefterini": "not defterini",
    "masa sünder": "masaüstünde", "masa üstünde": "masaüstünde",
    "masa üstü": "masaüstü",
}

# Uygulama adı düzeltmesinin çalışacağı bağlam: bu fiillerden biri cümlede
# geçmiyorsa benzerlik eşleştirmesi hiç denenmez.
_FIIL_KALIBI = re.compile(
    r"\b(aç|açar|açsana|başlat|çalıştır|kapat|kapatır|göster|geç)\w*\b",
    re.IGNORECASE,
)

# Bu sözcükler gerçek Türkçe kelimeler; benzerlik eşleştirmesine sokulmaz.
_KORUNANLAR = {
    "aç", "açar", "kapat", "başlat", "çalıştır", "göster", "bir", "bana",
    "sesi", "dosya", "klasör", "ekran", "görüntüsü", "yüzde", "sonra",
    "masaüstü", "masaüstünde", "belgeler", "müzik", "video", "not",
    "defteri", "defterini", "hesap", "makinesi", "ayarlar", "saat", "dakika",
}


def _sadelestir(metin: str) -> str:
    return metin.translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")).lower()


@lru_cache(maxsize=1)
def _uygulama_adlari() -> list[str]:
    """Başlat menüsündeki kısayol adları; düzeltmenin sözlüğü."""
    try:
        from skills.apps import ALIASES, _shortcut_index

        adlar = set(_shortcut_index().keys()) | set(ALIASES.keys())
        # Tek harfli ya da çok uzun girdiler eşleştirme için işe yaramaz
        return [a for a in adlar if 3 <= len(a) <= 24]
    except Exception:
        return []


def duzelt(metin: str) -> str:
    """Çözümlenmiş metni komut olarak işlenmeden önce düzeltir."""
    if not metin:
        return metin

    sonuc = metin

    # --- 1. Bilinen karışıklıklar (önce iki sözcüklüler) ---
    for yanlis, dogru in sorted(
        KARISIKLIKLAR.items(), key=lambda kv: -len(kv[0])
    ):
        if " " in yanlis:
            desen = re.compile(re.escape(yanlis), re.IGNORECASE)
            sonuc = desen.sub(dogru, sonuc)

    parcalar = re.split(r"(\W+)", sonuc)
    for i, parca in enumerate(parcalar):
        if not parca.strip():
            continue
        karsilik = KARISIKLIKLAR.get(_sadelestir(parca))
        if karsilik:
            parcalar[i] = karsilik
    sonuc = "".join(parcalar)

    # --- 2. Kurulu uygulamalara benzerlik (yalnızca fiil bağlamında) ---
    if not _FIIL_KALIBI.search(sonuc):
        return sonuc

    adlar = _uygulama_adlari()
    if not adlar:
        return sonuc

    parcalar = re.split(r"(\W+)", sonuc)
    for i, parca in enumerate(parcalar):
        sade = _sadelestir(parca)
        if len(sade) < 4 or sade in _KORUNANLAR:
            continue
        # Zaten tanınan bir uygulama adıysa dokunma
        if sade in adlar:
            continue
        yakin = difflib.get_close_matches(sade, adlar, n=1, cutoff=0.8)
        if yakin:
            parcalar[i] = yakin[0]
    return "".join(parcalar)


if __name__ == "__main__":  # hızlı deneme
    ornekler = [
        "Krumac mısın Google Krumac",
        "Gobi, Jehrome, aç",
        "Kroym'u aç",
        "not tefterini aç",
        "spotifay'ı aç ve müziği başlat",
        "masa sünder rapor diye bir dosya var mı",
        "yutup'ta lofi müzik ara",
        "Bugün hava nasıl olacak",
        "sesi yüzde otuza indir",
    ]
    for o in ornekler:
        print(f"  {o}\n-> {duzelt(o)}\n")
