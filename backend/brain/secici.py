"""Araç seçici: her tur için modele yalnızca ilgili becerileri gösterir.

Neden gerekli: 47 becerinin tamamını birden vermek modeli şaşırtıyor. Ölçtüğümde
altı araçla yüzde yüz doğru seçim yapan model, kırk yedi araçla "not defterini aç"
isteğine type_text, "wifi'yi kapat" isteğine shutdown çağırıyordu. Şema sayısı
gecikmeyi neredeyse hiç artırmıyor ama doğruluğu ciddi biçimde düşürüyor.

Yaklaşım: kullanıcının sözünü becerilerin ad ve açıklamalarındaki terimlerle
eşleştirip en olası on beş kadarını gönderiyoruz. Terim ağırlıkları ters belge
sıklığıyla (IDF) hesaplanıyor, yani "kullanıcı" gibi her açıklamada geçen
kelimeler puan vermiyor, "pano" gibi tek bir beceriye özgü olanlar çok veriyor.
Açıklamalarda geçmeyen gündelik kelimeler için elle yazılmış bir çağrışım
tablosu var.

Sözlük eşleşmesi ıskalarsa ajan tam listeyle bir kez daha deniyor; bu yüzden
seçici bir şeyi kaçırsa bile beceri erişilemez hâle gelmiyor.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from skills.registry import available_skills

# Her turda mutlaka gönderilenler: en sık kullanılanlar ve konuşmanın ortasında
# sözlük eşleşmesi olmadan da gerekebilecek olanlar.
CEKIRDEK = (
    "open_app", "web_search", "get_datetime", "system_stats",
    "remember", "recall", "set_volume", "take_screenshot",
)

# Açıklamalarda geçmeyen ama kullanıcının ağzından çıkacak kelimeler.
# Sağdaki listenin başındaki beceri en olası kabul edilir.
CAGRISIMLAR: dict[str, tuple[str, ...]] = {
    # uygulama adları
    "notepad": ("open_app", "close_app"),
    "defter": ("open_app", "close_app"),
    "chrome": ("open_app", "close_app", "browser_action"),
    "firefox": ("open_app", "close_app", "browser_action"),
    "edge": ("open_app", "close_app", "browser_action"),
    "spotify": ("open_app", "media_control"),
    "discord": ("open_app", "close_app"),
    "steam": ("open_app", "close_app"),
    "excel": ("open_app", "close_app"),
    "word": ("open_app", "close_app"),
    "hesap": ("open_app",),
    "paint": ("open_app",),
    "terminal": ("open_app",),
    "explorer": ("open_app", "open_path"),
    "gezgin": ("open_path", "list_dir"),
    # güncel bilgi
    "hava": ("web_search",),
    "sıcaklık": ("web_search",),
    "haber": ("web_search",),
    "dolar": ("web_search",),
    "euro": ("web_search",),
    "kur": ("web_search",),
    "borsa": ("web_search",),
    "fiyat": ("web_search",),
    "skor": ("web_search",),
    "maç": ("web_search",),
    "kim": ("web_search",),
    "nedir": ("web_search",),
    "güncel": ("web_search",),
    "bugün": ("web_search", "get_datetime"),
    # zaman
    "saat": ("get_datetime", "set_timer"),
    "tarih": ("get_datetime",),
    "gün": ("get_datetime",),
    "dakika": ("set_timer", "shutdown"),
    "hatırlat": ("set_timer", "list_timers", "cancel_timer"),
    "alarm": ("set_timer", "list_timers"),
    # sistem
    "pil": ("system_stats",),
    "batarya": ("system_stats",),
    "işlemci": ("system_stats",),
    "bellek": ("system_stats",),
    "ram": ("system_stats",),
    "disk": ("system_stats",),
    "sıcak": ("system_stats",),
    "yavaş": ("system_stats",),
    "performans": ("system_stats",),
    # ses
    "sessiz": ("mute", "set_volume"),
    "kıs": ("set_volume",),
    "aç": ("open_app", "set_volume", "open_url", "open_path"),
    "yükselt": ("set_volume",),
    "müzik": ("media_control", "open_app"),
    "şarkı": ("media_control", "search_youtube"),
    "durdur": ("media_control", "cancel_timer"),
    "duraklat": ("media_control",),
    # tarayıcı ve web
    "sekme": ("browser_action", "browser_open_tab"),
    "site": ("open_url", "browser_open_tab", "fetch_page"),
    "youtube": ("search_youtube", "browser_open_tab", "open_url"),
    "google": ("web_search", "browser_search", "open_url"),
    "video": ("search_youtube", "media_control"),
    "link": ("open_url", "fetch_page"),
    "adres": ("open_url", "browser_open_tab", "fetch_page"),
    # dosya
    "masaüstü": ("search_files", "list_dir", "take_screenshot"),
    "klasör": ("list_dir", "open_path", "search_files"),
    "dosya": ("search_files", "read_file", "write_file", "list_dir", "open_path"),
    "not": ("write_file", "remember"),
    "yaz": ("write_file", "type_text"),
    "kaydet": ("write_file", "take_screenshot"),
    "kopyala": ("clipboard_write", "clipboard_read"),
    "pano": ("clipboard_read", "clipboard_write"),
    # pencere
    "pencere": ("list_windows", "focus_window", "snap_window", "close_window",
                "get_active_window"),
    "ekran": ("take_screenshot", "snap_window", "lock_screen"),
    "büyüt": ("snap_window",),
    "küçült": ("snap_window", "minimize_all"),
    # kişisel bilgi
    "unutma": ("remember",),
    "hatırlıyor": ("recall",),
    "biliyor": ("recall",),
    "kimim": ("recall",),
    "söylemiştim": ("recall",),
    "dedim": ("recall",),
    # ayarlar
    "hızlı": ("set_speech_speed",),
    "yavaşla": ("set_speech_speed",),
    "konuş": ("set_speech_speed",),
    "hitap": ("set_address",),
    "ayar": ("get_settings", "set_speech_speed", "set_address"),
    "yetki": ("set_permission_level",),
    # kilit ve kapatma
    "kilitle": ("lock_screen",),
    "kapat": ("close_app", "close_window", "shutdown", "mute", "browser_action"),
    "yeniden": ("shutdown",),
    "restart": ("shutdown",),
}

# Bilgisayarı kapatmak yıkıcı; kullanıcı gerçekten öyle demediyse bu beceri
# listeye girmesin diye ayrıca kalıp arıyoruz.
_ZORUNLU: dict[str, tuple[str, ...]] = {
    "shutdown": ("kapat", "kapan", "yeniden başlat", "restart", "uyku"),
}

_KUCUK = str.maketrans("IİÎÂÛ", "ıiiau")
_TOKEN = re.compile(r"[a-zçğıöşü0-9]+")

_DURAK = {
    "bir", "bu", "şu", "ve", "ile", "için", "gibi", "ama", "de", "da", "mi",
    "mı", "mu", "mü", "ne", "çok", "daha", "en", "her", "ki", "ben",
    "sen", "bana", "beni", "sana", "olan", "olarak", "sonra", "önce", "var",
    "yok", "kullanıcı", "kullan", "dediğinde", "eder", "verir", "döndürür",
    "riley", "lütfen", "misin", "musun", "mısın",
}


def _sadelestir(metin: str) -> list[str]:
    metin = metin.translate(_KUCUK).lower()
    return [t for t in _TOKEN.findall(metin) if t not in _DURAK and len(t) > 1]


def _kok(kelime: str) -> str:
    """Kaba gövde: ilk beş harf.

    Tam bir biçimbilim çözümleyicisine gerek yok; amaç "kapat", "kapatır",
    "kapatsana" gibi biçimlerin aynı kutuya düşmesi.
    """
    return kelime[:5]


@lru_cache(maxsize=1)
def _terim_agirliklari() -> dict[str, dict[str, float]]:
    """Beceri başına terim ağırlıkları (TF x IDF)."""
    beceriler = list(available_skills())
    belge_sayisi = len(beceriler) or 1
    gecen: dict[str, int] = {}
    beceri_terimleri: dict[str, dict[str, int]] = {}

    for sk in beceriler:
        terimler: dict[str, int] = {}
        for parca in sk.name.split("_"):          # ad iki katı sayılır
            k = _kok(parca)
            terimler[k] = terimler.get(k, 0) + 2
        for t in _sadelestir(sk.description):
            k = _kok(t)
            terimler[k] = terimler.get(k, 0) + 1
        beceri_terimleri[sk.name] = terimler
        for k in terimler:
            gecen[k] = gecen.get(k, 0) + 1

    idf = {k: math.log(belge_sayisi / (1 + n)) + 0.2 for k, n in gecen.items()}
    return {
        ad: {k: sayi * max(0.0, idf.get(k, 0.0)) for k, sayi in terimler.items()}
        for ad, terimler in beceri_terimleri.items()
    }


def _cagrisim_puanlari(kokler: set[str]) -> dict[str, float]:
    puan: dict[str, float] = {}
    for kelime, beceriler in CAGRISIMLAR.items():
        if _kok(kelime) in kokler:
            for i, ad in enumerate(beceriler):
                puan[ad] = puan.get(ad, 0.0) + 3.0 / (1 + i * 0.5)
    return puan


def _puanla(soz: str) -> dict[str, float]:
    """Söze karşı her becerinin uygunluk puanı."""
    agirlik = _terim_agirliklari()
    kokler = {_kok(t) for t in _sadelestir(soz)}

    puan: dict[str, float] = {}
    for ad, terimler in agirlik.items():
        toplam = sum(w for k, w in terimler.items() if k in kokler)
        if toplam > 0:
            puan[ad] = toplam

    for ad, ek in _cagrisim_puanlari(kokler).items():
        puan[ad] = puan.get(ad, 0.0) + ek

    dusuk = soz.translate(_KUCUK).lower()
    for ad, kaliplar in _ZORUNLU.items():
        if ad in puan and not any(k in dusuk for k in kaliplar):
            del puan[ad]
    return puan


# Ölçülen puan dağılımı: gerçek komutlarda en yüksek puan 6,0 ile 21,9 arasında,
# sohbet cümlelerinde ("nasılsın", "bana bir şaka yap", "bugün moralim bozuk")
# en fazla 5,4 çıkıyor. Aradaki boşluk niyeti ayırmaya yetiyor.
NIYET_ESIGI = 6.0


def belirgin_niyet(soz: str) -> str | None:
    """Söz açıkça bir beceriyi işaret ediyorsa o becerinin adını verir.

    Ajan bunu emniyet ağı olarak kullanıyor: niyet belirginken model hiçbir
    araç çağırmadan geçiştiriyorsa ("panodaki metni okumak için önce onu
    almalıyız") bir kez daha, açık bir uyarıyla deneniyor.
    """
    puan = _puanla(soz)
    if not puan:
        return None
    ad, en_yuksek = max(puan.items(), key=lambda x: x[1])
    return ad if en_yuksek >= NIYET_ESIGI else None


def araclari_sec(soz: str, ust_sinir: int = 15) -> list[dict]:
    """Söze en uygun beceri şemalarını döndürür.

    Sonuç kayıt sırasını korur; modelin listedeki sıraya bakarak seçim
    yapmasını istemiyoruz.
    """
    beceriler = {s.name: s for s in available_skills()}
    if len(beceriler) <= ust_sinir:
        return [s.schema() for s in beceriler.values()]

    puan = {ad: p for ad, p in _puanla(soz).items() if ad in beceriler}

    secilen = {ad for ad in CEKIRDEK if ad in beceriler}
    kalan = ust_sinir - len(secilen)
    for ad, _ in sorted(puan.items(), key=lambda x: -x[1]):
        if kalan <= 0:
            break
        if ad not in secilen:
            secilen.add(ad)
            kalan -= 1

    return [s.schema() for ad, s in beceriler.items() if ad in secilen]


def tum_araclar() -> list[dict]:
    return [s.schema() for s in available_skills()]
