"""Ajan mantığı: onay sözcükleri ve uzun sohbetlerin özetlenmesi."""
import asyncio

import pytest

from brain import agent as ajan_modulu
from brain.agent import Agent, is_affirmative


# ------------------------------------------------------- onay sözcükleri --
@pytest.mark.parametrize(
    "soz, beklenen",
    [
        ("evet", True), ("Tamam", True), ("olur", True), ("onaylıyorum", True),
        ("tabii ki", True), ("peki", True),
        ("hayır", False), ("iptal", False), ("vazgeç", False), ("olmaz", False),
        ("boşver", False), ("yapma", False),
        ("belki", None), ("ne dedin", None), ("", None),
    ],
)
def test_onay_cozumleme(soz, beklenen):
    assert is_affirmative(soz) is beklenen


# ------------------------------------------------------------ özetleme --
def _sahte_akis(ozet_metni: str):
    """llm.chat_stream yerine geçen, sabit özet döndüren eşdeğer."""

    async def akis(messages, tools=None, temperature=None):
        yield {"kind": "done", "content": ozet_metni, "stats": {}}

    return akis


@pytest.fixture
def sessiz_bus(monkeypatch):
    async def hicbir_sey(*a, **k):
        return None

    monkeypatch.setattr(ajan_modulu.bus, "log", hicbir_sey)
    monkeypatch.setattr(ajan_modulu.bus, "emit", hicbir_sey)


def test_kisa_sohbet_kirpilmaz(sessiz_bus):
    a = Agent(max_history=10, tutulacak=4)
    for i in range(3):
        a.history.append({"role": "user", "content": f"soru {i}"})
        a.history.append({"role": "assistant", "content": f"cevap {i}"})

    asyncio.run(a._gecmisi_kirp())

    assert len(a.history) == 6
    assert a.ozet == ""


def test_uzun_sohbet_ozetlenir(sessiz_bus, monkeypatch):
    monkeypatch.setattr(
        ajan_modulu.llm, "chat_stream",
        _sahte_akis("Kullanıcının adı Esad, akşamları kod yazıyor."),
    )

    a = Agent(max_history=10, tutulacak=4)
    for i in range(10):
        a.history.append({"role": "user", "content": f"soru {i}"})
        a.history.append({"role": "assistant", "content": f"cevap {i}"})

    asyncio.run(a._gecmisi_kirp())

    assert len(a.history) == 4                      # sadece son mesajlar kaldı
    assert "Esad" in a.ozet                         # eskiler özete geçti
    assert a.history[-1]["content"] == "cevap 9"    # en yenisi korundu


def test_ozet_bir_sonraki_ozetlemeye_tasinir(sessiz_bus, monkeypatch):
    """İkinci kırpımda önceki özet de dil modeline verilmeli."""
    gorulen_istemler = []

    def akis_yakalayan(messages, tools=None, temperature=None):
        gorulen_istemler.append(messages[0]["content"])

        async def akis():
            yield {"kind": "done", "content": "yeni özet", "stats": {}}

        return akis()

    monkeypatch.setattr(ajan_modulu.llm, "chat_stream", akis_yakalayan)

    a = Agent(max_history=6, tutulacak=2)
    a.ozet = "önceki özet burada"
    for i in range(6):
        a.history.append({"role": "user", "content": f"soru {i}"})
        a.history.append({"role": "assistant", "content": f"cevap {i}"})

    asyncio.run(a._gecmisi_kirp())

    assert "önceki özet burada" in gorulen_istemler[0]
    assert a.ozet == "yeni özet"


def test_ozetleme_hatasi_sohbeti_kilitlemez(sessiz_bus, monkeypatch):
    """Dil modeli cevap veremezse geçmiş yine de kırpılmalı."""

    def patlayan(messages, tools=None, temperature=None):
        raise RuntimeError("model kapalı")

    monkeypatch.setattr(ajan_modulu.llm, "chat_stream", patlayan)

    a = Agent(max_history=6, tutulacak=2)
    for i in range(6):
        a.history.append({"role": "user", "content": f"soru {i}"})
        a.history.append({"role": "assistant", "content": f"cevap {i}"})

    asyncio.run(a._gecmisi_kirp())

    assert len(a.history) == 2
    assert a.ozet == ""


def test_sifirlama_ozeti_de_temizler():
    a = Agent()
    a.history.append({"role": "user", "content": "bir şey"})
    a.ozet = "bir özet"

    a.reset()

    assert a.history == []
    assert a.ozet == ""
