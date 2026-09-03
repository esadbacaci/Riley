"""Dinleme mantığının testleri: adıyla uyandırma ve söz kesme.

Gerçek mikrofon açılmaz; ses çerçeveleri sentetik olarak üretilir.
"""
import numpy as np
import pytest

from audio.mic import FRAME_LEN, FRAME_MS, Listener, ad_kalibi
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


class SahteSaat:
    """Çerçeve başına gerçek zaman geçmiş gibi davranan sayaç.

    Yankı tabanı ölçümü süreye bağlı olduğu için testin de zamanı
    ilerletmesi gerekiyor.
    """

    def __init__(self):
        self.simdi = 1_000_000.0

    def __call__(self) -> float:
        return self.simdi

    def ilerlet(self, ms: float) -> None:
        self.simdi += ms / 1000


@pytest.fixture
def dinleyici(monkeypatch):
    """Ses aygıtı açmadan, söz kesme açıkken bir Listener kurar."""
    yakalanan = []
    monkeypatch.setattr(
        "audio.mic.bus.emit_threadsafe",
        lambda tur, **k: yakalanan.append((tur, k)),
    )
    monkeypatch.setattr("audio.mic.machine.set_threadsafe", lambda *a, **k: None)
    monkeypatch.setattr(CFG.wake, "barge_in", True)     # varsayılanı kapalı

    saat = SahteSaat()
    monkeypatch.setattr("audio.mic.time.time", saat)

    lst = Listener(on_utterance=lambda t: None)
    lst.olaylar = yakalanan
    lst.saat = saat
    return lst


def _konustur(dinleyici, hoparlor, genlik: float, cerceve_sayisi: int) -> None:
    """Belirtilen sayıda çerçeveyi zamanı da ilerleterek besler."""
    for _ in range(cerceve_sayisi):
        dinleyici._konusurken(_cerceve(genlik), hoparlor)
        dinleyici.saat.ilerlet(FRAME_MS)


def test_kendi_sesi_sozunu_kesmez(dinleyici):
    """Riley'nin kendi sesi mikrofona geri gelse bile susmamalı.

    Bu, gerçekte yaşanan hatanın testi: yankı tabanı yanlış ölçülünce
    Riley kendi sesiyle tetikleniyor ve kendini kesiyordu.
    """
    hoparlor = SahteHoparlor()
    _konustur(dinleyici, hoparlor, 0.05, 200)      # ~6 saniyelik konuşma
    assert hoparlor.durduruldu is False


def test_sessizlikle_baslayan_konusma_kendini_kesmez(dinleyici):
    """Piper sessizlikle başlar; taban buna göre ölçülmemeli.

    Eski kod tabanı ilk yarım saniyeden alıyordu, o da sessizlik olduğu
    için sıfıra yakın çıkıyor ve Riley konuşmaya başlar başlamaz kendini
    kesiyordu.
    """
    hoparlor = SahteHoparlor()
    _konustur(dinleyici, hoparlor, 0.0005, 20)     # başlangıçtaki sessizlik
    _konustur(dinleyici, hoparlor, 0.06, 200)      # sonra normal konuşma
    assert hoparlor.durduruldu is False


def test_kullanici_araya_girince_susar(dinleyici):
    """Yankı tabanının belirgin üstündeki ses konuşmayı kesmeli."""
    hoparlor = SahteHoparlor()
    eko = 0.05

    # Önce yankı tabanı ölçülsün (ölçüm süresi dolana kadar)
    _konustur(dinleyici, hoparlor, eko, 60)
    assert hoparlor.durduruldu is False

    # Sonra kullanıcı mikrofona yakın konuşsun
    _konustur(dinleyici, hoparlor, eko * 6, CFG.wake.barge_in_cerceve + 2)

    assert hoparlor.durduruldu is True
    assert any(t == "barge.in" for t, _ in dinleyici.olaylar)


def test_tek_gurultu_patlamasi_kesmez(dinleyici):
    """Kapı çarpması gibi kısa sesler sözü kesmemeli."""
    hoparlor = SahteHoparlor()
    eko = 0.05

    _konustur(dinleyici, hoparlor, eko, 60)

    # Ardışık eşiğin altında kalan kısa bir patlama
    _konustur(dinleyici, hoparlor, eko * 8, CFG.wake.barge_in_cerceve - 2)
    _konustur(dinleyici, hoparlor, eko, 1)     # sessizliğe dönüş

    assert hoparlor.durduruldu is False


def test_kulaklikta_da_calisir(dinleyici):
    """Kulaklık takılıyken yankı yok; mutlak alt sınır devreye girmeli."""
    hoparlor = SahteHoparlor()

    _konustur(dinleyici, hoparlor, 0.0005, 60)              # neredeyse sessiz
    _konustur(dinleyici, hoparlor, 0.15,
              CFG.wake.barge_in_cerceve + 2)                # normal konuşma

    assert hoparlor.durduruldu is True
