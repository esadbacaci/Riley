"""Riley'in konuşma durumu. HUD'un rengi/animasyonu bunu takip eder."""
from __future__ import annotations

import asyncio
from enum import Enum

from core.bus import bus


class State(str, Enum):
    BOOTING = "booting"     # modeller yükleniyor
    IDLE = "idle"           # bekliyor / wake word dinliyor
    LISTENING = "listening" # kullanıcı konuşuyor, kayıt alınıyor
    THINKING = "thinking"   # LLM çalışıyor
    ACTING = "acting"       # bir beceri (tool) çalışıyor
    SPEAKING = "speaking"   # TTS çalışıyor
    ERROR = "error"


class StateMachine:
    def __init__(self) -> None:
        self._state = State.BOOTING
        self._lock = asyncio.Lock()
        self.cancel_flag = asyncio.Event()   # "dur" komutu için

    @property
    def current(self) -> State:
        return self._state

    def is_busy(self) -> bool:
        return self._state in (State.THINKING, State.ACTING, State.SPEAKING)

    async def set(self, new: State, detail: str = "") -> None:
        async with self._lock:
            if self._state == new and not detail:
                return
            self._state = new
        await bus.emit("state", value=new.value, detail=detail)

    def set_threadsafe(self, new: State, detail: str = "") -> None:
        if bus.loop is None:
            self._state = new
            return
        asyncio.run_coroutine_threadsafe(self.set(new, detail), bus.loop)

    # --- iptal ------------------------------------------------------------
    def request_cancel(self) -> None:
        self.cancel_flag.set()

    def clear_cancel(self) -> None:
        self.cancel_flag.clear()

    @property
    def cancelled(self) -> bool:
        return self.cancel_flag.is_set()


machine = StateMachine()
