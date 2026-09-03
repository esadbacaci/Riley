"""Tarayıcı kontrolü.

Eklenti ya da hata ayıklama bağlantısı gerektirmez: komutlar öndeki tarayıcı
penceresine klavye kısayolu olarak gönderilir. Böylece Chrome, Edge, Firefox,
Brave ve türevlerinin hepsinde aynı şekilde çalışır.

Tarayıcı önde değilse önce öne getirilir; yoksa kullanıcıya söylenir.
"""
from __future__ import annotations

import time

from skills.pencere_araci import ekran_kilitli, one_getir, surec_adi
from skills.registry import SkillError, skill

# Tanıdığımız tarayıcıların süreç adları
TARAYICILAR = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "opera_gx.exe": "Opera GX",
    "vivaldi.exe": "Vivaldi",
    "arc.exe": "Arc",
    "zen.exe": "Zen",
    "librewolf.exe": "LibreWolf",
}

# İşlem adı -> (kısayol, kullanıcıya söylenecek)
EYLEMLER: dict[str, tuple[tuple[str, ...], str]] = {
    "yeni_sekme": (("ctrl", "t"), "Yeni sekme açıldı."),
    "sekmeyi_kapat": (("ctrl", "w"), "Sekme kapatıldı."),
    "kapali_sekmeyi_ac": (("ctrl", "shift", "t"), "Kapatılan sekme geri açıldı."),
    "sonraki_sekme": (("ctrl", "tab"), "Sonraki sekmeye geçildi."),
    "onceki_sekme": (("ctrl", "shift", "tab"), "Önceki sekmeye geçildi."),
    "sekmeyi_cogalt": (("alt", "shift", "d"), "Sekme çoğaltıldı."),
    "geri": (("alt", "left"), "Geri gidildi."),
    "ileri": (("alt", "right"), "İleri gidildi."),
    "yenile": (("f5",), "Sayfa yenilendi."),
    "zorla_yenile": (("ctrl", "shift", "r"), "Sayfa önbelleksiz yenilendi."),
    "ana_sayfa": (("alt", "home"), "Ana sayfaya gidildi."),
    "yer_imi_ekle": (("ctrl", "d"), "Yer imi penceresi açıldı."),
    "gecmis": (("ctrl", "h"), "Geçmiş açıldı."),
    "indirilenler": (("ctrl", "j"), "İndirilenler açıldı."),
    "gizli_pencere": (("ctrl", "shift", "n"), "Gizli pencere açıldı."),
    "yeni_pencere": (("ctrl", "n"), "Yeni pencere açıldı."),
    "tam_ekran": (("f11",), "Tam ekran değiştirildi."),
    "yakinlastir": (("ctrl", "+"), "Yakınlaştırıldı."),
    "uzaklastir": (("ctrl", "-"), "Uzaklaştırıldı."),
    "yakinlastirmayi_sifirla": (("ctrl", "0"), "Yakınlaştırma sıfırlandı."),
    "sayfayi_kaydet": (("ctrl", "s"), "Kaydetme penceresi açıldı."),
    "yazdir": (("ctrl", "p"), "Yazdırma penceresi açıldı."),
    "sekmeyi_sessize_al": (("ctrl", "m"), "Sekme sessize alındı."),
}


def _on_pencere():
    import pygetwindow as gw

    try:
        return gw.getActiveWindow()
    except Exception:
        return None


def _tarayiciyi_one_getir() -> str:
    """Öndeki pencere tarayıcı değilse bir tarayıcı bulup öne getirir.

    Komutlar klavye kısayolu olarak gönderildiği için yanlış pencereye
    gitmeleri tehlikeli olur: Ctrl+W açık bir belgeyi kapatabilir.
    """
    onde = _on_pencere()
    if onde is not None:
        ad = surec_adi(onde)
        if ad in TARAYICILAR:
            return TARAYICILAR[ad]

    if ekran_kilitli():
        raise SkillError(
            "Ekran kilitli olduğu için tarayıcıya geçemiyorum. "
            "Önce kilidi açar mısınız?"
        )

    import pygetwindow as gw

    bulunan_tarayici = ""
    for pencere in gw.getAllWindows():
        if not (pencere.title or "").strip():
            continue
        ad = surec_adi(pencere)
        if ad not in TARAYICILAR:
            continue
        bulunan_tarayici = TARAYICILAR[ad]
        if one_getir(pencere):
            return TARAYICILAR[ad]

    if bulunan_tarayici:
        raise SkillError(
            f"{bulunan_tarayici} açık ama öne getiremedim. Başka bir pencere "
            "odağı tutuyor olabilir."
        )
    raise SkillError(
        "Açık bir tarayıcı bulamadım. Önce bir tarayıcı açmamı ister misiniz?"
    )


