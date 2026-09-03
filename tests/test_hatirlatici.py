"""Hatırlatıcıların süre çözümlemesi ve yeniden başlatmayı aşması."""
import asyncio
import datetime as dt
import json

import pytest

from skills import misc
from skills.registry import SkillError


# ------------------------------------------------------ süre çözümlemesi --
@pytest.mark.parametrize(
    "metin, saniye",
    [
        ("5 dakika", 300),
        ("1 saat", 3600),
        ("1 saat 30 dakika", 5400),
        ("90 saniye", 90),
        ("2 dk", 120),
        ("10", 600),          # birim yoksa dakika varsayılır
    ],
)
def test_sure_cozumleme(metin, saniye):
    assert misc._parse_duration(metin) == saniye


@pytest.mark.parametrize("metin", ["biraz sonra", "", "yakında"])
def test_anlasilmayan_sure_hata_verir(metin):
    with pytest.raises(SkillError):
        misc._parse_duration(metin)


# ------------------------------------------------------------ kalıcılık --
@pytest.fixture
def gecici_kayit(tmp_path, monkeypatch):
    """Hatırlatıcı dosyasını geçici bir dizine yönlendirir."""
    dosya = tmp_path / "timers.json"
    monkeypatch.setattr(misc, "TIMERS_FILE", dosya)
    monkeypatch.setattr(misc, "_KAYITLAR", {})
    monkeypatch.setattr(misc, "_TIMERS", {})
    return dosya


def test_kayit_diske_yazilir(gecici_kayit):
    misc._KAYITLAR["abc123"] = {
        "label": "çay",
        "fire_at": (dt.datetime.now() + dt.timedelta(minutes=10)).isoformat(),
        "created_at": dt.datetime.now().isoformat(),
    }
    misc._kayitlari_yaz()

    assert gecici_kayit.exists()
    okunan = json.loads(gecici_kayit.read_text(encoding="utf-8"))
    assert okunan["abc123"]["label"] == "çay"


def test_gelecekteki_hatirlatici_geri_yuklenir(gecici_kayit, monkeypatch):
    """Riley kapanıp açılınca bekleyen hatırlatma korunmalı."""
    kurulan = []
    monkeypatch.setattr(misc.bus, "log", _sahte_log)

    async def sahte_spawn(timer_id, seconds, label, gecikmis=False):
        kurulan.append((timer_id, seconds, label, gecikmis))
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(misc, "_spawn", sahte_spawn)

    gecici_kayit.write_text(json.dumps({
        "t1": {
            "label": "toplantı",
            "fire_at": (dt.datetime.now() + dt.timedelta(minutes=30)).isoformat(),
            "created_at": dt.datetime.now().isoformat(),
        }
    }), encoding="utf-8")

    sayi = asyncio.run(misc.hatirlaticilari_geri_yukle())

    assert sayi == 1
    assert kurulan[0][2] == "toplantı"
    assert kurulan[0][3] is False              # gecikmiş değil
    assert 1500 < kurulan[0][1] <= 1800        # ~30 dakika kalmış


def test_zamani_gecmis_hatirlatici_hemen_bildirilir(gecici_kayit, monkeypatch):
    kurulan = []
    monkeypatch.setattr(misc.bus, "log", _sahte_log)

    async def sahte_spawn(timer_id, seconds, label, gecikmis=False):
        kurulan.append((timer_id, seconds, label, gecikmis))
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(misc, "_spawn", sahte_spawn)

    gecici_kayit.write_text(json.dumps({
        "t2": {
            "label": "ilaç",
            "fire_at": (dt.datetime.now() - dt.timedelta(minutes=20)).isoformat(),
            "created_at": dt.datetime.now().isoformat(),
        }
    }), encoding="utf-8")

    asyncio.run(misc.hatirlaticilari_geri_yukle())

    assert kurulan[0][1] == 0                  # beklemeden çalsın
    assert kurulan[0][3] is True               # gecikmiş olarak işaretli


def test_cok_eski_kayit_dusurulur(gecici_kayit, monkeypatch):
    """Bir gün önceki hatırlatma açılışta ortalığı meşgul etmemeli."""
    kurulan = []
    monkeypatch.setattr(misc.bus, "log", _sahte_log)

    async def sahte_spawn(*a, **k):
        kurulan.append(a)
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(misc, "_spawn", sahte_spawn)

    gecici_kayit.write_text(json.dumps({
        "t3": {
            "label": "dünkü iş",
            "fire_at": (dt.datetime.now() - dt.timedelta(days=1)).isoformat(),
            "created_at": dt.datetime.now().isoformat(),
        }
    }), encoding="utf-8")

    sayi = asyncio.run(misc.hatirlaticilari_geri_yukle())

    assert sayi == 0
    assert kurulan == []
    assert json.loads(gecici_kayit.read_text(encoding="utf-8")) == {}


def test_listeleme_kalan_sureyi_gosterir(gecici_kayit):
    misc._KAYITLAR["t4"] = {
        "label": "çay",
        "fire_at": (dt.datetime.now() + dt.timedelta(minutes=15)).isoformat(),
        "created_at": dt.datetime.now().isoformat(),
    }
    sonuc = misc.list_timers()
    assert "çay" in sonuc
    assert "dakika sonra" in sonuc


async def _sahte_log(*a, **k):
    """bus.log yerine geçen, hiçbir şey yapmayan eşdeğer."""
    return None
