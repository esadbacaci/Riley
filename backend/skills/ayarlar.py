"""Riley'nin kendi ayarlarını sesle değiştirebilmesi.

"Biraz daha hızlı konuş", "bana Esad diye hitap et", "yetkilerini kıs"
gibi istekler ayarlar penceresini açmadan halledilir. Değişiklikler diske
yazılır ve arayüz olay veri yolundan haberdar edilir.
"""
from __future__ import annotations

from config import CFG
from core.bus import bus
from skills.registry import SkillError, skill

# Piper'da length_scale küçüldükçe konuşma hızlanır. Kullanıcı "hızlandır"
# dediğinde değeri düşürmemiz gerekiyor; bu ters ilişkiyi burada saklıyoruz.
HIZ_ADIMI = 0.08
HIZ_ALT = 0.60
HIZ_UST = 1.30


def _degisikligi_duyur(alan: str, deger) -> None:
    bus.emit_threadsafe("settings.changed", field=alan, value=deger)


def _kaydet() -> None:
    try:
        CFG.save()
    except Exception as exc:
        raise SkillError(f"Ayar kaydedilemedi: {exc}") from exc


@skill(
    name="set_speech_speed",
    description=(
        "Riley'nin konuşma hızını değiştirir. Kullanıcı 'daha hızlı konuş', "
        "'biraz yavaşla', 'normal hızda konuş' dediğinde kullan. Yön yerine "
        "doğrudan bir değer de verilebilir (0.6 çok hızlı, 1.3 çok yavaş)."
    ),
    params={
        "yon": {
            "type": "string",
            "enum": ["hizlandir", "yavaslat", "normal"],
            "description": "Hızlandır, yavaşlat ya da varsayılana dön",
        },
        "deger": {
            "type": "number",
            "description": "İsteğe bağlı doğrudan değer, 0.6 ile 1.3 arası",
        },
    },
)
def set_speech_speed(yon: str = "", deger: float | None = None) -> str:
    onceki = CFG.tts.speed
    varsayilana_don = False

    if deger is not None:
        yeni = float(deger)
    elif yon == "normal":
        yeni = 0.80
        varsayilana_don = True
    elif yon == "hizlandir":
        yeni = onceki - HIZ_ADIMI      # küçük değer = hızlı
    elif yon == "yavaslat":
        yeni = onceki + HIZ_ADIMI
    else:
        raise SkillError("Hızı nasıl değiştireyim? Hızlandır ya da yavaşlat de.")

    yeni = round(max(HIZ_ALT, min(HIZ_UST, yeni)), 2)
    if abs(yeni - onceki) < 0.001:
        if varsayilana_don:
            return "Zaten normal hızda konuşuyorum."
        if yeni <= HIZ_ALT:
            return "Zaten en hızlı ayardayım, daha fazla hızlanamam."
        if yeni >= HIZ_UST:
            return "Zaten en yavaş ayardayım, daha fazla yavaşlayamam."
        return "Hızım zaten bu ayarda."

    CFG.tts.speed = yeni
    _kaydet()
    _degisikligi_duyur("tts.speed", yeni)

    if varsayilana_don:
        return "Normal hızıma döndüm."
    nasil = "hızlandım" if yeni < onceki else "yavaşladım"
    return f"Tamam, biraz {nasil}."


@skill(
    name="set_address",
    description=(
        "Riley'nin kullanıcıya nasıl hitap edeceğini değiştirir. "
        "'Bana Esad de', 'efendim deme' gibi isteklerde kullan."
    ),
    params={
        "hitap": {
            "type": "string",
            "description": "Yeni hitap, örn: Esad, patron, komutanım",
        }
    },
    required=["hitap"],
)
def set_address(hitap: str) -> str:
    temiz = hitap.strip()[:24]
    if not temiz:
        raise SkillError("Nasıl hitap edeyim?")

    CFG.persona.address = temiz
    _kaydet()
    _degisikligi_duyur("persona.address", temiz)
    return f"Anlaşıldı, bundan sonra size {temiz} diyeceğim."


@skill(
    name="set_permission_level",
    description=(
        "Riley'nin bu bilgisayarda ne yapabileceğini belirleyen yetki "
        "seviyesini değiştirir. 'Yetkilerini kıs', 'her şeyi yapabilirsin' "
        "gibi isteklerde kullan."
    ),
    params={
        "seviye": {
            "type": "string",
            "enum": ["narrow", "medium", "wide"],
            "description": (
                "narrow: sadece okuma ve uygulama açma. "
                "medium: dosya ve sistem işleri, yıkıcı olanlar onay ister. "
                "wide: her şey açık."
            ),
        }
    },
    required=["seviye"],
)
def set_permission_level(seviye: str) -> str:
    secim = seviye.strip().lower()
    if secim not in ("narrow", "medium", "wide"):
        raise SkillError("Seviye dar, orta ya da geniş olabilir.")

    onceki = CFG.perms.level
    if secim == onceki:
        return f"Yetki seviyem zaten {_seviye_adi(secim)}."

    CFG.perms.level = secim
    _kaydet()
    _degisikligi_duyur("perms.level", secim)
    return (
        f"Yetki seviyem {_seviye_adi(onceki)} seviyesinden "
        f"{_seviye_adi(secim)} seviyesine geçti."
    )


def _seviye_adi(seviye: str) -> str:
    return {"narrow": "dar", "medium": "orta", "wide": "geniş"}.get(seviye, seviye)


@skill(
    name="set_follow_up_window",
    description=(
        "Riley cevap verdikten sonra adını söylemeden kaç saniye konuşmaya "
        "devam edilebileceğini ayarlar. 'Beni daha uzun dinle', 'her seferinde "
        "adını söylemek istemiyorum' gibi isteklerde kullan."
    ),
    params={
        "saniye": {
            "type": "number",
            "description": "0 ile 30 arası; 0 kapatır",
        }
    },
    required=["saniye"],
)
def set_follow_up_window(saniye: float) -> str:
    yeni = round(max(0.0, min(30.0, float(saniye))), 1)
    CFG.wake.follow_up_s = yeni
    _kaydet()
    _degisikligi_duyur("wake.follow_up_s", yeni)

    if yeni == 0:
        return "Devam penceresi kapatıldı, her seferinde adımı söylemelisiniz."
    return f"Cevabımdan sonra {yeni:.0f} saniye adımı söylemeden konuşabilirsiniz."


@skill(
    name="get_settings",
    description=(
        "Riley'nin şu anki ayarlarını söyler: konuşma hızı, hitap, yetki "
        "seviyesi, uyandırma kipi ve kullanılan modeller."
    ),
    level="narrow",
)
def get_settings() -> str:
    hiz_tarifi = (
        "hızlı" if CFG.tts.speed < 0.75
        else "normal" if CFG.tts.speed <= 0.9
        else "yavaş"
    )
    uyandirma = {
        "name": f'adımı söyleyerek ("{CFG.persona.name}")',
        "wakeword": f"hazır model ({CFG.wake.model})",
        "off": "kapalı, yalnızca kısayol",
    }.get(CFG.wake.mode, CFG.wake.mode)

    return (
        f"Konuşma hızım {hiz_tarifi} ({CFG.tts.speed}). "
        f"Size {CFG.persona.address} diye hitap ediyorum. "
        f"Yetki seviyem {_seviye_adi(CFG.perms.level)}. "
        f"Uyandırma: {uyandirma}. "
        f"Devam penceresi {CFG.wake.follow_up_s:.0f} saniye. "
        f"Dil modeli {CFG.llm.model}, ses tanıma {CFG.stt.model_size}, "
        f"ses {CFG.tts.voice}."
    )