@skill(
    name="browser_action",
    description=(
        "Tarayıcıyı klavye kısayoluyla kontrol eder: yeni sekme açma, sekme "
        "kapatma, sekmeler arası geçiş, geri, ileri, yenileme, geçmiş, "
        "indirilenler, gizli pencere, yakınlaştırma gibi. Tarayıcı önde "
        "değilse önce öne getirilir."
    ),
    params={
        "eylem": {
            "type": "string",
            "enum": sorted(EYLEMLER),
            "description": "Yapılacak işlem",
        }
    },
    required=["eylem"],
)
def browser_action(eylem: str) -> str:
    import pyautogui

    anahtar = eylem.strip().lower()
    kayit = EYLEMLER.get(anahtar)
    if kayit is None:
        raise SkillError(
            f"'{eylem}' bilinmeyen bir tarayıcı işlemi. "
            f"Şunlar olabilir: {', '.join(sorted(EYLEMLER))}"
        )

    tarayici = _tarayiciyi_one_getir()
    kisayol, mesaj = kayit
    pyautogui.hotkey(*kisayol)
    return f"{tarayici}: {mesaj}"


@skill(
    name="browser_open_tab",
    description=(
        "Tarayıcıda YENİ SEKMEDE bir adres açar. Kullanıcı 'yeni sekmede aç' "
        "dediğinde ya da tarayıcı zaten açıkken bir siteye gitmek istediğinde "
        "kullan. Tarayıcı kapalıysa open_url daha uygundur."
    ),
    params={"url": {"type": "string", "description": "Açılacak adres, örn: youtube.com"}},
    required=["url"],
)
def browser_open_tab(url: str) -> str:
    import pyautogui

    adres = url.strip()
    if not adres:
        raise SkillError("Hangi adresi açacağımı söylemediniz.")
    if not adres.startswith(("http://", "https://")):
        adres = "https://" + adres

    tarayici = _tarayiciyi_one_getir()
    pyautogui.hotkey("ctrl", "t")
    time.sleep(0.35)                  # yeni sekme yüklensin
    _adres_yaz(adres)
    return f"{tarayici}: {adres} yeni sekmede açıldı."


@skill(
    name="browser_search",
    description=(
        "Tarayıcının adres çubuğuna yazıp arama yapar. Açık tarayıcıda hızlıca "
        "bir şey aratmak için kullan. Sonuçları okuman gerekiyorsa bunun "
        "yerine web_search kullan."
    ),
    params={"query": {"type": "string", "description": "Aranacak metin"}},
    required=["query"],
)
def browser_search(query: str) -> str:
    import pyautogui

    if not query.strip():
        raise SkillError("Ne arayacağımı söylemediniz.")

    tarayici = _tarayiciyi_one_getir()
    pyautogui.hotkey("ctrl", "t")
    time.sleep(0.35)
    _adres_yaz(query.strip())
    return f"{tarayici}: '{query}' arandı."


@skill(
    name="browser_find_in_page",
    description="Açık sayfada metin arar (tarayıcının kendi bul özelliği).",
    params={"text": {"type": "string", "description": "Sayfada aranacak metin"}},
    required=["text"],
)
def browser_find_in_page(text: str) -> str:
    import pyautogui

    tarayici = _tarayiciyi_one_getir()
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.3)
    _metin_yaz(text)
    return f"{tarayici}: sayfada '{text}' arandı."


def _adres_yaz(metin: str) -> None:
    """Adres çubuğuna yazıp Enter'a basar."""
    import pyautogui

    _metin_yaz(metin)
    pyautogui.press("enter")


def _metin_yaz(metin: str) -> None:
    """Türkçe karakterler pyautogui.write ile bozulduğu için pano kullanılır.

    Pano kullanıcıya ait; ödünç alınıp geri veriliyor.
    """
    import pyautogui
    import pyperclip

    onceki = None
    try:
        onceki = pyperclip.paste()
    except Exception:
        pass

    try:
        pyperclip.copy(metin)
    except Exception as exc:
        raise SkillError(f"Panoya yazamadım: {type(exc).__name__}") from exc

    try:
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
    finally:
        if onceki is not None:
            try:
                pyperclip.copy(onceki)
            except Exception:
                pass
