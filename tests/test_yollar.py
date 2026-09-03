"""Kullanıcının söylediği yolun gerçek bir dizine çevrilmesi.

Konuşurken kimse tam yol söylemez: "masaüstünde", "Belgeler'de",
"Riley klasöründe". Bu katman onları çözer.
"""
from pathlib import Path

import pytest

from skills.files import _expand


@pytest.mark.parametrize(
    "soylenen, beklenen",
    [
        ("masaustu", Path.home() / "Desktop"),
        ("masaüstü", Path.home() / "Desktop"),
        ("Masaüstü", Path.home() / "Desktop"),
        ("belgeler", Path.home() / "Documents"),
        ("Belgelerim", Path.home() / "Documents"),
        ("indirilenler", Path.home() / "Downloads"),
        ("resimler", Path.home() / "Pictures"),
    ],
)
def test_turkce_klasor_adlari(soylenen, beklenen):
    assert _expand(soylenen) == beklenen


def test_karma_yol():
    """"masaustu/notlar.txt" gibi karma yollar da çözülmeli."""
    assert _expand("masaustu/notlar.txt") == Path.home() / "Desktop" / "notlar.txt"


def test_mutlak_yol_korunur():
    assert _expand("C:/Windows") == Path("C:/Windows")


def test_ciplak_ad_olagan_yerlerde_aranir(tmp_path, monkeypatch):
    """Kullanıcı sadece klasör adını söylerse Masaüstü ve Belgeler'e bakılmalı."""
    sahte_masaustu = tmp_path / "Desktop"
    sahte_masaustu.mkdir()
    (sahte_masaustu / "ProjeKlasoru").mkdir()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert _expand("ProjeKlasoru") == sahte_masaustu / "ProjeKlasoru"


def test_bulunamayan_ad_oldugu_gibi_doner():
    sonuc = _expand("boyle_bir_klasor_yok_12345")
    assert sonuc.name == "boyle_bir_klasor_yok_12345"
    assert not sonuc.exists()


def test_tirnaklar_temizlenir():
    assert _expand('"masaustu"') == Path.home() / "Desktop"
