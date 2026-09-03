"""Asenkron olay veri yolu.

Ses is parçacıkları (thread) ile FastAPI'nin event loop'u arasındaki tek köprü.
Thread'lerden `bus.emit_threadsafe(...)`, async koddan `await bus.emit(...)`.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable

Handler = Callable[[dict], Awaitable[None]]

# Konsola da yazılacak olaylar. Arayüz kapalıyken sorunları görebilmek için.
_CONSOLE_EVENTS = {
    "log", "boot.step", "boot.done", "state", "wake", "user.said",
    "reply.done", "tool.start", "tool.end", "confirm.request", "timer.fired",
}
_ETIKET = {
    "log": "kayıt", "boot.step": "açılış", "boot.done": "hazır", "state": "durum",
    "wake": "uyandı", "user.said": "sen", "reply.done": "riley",
    "tool.start": "araç>", "tool.end": "araç<", "confirm.request": "onay",
    "timer.fired": "alarm",
}


def _console(event: dict) -> None:
    """Olayı okunabilir tek satır hâlinde stdout'a yazar."""
    kind = event.get("type", "")
    if kind not in _CONSOLE_EVENTS:
        return
    stamp = time.strftime("%H:%M:%S")
    etiket = _ETIKET.get(kind, kind)
    detay = (
        event.get("text")
        or event.get("detail")
        or event.get("value")
        or event.get("name")
        or event.get("question")
        or ""
    )
    if kind == "boot.step":
        detay = f"{event.get('step')} {event.get('status')} {event.get('detail', '')}"
    elif kind in ("tool.start", "tool.end"):
        extra = event.get("args") or event.get("result") or ""
        detay = f"{event.get('name')} {extra}"
    try:
        print(f"[{stamp}] {etiket:<7} {str(detay)[:220]}", flush=True)
    except UnicodeEncodeError:  # konsol kod sayfası dar olabilir
        print(f"[{stamp}] {etiket:<7} {str(detay)[:220].encode('ascii', 'replace').decode()}",
              flush=True)


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._handlers: dict[str, list[Handler]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._history: deque[dict] = deque(maxlen=history)

    # --- yaşam döngüsü ---------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    # --- abonelik --------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def on(self, event_type: str, handler: Handler) -> None:
        """Sunucu ici dinleyici (örneğin 'user.text' -> ajani çalıştır)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def replay(self) -> list[dict]:
        """Yeni bağlanan arayüze son olayları geri oynat."""
        return list(self._history)

    # --- yayın -----------------------------------------------------------
    async def emit(self, event_type: str, **payload: Any) -> None:
        event = {"type": event_type, "ts": time.time(), **payload}
        if not event_type.startswith(("audio.level", "system.stats")):
            self._history.append(event)
            _console(event)

        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Arayüz geride kaldıysa en eskiyi at, yenisini koy
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

        for handler in self._handlers.get(event_type, []):
            asyncio.create_task(handler(event))

    def emit_threadsafe(self, event_type: str, **payload: Any) -> None:
        """Ses thread'lerinden güvenli yayın."""
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.emit(event_type, **payload), self._loop)

    # --- kısayollar ------------------------------------------------------
    async def log(self, text: str, level: str = "info") -> None:
        await self.emit("log", level=level, text=text)

    def log_threadsafe(self, text: str, level: str = "info") -> None:
        self.emit_threadsafe("log", level=level, text=text)


bus = EventBus()
