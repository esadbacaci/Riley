"""Pencere yönetimi ve bağlam becerileri.

Riley'nin ekranı "görmesi" için bir görüntü modeli gerekmez; hangi pencerenin
önde olduğunu ve başlığını bilmek çoğu isteğe yeter: "bunu kaydet",
"şunu kapat", "hangi dosyadayım".
"""
from __future__ import annotations

from skills.registry import SkillError, skill

# Windows'un kendi kenara yaslama kısayolları en güvenilir yol; el ile
# konumlandırma çok monitörlü kurulumlarda kolayca yanlış yere düşüyor.
_YASLAMA = {
    "sol": ("win", "left"),
    "sag": ("win", "right"),
    "sağ": ("win", "right"),
    "buyut": ("win", "up"),
    "büyüt": ("win", "up"),
    "kucult": ("win", "down"),
    "küçült": ("win", "down"),
}


def _pencereler():
    import pygetwindow as gw

    return [w for w in gw.getAllWindows() if (w.title or "").strip()]


def _bul(baslik: str):
    hedef = baslik.strip().lower()
    adaylar = [w for w in _pencereler() if hedef in (w.title or "").lower()]
    if not adaylar:
        raise SkillError(f"'{baslik}' başlığıyla eşleşen pencere yok.")
    return adaylar[0]


@skill(
    name="get_active_window",
    description=(
        "Şu anda önde olan pencerenin başlığını ve uygulamasını söyler. "
        "Kullanıcı 'bu', 'şu an baktığım', 'açık olan' gibi belirsiz bir şeyden "
        "bahsettiğinde neye baktığını anlamak için kullan."
    ),
    level="narrow",
)
def get_active_window() -> str:
    import pygetwindow as gw

    try:
        pencere = gw.getActiveWindow()
    except Exception as exc:
        raise SkillError(f"Aktif pencere okunamadı: {exc}") from exc

    if pencere is None or not (pencere.title or "").strip():
        return "Şu anda önde bir pencere yok, masaüstündesiniz."

    uygulama = _pencere_uygulamasi(pencere)
    ek = f" ({uygulama})" if uygulama else ""
    return f"Önde olan pencere: {pencere.title}{ek}"


def _pencere_uygulamasi(pencere) -> str:
    """Pencerenin hangi programa ait olduğunu bulur."""
    try:
        import ctypes

        import psutil

        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(pencere._hWnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name()
    except Exception:
        return ""


@skill(
    name="snap_window",
    description=(
        "Pencereyi ekranın bir kenarına yaslar, büyütür ya da küçültür. "
        "Başlık verilmezse öndeki pencereye uygulanır."
    ),
    params={
        "yon": {
            "type": "string",
            "enum": ["sol", "sag", "buyut", "kucult"],
            "description": "Yaslama yönü",
        },
        "title": {
            "type": "string",
            "description": "Pencere başlığının bir parçası; boşsa öndeki pencere",
        },
    },
    required=["yon"],
)
def snap_window(yon: str, title: str = "") -> str:
    import pyautogui

    tuslar = _YASLAMA.get(yon.strip().lower())
    if not tuslar:
        raise SkillError(f"'{yon}' bilinmeyen bir yön. sol, sag, buyut, kucult olabilir.")

    hedef_ad = "öndeki pencere"
    if title:
        pencere = _bul(title)
        hedef_ad = pencere.title
        from skills.pencere_araci import one_getir

        if not one_getir(pencere):
            raise SkillError(f"'{hedef_ad}' penceresi öne getirilemedi.")

    pyautogui.hotkey(*tuslar)
    etiketler = {
        "sol": "sola yaslandı", "sag": "sağa yaslandı", "sağ": "sağa yaslandı",
        "buyut": "büyütüldü", "büyüt": "büyütüldü",
        "kucult": "küçültüldü", "küçült": "küçültüldü",
    }
    return f"{hedef_ad} {etiketler[yon.strip().lower()]}."


@skill(
    name="minimize_all",
    description="Tüm pencereleri küçültüp masaüstünü gösterir.",
)
def minimize_all() -> str:
    import pyautogui

    pyautogui.hotkey("win", "d")
    return "Masaüstü gösterildi."


@skill(
    name="close_window",
    description=(
        "Adı verilen pencereyi kapatır. Uygulamanın tamamını değil yalnızca "
        "o pencereyi kapatmak için kullan; tüm uygulamayı kapatmak için "
        "close_app kullan."
    ),
    params={"title": {"type": "string", "description": "Pencere başlığının bir parçası"}},
    required=["title"],
)
def close_window(title: str) -> str:
    pencere = _bul(title)
    ad = pencere.title
    try:
        pencere.close()
    except Exception as exc:
        raise SkillError(f"Pencere kapatılamadı: {exc}") from exc
    return f"'{ad}' penceresi kapatıldı."
