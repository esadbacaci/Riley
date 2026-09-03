"""Dosya içinde arama becerisinin testleri."""
import asyncio

import pytest

from skills import arama
from skills.registry import run_skill


@pytest.fixture
def ornek_klasor(tmp_path):
    (tmp_path / "notlar.txt").write_text(
        "Alışveriş listesi\nSüt, ekmek\nFatura ödemesi yapılacak\n",
        encoding="utf-8",
    )
    (tmp_path / "rapor.md").write_text(
        "# Rapor\nBu belgede FATURA konusu geçiyor.\n", encoding="utf-8"
    )
    (tmp_path / "resim.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    alt = tmp_path / "node_modules"
    alt.mkdir()
    (alt / "paket.txt").write_text("fatura", encoding="utf-8")
    return tmp_path


def _ara(klasor, sorgu, limit=10):
    return asyncio.run(
        run_skill("search_in_files", {
            "query": sorgu, "folder": str(klasor), "limit": limit,
        })
    )


def test_icerikte_bulur(ornek_klasor):
    sonuc = _ara(ornek_klasor, "fatura")
    assert sonuc["ok"] is True
    assert "notlar.txt" in sonuc["result"]
    assert "rapor.md" in sonuc["result"]


def test_buyuk_kucuk_ve_turkce_harf_farketmez(ornek_klasor):
    """'FATURA' yazan belge 'fatura' aramasında da çıkmalı."""
    sonuc = _ara(ornek_klasor, "FaTuRa")
    assert "rapor.md" in sonuc["result"]


def test_eslesen_satir_gosterilir(ornek_klasor):
    sonuc = _ara(ornek_klasor, "süt")
    assert "Süt, ekmek" in sonuc["result"]
    assert "satır 2" in sonuc["result"]


def test_ikili_dosyalar_taranmaz(ornek_klasor):
    sonuc = _ara(ornek_klasor, "PNG")
    assert "resim.png" not in (sonuc.get("result") or "")


def test_gereksiz_klasorler_atlanir(ornek_klasor):
    """node_modules gibi klasörler taramayı boğmamalı."""
    sonuc = _ara(ornek_klasor, "fatura")
    assert "node_modules" not in sonuc["result"]


def test_bulunamayinca_anlasilir_cevap(ornek_klasor):
    sonuc = _ara(ornek_klasor, "boylebirseyyok")
    assert sonuc["ok"] is True
    assert "bulamadım" in sonuc["result"]


def test_cok_kisa_sorgu_reddedilir(ornek_klasor):
    sonuc = _ara(ornek_klasor, "a")
    assert sonuc["ok"] is False


def test_olmayan_klasor_hata_verir():
    sonuc = _ara("C:/boyle/bir/yer/yok", "fatura")
    assert sonuc["ok"] is False


def test_limit_uygulanir(tmp_path):
    for i in range(8):
        (tmp_path / f"dosya{i}.txt").write_text("anahtar kelime", encoding="utf-8")
    sonuc = _ara(tmp_path, "anahtar", limit=3)
    # Her sonuç bir dosya yolu satırıdır; başlık satırında .txt geçmez
    assert sonuc["result"].count(".txt") == 3


@pytest.mark.parametrize(
    "metin, beklenen",
    [("İSTANBUL", "istanbul"), ("Şişli", "sisli"), ("Ağrı", "agri")],
)
def test_sadelestirme(metin, beklenen):
    assert arama._sadelestir(metin) == beklenen
