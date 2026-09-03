"""Metin katmanlarının testleri: sayı okuma, marka düzeltme, gürültü süzgeci.

Bunlar saf mantık olduğu için model, mikrofon ya da ağ gerektirmez.
"""
import pytest

from audio.duzeltme import duzelt
from audio.normalize import sayi_oku, seslendirme_icin_hazirla
from audio.stt import is_noise


# --------------------------------------------------------------- sayılar --
@pytest.mark.parametrize(
    "sayi, beklenen",
    [
        (0, "sıfır"),
        (7, "yedi"),
        (13, "on üç"),
        (30, "otuz"),
        (100, "yüz"),
        (101, "yüz bir"),
        (200, "iki yüz"),
        (1000, "bin"),
        (1250, "bin iki yüz elli"),
        (2026, "iki bin yirmi altı"),
        (1000000, "bir milyon"),
        (-5, "eksi beş"),
    ],
)
def test_sayi_oku(sayi, beklenen):
    assert sayi_oku(sayi) == beklenen


@pytest.mark.parametrize(
    "metin, icermeli",
    [
        ("%44", "yüzde kırk dört"),
        ("Saat 19:30", "on dokuz otuz"),
        ("12.6 GB", "on iki virgül altı gigabayt"),
        ("17.0 GB", "on yedi gigabayt"),          # sıfır ondalık okunmaz
        ("45 derece", "kırk beş"),
    ],
)
def test_seslendirme_donusumu(metin, icermeli):
    assert icermeli in seslendirme_icin_hazirla(metin)


def test_dosya_yolu_kisaltilir():
    sonuc = seslendirme_icin_hazirla(
        r"Kaydedildi: C:\Users\Esad\Desktop\ekran.png"
    )
    assert "ekran.png" in sonuc
    assert "Users" not in sonuc


def test_url_sadelestirilir():
    sonuc = seslendirme_icin_hazirla("Kaynak: https://www.example.com/haber/123")
    assert "example.com" in sonuc
    assert "https" not in sonuc


def test_riley_rayli_okunur():
    assert "Rayli" in seslendirme_icin_hazirla("Ben Riley'im.")


# ------------------------------------------------------- marka düzeltme --
@pytest.mark.parametrize(
    "duyulan, beklenen_parca",
    [
        ("Gobi, Jehrome, aç", "Chrome"),
        ("Kroym'u aç", "Chrome"),
        ("Krumac mısın Google Krumac", "Chrome"),
        ("spotifay'ı aç", "Spotify"),
        ("not tefterini aç", "not defterini"),
        ("yutup'ta müzik ara", "YouTube"),
    ],
)
def test_marka_duzeltme(duyulan, beklenen_parca):
    assert beklenen_parca in duzelt(duyulan)


@pytest.mark.parametrize(
    "metin",
    [
        "Bugün hava nasıl olacak",
        "sesi yüzde otuza indir",
        "bana on dakika sonra çayı hatırlat",
        "bilgisayarın durumu nasıl",
    ],
)
def test_normal_cumleler_bozulmaz(metin):
    """Düzeltme katmanı sıradan Türkçeye dokunmamalı."""
    assert duzelt(metin) == metin


# ------------------------------------------------------- gürültü süzgeci --
@pytest.mark.parametrize(
    "metin",
    [
        "Altyazı M.K.",
        "İzlediğiniz için teşekkürler",
        "Merhaba, Türkler. Bir sonraki videoda görüşürüz.",
        "Merhaba. Merhaba. Merhaba. Merhaba.",
        "...",
        "",
    ],
)
def test_uydurma_metinler_elenir(metin):
    assert is_noise(metin) is True


@pytest.mark.parametrize(
    "metin",
    [
        "sesi yüzde otuz yap",
        "not defterini aç",
        "İstanbul hava durumu",
        "ekran görüntüsü al",
    ],
)
def test_gercek_komutlar_gecer(metin):
    assert is_noise(metin) is False
