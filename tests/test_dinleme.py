"""Dinleme mantığının testleri: adıyla uyandırma ve söz kesme.

Gerçek mikrofon açılmaz; ses çerçeveleri sentetik olarak üretilir.
"""
import numpy as np
import pytest

from audio.mic import FRAME_LEN, Listener, ad_kalibi
from config import CFG


# ---------------------------------------------------- adıyla uyandırma --
@pytest.mark.parametrize(
    "soylenen, beklenen_komut",
    [
        ("Riley, sesi kıs", "sesi kıs"),
        ("Rayli saat kaç", "saat kaç"),
        ("Hey Riley not defterini aç", "not defterini aç"),
        ("Riley'e sor bakalım", "sor bakalım"),
        ("Asistan ekran görüntüsü al", "ekran görüntüsü al"),
    ],
)
def test_ad_ayiklanir(soylenen, beklenen_komut):
    eslesme = ad_kalibi().match(soylenen.lower())
    assert eslesme is not None
    assert soylenen[eslesme.end():].strip(" ,.!?:;") == beklenen_komut


@pytest.mark.parametrize(
    "soylenen",
    [
        "raylı sistem nedir",        # gerçek Türkçe tabir, uyandırmamalı
        "rayları değiştir",
        "asistanım nerede",          # kelime sınırı
        "Bugün hava nasıl",
    ],
)
def test_yanlis_uyanma_olmaz(soylenen):
    assert ad_kalibi().match(soylenen.lower()) is None


# ------------------------------------------------------------ söz kesme --
class SahteHoparlor:
    """Konuşuyormuş gibi davranan, durdurulduğunu kaydeden sahte hoparlör."""

    def __init__(self):
        self.durduruldu = False
        self.is_speaking = True

    def stop(self):
        self.durduruldu = True
        self.is_speaking = False


def _cerceve(genlik: float) -> np.ndarray:
    """Verilen RMS genliğinde (0-1) bir ses çerçevesi üretir."""
    return np.full(FRAME_LEN, int(genlik * 32767), dtype=np.int16)


@pytest.fixture
def dinleyici(monkeypatch):
    """Ses aygıtı açmadan bir Listener kurar."""
    yakalanan = []
    monkeypatch.setattr(
        "audio.mic.bus.emit_threadsafe",
        lambda tur, **k: yakalanan.append((tur, k)),
    )
    monkeypatch.setattr("audio.mic.machine.set_threadsafe", lambda *a, **k: None)

    lst = Listener(on_utterance=lambda t: None)
    lst.olaylar = yakalanan
    return lst


def test_kendi_sesi_sozunu_kesmez(dinleyici):
    """Riley'nin kendi sesi mikrofona geri gelse bile susmamalı."""
    hoparlor = SahteHoparlor()
    eko = 0.05                       # sabit yankı seviyesi

    for _ in range(120):             # ~3.6 saniyelik konuşma
        dinleyici._konusurken(_cerceve(eko), hoparlor)

    assert hoparlor.durduruldu is False


def test_kullanici_araya_girince_susar(dinleyici):
    """Yankı tabanının belirgin üstündeki ses konuşmayı kesmeli."""
    hoparlor = SahteHoparlor()
    eko = 0.05

    # Önce yankı tabanı ölçülsün
    for _ in range(30):
        dinleyici._konusurken(_cerceve(eko), hoparlor)
    assert hoparlor.durduruldu is False

    # Sonra kullanıcı konuşsun: taban üç kattan fazla aşılıyor
    for _ in range(CFG.wake.barge_in_cerceve + 2):
        dinleyici._konusurken(_cerceve(eko * 5), hoparlor)

    assert hoparlor.durduruldu is True
    assert any(t == "barge.in" for t, _ in dinleyici.olaylar)


def test_tek_gurultu_patlamasi_kesmez(dinleyici):
    """Kapı çarpması gibi tek çerçevelik sesler sözü kesmemeli."""
    hoparlor = SahteHoparlor()
    eko = 0.05

    for _ in range(30):
        dinleyici._konusurken(_cerceve(eko), hoparlor)

    # Ardışık eşiğin altında kalan kısa bir patlama
    for _ in range(CFG.wake.barge_in_cerceve - 2):
        dinleyici._konusurken(_cerceve(eko * 6), hoparlor)
    dinleyici._konusurken(_cerceve(eko), hoparlor)     # sessizliğe dönüş

    assert hoparlor.durduruldu is False


def test_kulaklikta_da_calisir(dinleyici):
    """Kulaklık takılıyken yankı yok; mutlak alt sınır devreye girmeli."""
    hoparlor = SahteHoparlor()

    for _ in range(30):
        dinleyici._konusurken(_cerceve(0.0005), hoparlor)   # neredeyse sessiz

    for _ in range(CFG.wake.barge_in_cerceve + 2):
        dinleyici._konusurken(_cerceve(0.15), hoparlor)     # normal konuşma

    assert hoparlor.durduruldu is True
