"""Zaman, hatırlatıcı ve kalıcı not becerileri."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import uuid

from config import DATA_DIR
from core.bus import bus
from skills.registry import SkillError, skill

MEMORY_FILE = DATA_DIR / "memory.json"

_GUNLER = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
]
_AYLAR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


@skill(
    name="get_datetime",
    description=(
        "Su anki tarih ve saati döndürür. Saat kac, bugün günlerden ne gibi "
        "sorularda kullan. Tarihi asla tahmin etme, her zaman bunu çağır."
    ),
    level="narrow",
)
def get_datetime() -> str:
    now = dt.datetime.now()
    return (
        f"{now.day} {_AYLAR[now.month - 1]} {now.year}, "
        f"{_GUNLER[now.weekday()]}, saat {now.hour:02d}:{now.minute:02d}."
    )


# --- Hatırlatıcı / zamanlayıcı -------------------------------------------

_TIMERS: dict[str, asyncio.Task] = {}


def _parse_duration(text: str) -> int:
    """'5 dakika', '1 saat 30 dk', '90 saniye' -> saniye."""
    raw = str(text).lower().replace(",", ".")
    total = 0
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:saat|sa\b|h\b|hour)", 3600),
        (r"(\d+(?:\.\d+)?)\s*(?:dakika|dakka|dk\b|min|m\b)", 60),
        (r"(\d+(?:\.\d+)?)\s*(?:saniye|sn\b|sec|s\b)", 1),
    ]
    for pattern, factor in patterns:
        for value in re.findall(pattern, raw):
            total += float(value) * factor

    if total == 0:
        bare = re.findall(r"\d+(?:\.\d+)?", raw)
        if bare:
            total = float(bare[0]) * 60  # birim yoksa dakika varsay
    if total <= 0:
        raise SkillError("Süreyi anlayamadım. Örnek: 5 dakika, 1 saat 30 dakika.")
    return int(total)


async def _fire(timer_id: str, seconds: int, label: str) -> None:
    try:
        await asyncio.sleep(seconds)
        await bus.emit("timer.fired", id=timer_id, label=label)
        await bus.emit("assistant.say", text=f"Hatırlatma zamanı: {label}")
    except asyncio.CancelledError:
        pass
    finally:
        _TIMERS.pop(timer_id, None)


@skill(
    name="set_timer",
    description=(
        "Belirtilen süre sonra sesli hatırlatma kurar. Kullanıcı bana su kadar "
        "sonra sunu hatırlat dediğinde kullan."
    ),
    params={
        "duration": {"type": "string", "description": "Süre, orn: 10 dakika, 1 saat"},
        "label": {"type": "string", "description": "Hatırlatılacak şey"},
    },
    required=["duration"],
)
def set_timer(duration: str, label: str = "zamanlayıcı") -> str:
    seconds = _parse_duration(duration)
    timer_id = uuid.uuid4().hex[:8]

    loop = bus.loop
    if loop is None:
        raise SkillError("Zamanlayıcı su an kurulamıyor.")
    task = asyncio.run_coroutine_threadsafe(
        _spawn(timer_id, seconds, label), loop
    ).result(timeout=5)
    _TIMERS[timer_id] = task

    when = dt.datetime.now() + dt.timedelta(seconds=seconds)
    return f"Tamam, {when.hour:02d}:{when.minute:02d} için kuruldu: {label} (kod {timer_id})"


async def _spawn(timer_id: str, seconds: int, label: str) -> asyncio.Task:
    return asyncio.create_task(_fire(timer_id, seconds, label))


@skill(
    name="list_timers",
    description="Kurulmuş aktif hatırlatıcıları listeler.",
    level="narrow",
)
def list_timers() -> str:
    if not _TIMERS:
        return "Aktif hatırlatıcı yok."
    return "Aktif hatırlatıcılar: " + ", ".join(_TIMERS.keys())


@skill(
    name="cancel_timer",
    description="Bir hatırlatıcıyı iptal eder. Kod verilmezse hepsini iptal eder.",
    params={"timer_id": {"type": "string", "description": "Iptal edilecek hatırlatıcı kodu"}},
)
def cancel_timer(timer_id: str = "") -> str:
    if not timer_id:
        count = len(_TIMERS)
        for task in list(_TIMERS.values()):
            task.cancel()
        _TIMERS.clear()
        return f"{count} hatırlatıcı iptal edildi."

    task = _TIMERS.pop(timer_id, None)
    if task is None:
        raise SkillError(f"{timer_id} kodlu hatırlatıcı yok.")
    task.cancel()
    return f"{timer_id} iptal edildi."


# --- Kalıcı hafıza -------------------------------------------------------


def _load_memory() -> list[dict]:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_memory(items: list[dict]) -> None:
    MEMORY_FILE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@skill(
    name="remember",
    description=(
        "Kullanıcı hakkında kalıcı bir bilgi kaydeder; sonraki oturumlarda da "
        "hatırlanır. Kullanıcı bunu unutma, sunu aklında tut dediğinde kullan."
    ),
    params={"fact": {"type": "string", "description": "Hatırlanacak bilgi"}},
    required=["fact"],
)
def remember(fact: str) -> str:
    items = _load_memory()
    items.append({"fact": fact.strip(), "at": dt.datetime.now().isoformat(timespec="seconds")})
    _save_memory(items[-200:])
    return f"Aklımda tuttum: {fact}"


@skill(
    name="recall",
    description=(
        "Daha önce kaydedilmiş bilgileri getirir. Kullanıcı geçmişte söylediği "
        "bir şeyi sorduğunda kullan."
    ),
    params={"query": {"type": "string", "description": "Aranacak kelime, boş ise hepsi"}},
    level="narrow",
)
def recall(query: str = "") -> str:
    items = _load_memory()
    if query:
        needle = query.lower()
        items = [i for i in items if needle in i["fact"].lower()]
    if not items:
        return "Bu konuda kayıtlı bir şey yok."
    return "Hatırladıklarım:\n" + "\n".join(f"- {i['fact']}" for i in items[-25:])


@skill(
    name="forget",
    description="Kayıtlı bir bilgiyi siler.",
    params={"query": {"type": "string", "description": "Silinecek kaydın içerdiği kelime"}},
    required=["query"],
)
def forget(query: str) -> str:
    items = _load_memory()
    needle = query.lower()
    kept = [i for i in items if needle not in i["fact"].lower()]
    removed = len(items) - len(kept)
    if removed == 0:
        raise SkillError(f"{query} ile eşleşen kayıt yok.")
    _save_memory(kept)
    return f"{removed} kayıt silindi."
