"""Araç kararlarının testleri.

Dil modeli bazen aracı çağırmak yerine çağıracağını anlatıyor
("set_volume aracını çağırıyorum"). Bu durumu yakalayan tespit ve
becerilerin kendi doğrulama mantığı burada sınanır.
"""
import pytest

from brain.agent import _arac_anonsu
from skills.registry import REGISTRY, needs_confirmation, run_skill, tool_schemas


# ------------------------------------------------- araç anonsu tespiti --
@pytest.mark.parametrize(
    "cevap",
    [
        "set_volume aracını çağırıyorum.",
        "System stats aracını çağırıyorum.",
        "system_stats çalıştırıyorum",
        "open_app kullanacağım",
        "take_screenshot aracını başlatıyorum",
    ],
)
def test_anons_yakalanir(cevap):
    assert _arac_anonsu(cevap) is True


@pytest.mark.parametrize(
    "cevap",
    [
        "Ses yüzde kırk oldu.",
        "İşlemci yüzde on ikide, bellek yarıdan biraz fazla dolu.",
        "Chrome açıldı.",
        "Ekran görüntüsü aldım ve kaydettim.",
        "Sesi ayarlamak için bir araç kullanacağım",   # araç adı geçmiyor
        "",
    ],
)
def test_normal_cevap_anons_sayilmaz(cevap):
    assert _arac_anonsu(cevap) is False


# ------------------------------------------------------ kayıt defteri --
def test_butun_beceriler_sema_uretir():
    semalar = tool_schemas()
    assert len(semalar) >= 30
    for sema in semalar:
        assert sema["type"] == "function"
        fn = sema["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_yikici_isler_onay_ister():
    for ad in ("delete_path", "shutdown"):
        assert needs_confirmation(ad) is True


def test_gunluk_isler_onay_istemez():
    for ad in ("open_app", "system_stats", "get_datetime", "take_screenshot"):
        assert needs_confirmation(ad) is False


def test_bilinmeyen_beceri_hata_dondurur():
    import asyncio

    sonuc = asyncio.run(run_skill("boyle_bir_sey_yok", {}))
    assert sonuc["ok"] is False
    assert "beceri" in sonuc["error"].lower() or "yok" in sonuc["error"].lower()


def test_fazladan_parametre_temizlenir():
    """Model uydurma parametre gönderse bile beceri çalışmalı."""
    import asyncio

    sonuc = asyncio.run(run_skill("get_datetime", {"uydurma": 1, "app": "x"}))
    assert sonuc["ok"] is True


def test_eksik_zorunlu_parametre_yakalanir():
    import asyncio

    sonuc = asyncio.run(run_skill("open_app", {}))
    assert sonuc["ok"] is False
    assert "app" in sonuc["error"]


def test_beceri_adlari_ingilizce_ve_alt_cizgili():
    """Araç anonsu tespiti buna dayanıyor: adlar Türkçe metinde geçmez."""
    for ad in REGISTRY:
        assert ad.islower()
        assert all(c.isalnum() or c == "_" for c in ad)
