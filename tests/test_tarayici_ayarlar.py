"""Tarayıcı kontrolü ve sesle ayar değiştirme testleri.

Gerçek tarayıcı açılmaz; pencere katmanı taklit edilir.
"""
import asyncio

import pytest

from config import CFG
from skills import ayarlar, tarayici
from skills.registry import run_skill


# ------------------------------------------------------------- tarayıcı --
def test_butun_eylemlerin_kisayolu_ve_mesaji_var():
    for ad, (kisayol, mesaj) in tarayici.EYLEMLER.items():
        assert isinstance(kisayol, tuple) and kisayol, f"{ad} kısayolsuz"
        assert mesaj.endswith("."), f"{ad} mesajı cümle değil"


def test_sema_enum_eylemlerle_ayni():
    from skills.registry import REGISTRY

    sema = REGISTRY["browser_action"].schema()
    secenekler = set(sema["function"]["parameters"]["properties"]["eylem"]["enum"])
    assert secenekler == set(tarayici.EYLEMLER)


def test_bilinmeyen_eylem_reddedilir():
    sonuc = asyncio.run(run_skill("browser_action", {"eylem": "olmayan"}))
    assert sonuc["ok"] is False
    assert "bilinmeyen" in sonuc["error"].lower()


def test_tarayici_yokken_anlasilir_hata(monkeypatch):
    monkeypatch.setattr(tarayici, "_on_pencere", lambda: None)
    monkeypatch.setattr(tarayici, "ekran_kilitli", lambda: False)

    class SahteGw:
        @staticmethod
        def getAllWindows():
            return []

    monkeypatch.setitem(__import__("sys").modules, "pygetwindow", SahteGw)
    sonuc = asyncio.run(run_skill("browser_action", {"eylem": "yeni_sekme"}))
    assert sonuc["ok"] is False
    assert "tarayıcı bulamadım" in sonuc["error"]


def test_kilitli_ekranda_kilit_soylenir(monkeypatch):
    monkeypatch.setattr(tarayici, "_on_pencere", lambda: None)
    monkeypatch.setattr(tarayici, "ekran_kilitli", lambda: True)

    sonuc = asyncio.run(run_skill("browser_action", {"eylem": "yeni_sekme"}))
    assert sonuc["ok"] is False
    assert "kilitli" in sonuc["error"].lower()


def test_bos_adres_reddedilir():
    sonuc = asyncio.run(run_skill("browser_open_tab", {"url": "   "}))
    assert sonuc["ok"] is False


# -------------------------------------------------------------- ayarlar --
@pytest.fixture
def ayar_yedegi(monkeypatch):
    """Ayarları teste özel yapar; disk ve olay veri yolu susturulur."""
    monkeypatch.setattr(ayarlar, "_kaydet", lambda: None)
    monkeypatch.setattr(ayarlar, "_degisikligi_duyur", lambda *a: None)

    onceki = (CFG.tts.speed, CFG.persona.address, CFG.perms.level,
              CFG.wake.follow_up_s)
    yield
    (CFG.tts.speed, CFG.persona.address, CFG.perms.level,
     CFG.wake.follow_up_s) = onceki


def test_hizlandirma_degeri_dusurur(ayar_yedegi):
    CFG.tts.speed = 0.90
    asyncio.run(run_skill("set_speech_speed", {"yon": "hizlandir"}))
    assert CFG.tts.speed < 0.90       # küçük değer = hızlı konuşma


def test_yavaslatma_degeri_yukseltir(ayar_yedegi):
    CFG.tts.speed = 0.80
    asyncio.run(run_skill("set_speech_speed", {"yon": "yavaslat"}))
    assert CFG.tts.speed > 0.80


def test_hiz_sinirlari_asilmaz(ayar_yedegi):
    CFG.tts.speed = 0.80
    asyncio.run(run_skill("set_speech_speed", {"deger": 5.0}))
    assert CFG.tts.speed == ayarlar.HIZ_UST

    asyncio.run(run_skill("set_speech_speed", {"deger": 0.1}))
    assert CFG.tts.speed == ayarlar.HIZ_ALT


def test_sinirdayken_anlasilir_cevap(ayar_yedegi):
    CFG.tts.speed = ayarlar.HIZ_ALT
    sonuc = asyncio.run(run_skill("set_speech_speed", {"yon": "hizlandir"}))
    assert "en hızlı" in sonuc["result"]


def test_normal_hiza_donme(ayar_yedegi):
    CFG.tts.speed = 1.2
    sonuc = asyncio.run(run_skill("set_speech_speed", {"yon": "normal"}))
    assert CFG.tts.speed == 0.80
    assert "normal" in sonuc["result"].lower()


def test_yonsuz_cagri_hata_verir(ayar_yedegi):
    sonuc = asyncio.run(run_skill("set_speech_speed", {}))
    assert sonuc["ok"] is False


def test_hitap_degisir(ayar_yedegi):
    sonuc = asyncio.run(run_skill("set_address", {"hitap": "patron"}))
    assert CFG.persona.address == "patron"
    assert "patron" in sonuc["result"]


def test_bos_hitap_reddedilir(ayar_yedegi):
    sonuc = asyncio.run(run_skill("set_address", {"hitap": "   "}))
    assert sonuc["ok"] is False


def test_yetki_seviyesi_degisir(ayar_yedegi):
    CFG.perms.level = "medium"
    sonuc = asyncio.run(run_skill("set_permission_level", {"seviye": "narrow"}))
    assert CFG.perms.level == "narrow"
    assert "dar" in sonuc["result"]


def test_ayni_yetki_seviyesi_tekrar_ayarlanmaz(ayar_yedegi):
    CFG.perms.level = "medium"
    sonuc = asyncio.run(run_skill("set_permission_level", {"seviye": "medium"}))
    assert "zaten" in sonuc["result"]


def test_devam_penceresi_sinirlanir(ayar_yedegi):
    asyncio.run(run_skill("set_follow_up_window", {"saniye": 999}))
    assert CFG.wake.follow_up_s == 30.0

    sonuc = asyncio.run(run_skill("set_follow_up_window", {"saniye": 0}))
    assert CFG.wake.follow_up_s == 0.0
    assert "kapatıldı" in sonuc["result"]


def test_ayarlari_okuma_hepsini_icerir(ayar_yedegi):
    sonuc = asyncio.run(run_skill("get_settings", {}))
    metin = sonuc["result"]
    for beklenen in ("Konuşma hızım", "hitap", "Yetki seviyem", "Uyandırma"):
        assert beklenen in metin
