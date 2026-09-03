"""Riley sunucusu: WebSocket köprüleri, açılış sırası ve arayüz komutları."""
from __future__ import annotations

import asyncio
import contextlib
import random
import sys
from pathlib import Path

# 'backend' dizinini yola ekle ki modül importları düz kalsın
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from brain.agent import agent, is_affirmative
from brain.llm import llm
from brain.persona import GREETINGS
from config import CFG, ROOT, mikrofon_kapali
from core.bus import bus
from core.state import State, machine
from skills import REGISTRY, available_skills

FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Riley")

listener = None          # audio.mic.Listener, açılışta kurulur
_boot_task: asyncio.Task | None = None
_hotkey_listener = None


# ---------------------------------------------------------------- açılış --
async def _boot() -> None:
    """Ağır modelleri arka planda yükler; arayüz bu sırada canlıdır."""
    from audio.tts import speaker, speech_pump

    await machine.set(State.BOOTING, "sistemler başlatılıyor")
    asyncio.create_task(speech_pump(agent.speech_queue))

    # 1) Sentezleyici
    await bus.emit("boot.step", step="tts", status="start")
    name = await asyncio.to_thread(speaker.init)
    speaker.start()
    await bus.emit("boot.step", step="tts", status="ok", detail=name)

    # 2) Dil modeli
    await bus.emit("boot.step", step="llm", status="start")
    if await llm.is_alive():
        models = await llm.list_models()
        if not any(CFG.llm.model.split(":")[0] in m for m in models):
            await bus.emit(
                "boot.step", step="llm", status="warn",
                detail=f"{CFG.llm.model} indirilmemiş. Çalıştır: ollama pull {CFG.llm.model}",
            )
        else:
            asyncio.create_task(_warm_llm())
            await bus.emit("boot.step", step="llm", status="ok", detail=CFG.llm.model)
    else:
        await bus.emit(
            "boot.step", step="llm", status="error",
            detail="Ollama çalışmıyor. Başlatmak için: ollama serve",
        )

    # 3) Konuşma tanıma
    await bus.emit("boot.step", step="stt", status="start")
    try:
        from audio.stt import transcriber

        detail = await asyncio.to_thread(transcriber.load)
        await asyncio.to_thread(transcriber.isit)
        await bus.emit("boot.step", step="stt", status="ok", detail=detail)
    except Exception as exc:
        await bus.emit("boot.step", step="stt", status="error", detail=str(exc)[:200])

    # 4) Mikrofon + uyandırma
    global listener
    await bus.emit("boot.step", step="mic", status="start")
    if mikrofon_kapali():
        await bus.emit(
            "boot.step", step="mic", status="warn", detail="mikrofon kapalı"
        )
    else:
        try:
            from audio.mic import Listener

            listener = Listener(on_utterance=_on_utterance)
            await asyncio.to_thread(listener.start)
            await bus.emit(
                "boot.step", step="mic", status="ok",
                detail=(
                    CFG.wake.model
                    if listener.wake.ready
                    else f'"{CFG.persona.name}" de'
                ),
            )
        except Exception as exc:
            await bus.emit(
                "boot.step", step="mic", status="error", detail=str(exc)[:200]
            )

    # 5) Kısayol tuşu ve telemetri
    _start_hotkey()
    asyncio.create_task(_telemetry_loop())

    await machine.set(State.IDLE)
    await bus.emit("boot.done", skills=len(available_skills()))
    await agent.speak(random.choice(GREETINGS))


async def _warm_llm() -> None:
    try:
        await llm.warmup()
        await bus.log(f"{CFG.llm.model} belleğe yüklendi.", "debug")
    except Exception as exc:
        await bus.log(f"Model önceden yüklenemedi: {exc}", "warn")


async def _telemetry_loop() -> None:
    """HUD'daki göstergeler için saniyede bir sistem ölçüleri yayınlar."""
    import psutil

    from skills.system import _gpu_stats

    psutil.cpu_percent(interval=None)  # ilk çağrı her zaman 0 döner
    tick = 0
    while True:
        try:
            mem = psutil.virtual_memory()
            payload = {
                "cpu": psutil.cpu_percent(interval=None),
                "ram": mem.percent,
                "ram_used": round(mem.used / 1e9, 1),
                "ram_total": round(mem.total / 1e9, 1),
            }
            if tick % 5 == 0:  # nvidia-smi pahalı, 5 saniyede bir yeter
                gpu = await asyncio.to_thread(_gpu_stats)
                payload["gpu_text"] = gpu
            await bus.emit("system.stats", **payload)
        except Exception:
            pass
        tick += 1
        await asyncio.sleep(1.0)


def _start_hotkey() -> None:
    """Global kısayol: konuşmayı elle başlat."""
    global _hotkey_listener
    try:
        from pynput import keyboard

        def on_activate() -> None:
            if listener is not None:
                listener.trigger()
                bus.emit_threadsafe("wake", score=1.0, source="hotkey")

        _hotkey_listener = keyboard.GlobalHotKeys({CFG.wake.hotkey: on_activate})
        _hotkey_listener.start()
        bus.log_threadsafe(f"Kısayol aktif: {CFG.wake.hotkey}", "info")
    except Exception as exc:
        bus.log_threadsafe(f"Kısayol kurulamadı: {exc}", "warn")


async def _on_speech_end(event: dict) -> None:
    """Riley sustuğunda kısa bir devam penceresi açılır: kullanıcı adını
    tekrar söylemeden konuşmaya devam edebilir."""
    from audio.tts import speaker

    if listener is not None and not speaker.is_speaking:
        listener.arm_follow_up()


def _on_utterance(text: str) -> None:
    """Mikrofon is parçacığından gelen metni ajana yönlendirir."""
    loop = bus.loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(route_user_input(text, source="voice"), loop)


# ------------------------------------------------------------ yönlendirme --
async def route_user_input(text: str, source: str = "ui") -> None:
    """Kullanıcı girdisi: önce onay bekleniyor mu diye bak, sonra ajana ver."""
    text = (text or "").strip()
    if not text:
        return

    if agent.awaiting_confirmation:
        decision = is_affirmative(text)
        if decision is None:
            await agent.speak("Onaylıyor musunuz? Lütfen evet ya da hayır deyin.")
            return
        agent.resolve_confirmation(decision)
        await bus.emit("user.said", text=text, source=source)
        if not decision:
            await agent.speak("Tamam, iptal ettim.")
        return

    # Konuşmayı kesme komutları ajana hiç gitmesin
    from audio.tts import speaker

    lowered = text.lower().strip(" .!?")
    if lowered in {"dur", "sus", "kes", "iptal", "tamam dur", "yeter"}:
        speaker.stop()
        machine.request_cancel()
        await bus.emit("user.said", text=text, source=source)
        await machine.set(State.IDLE)
        return

    await agent.handle(text)


# --------------------------------------------------------------- HTTP API --
@app.get("/api/health")
async def health() -> JSONResponse:
    from audio.stt import transcriber
    from audio.tts import speaker

    return JSONResponse({
        "state": machine.current.value,
        "llm": {"model": CFG.llm.model, "alive": await llm.is_alive()},
        "stt": {"device": transcriber.device, "loaded": transcriber.model is not None},
        "tts": {"engine": speaker.engine_name},
        "wake": {"ready": bool(listener and listener.wake.ready)},
        "skills": len(available_skills()),
    })


@app.get("/api/skills")
async def skills_list() -> JSONResponse:
    return JSONResponse([
        {
            "name": s.name,
            "description": s.description,
            "confirm": s.confirm,
            "level": s.level,
        }
        for s in sorted(REGISTRY.values(), key=lambda s: s.name)
    ])


@app.get("/api/config")
async def get_config() -> JSONResponse:
    return JSONResponse(CFG.to_dict())


# Arayüzden canlı değiştirilebilen ayarlar: (bölüm, alan) -> dönüştürücü
_AYARLANABILIR: dict[str, tuple[str, str, type]] = {
    "tts_speed": ("tts", "speed", float),
    "tts_voice": ("tts", "voice", str),
    "wake_mode": ("wake", "mode", str),
    "follow_up_s": ("wake", "follow_up_s", float),
    "address": ("persona", "address", str),
    "model": ("llm", "model", str),
    "temperature": ("llm", "temperature", float),
    "perm_level": ("perms", "level", str),
    "stt_model": ("stt", "model_size", str),
    "beam_size": ("stt", "beam_size", int),
}


@app.post("/api/settings")
async def update_settings(request: Request) -> JSONResponse:
    """Arayüzden gelen ayarları uygular ve diske yazar.

    Ses hızı, hitap ve model gibi ayarlar anında geçerli olur; uyandırma
    kipi değişikliği yeniden başlatma ister.
    """
    gelen = await request.json()
    uygulanan: dict[str, object] = {}
    yeniden_baslat = False

    for anahtar, deger in gelen.items():
        hedef = _AYARLANABILIR.get(anahtar)
        if hedef is None:
            continue
        bolum, alan, tur = hedef
        try:
            setattr(getattr(CFG, bolum), alan, tur(deger))
        except (TypeError, ValueError):
            continue
        uygulanan[anahtar] = deger
        if anahtar in ("wake_mode", "tts_voice", "stt_model"):
            yeniden_baslat = True

    if "model" in uygulanan:
        llm.model = CFG.llm.model
        asyncio.create_task(_warm_llm())

    if uygulanan:
        CFG.save()
        await bus.log(
            "Ayarlar güncellendi: "
            + ", ".join(f"{k}={v}" for k, v in uygulanan.items()),
            "info",
        )

    return JSONResponse({
        "ok": True,
        "applied": uygulanan,
        "restart_required": yeniden_baslat,
    })


@app.get("/api/models")
async def list_models() -> JSONResponse:
    """Ollama'da kurulu modelleri listeler."""
    try:
        return JSONResponse({"models": await llm.list_models(), "current": CFG.llm.model})
    except Exception as exc:
        return JSONResponse({"models": [], "current": CFG.llm.model, "error": str(exc)})


@app.get("/api/memory")
async def get_memory() -> JSONResponse:
    from skills.misc import _load_memory

    return JSONResponse(_load_memory())


# --------------------------------------------------------------- WebSocket --
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    queue = bus.subscribe()

    await ws.send_json({
        "type": "hello",
        "state": machine.current.value,
        "persona": CFG.persona.name,
        "model": CFG.llm.model,
        "hotkey": CFG.wake.hotkey,
        "skills": [s.name for s in available_skills()],
    })
    for event in bus.replay()[-40:]:
        await ws.send_json(event)

    async def pump() -> None:
        while True:
            event = await queue.get()
            await ws.send_json(event)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            message = await ws.receive_json()
            await _handle_ui_message(message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await bus.log(f"WebSocket hatası: {exc}", "warn")
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        bus.unsubscribe(queue)


async def _handle_ui_message(message: dict) -> None:
    from audio.tts import speaker

    kind = message.get("type")

    if kind == "text":
        await route_user_input(message.get("text", ""), source="ui")

    elif kind == "listen":
        if listener is not None:
            listener.trigger()
            await bus.emit("wake", score=1.0, source="ui")

    elif kind == "confirm":
        if agent.awaiting_confirmation:
            agent.resolve_confirmation(bool(message.get("approved")))

    elif kind == "cancel":
        speaker.stop()
        machine.request_cancel()
        await machine.set(State.IDLE)

    elif kind == "reset":
        agent.reset()
        await bus.log("Sohbet geçmişi temizlendi.", "info")

    elif kind == "say":
        await agent.speak(message.get("text", ""))

    elif kind == "ping":
        await bus.emit("pong")


# --------------------------------------------------------- yaşam döngüsü --
@app.on_event("startup")
async def on_startup() -> None:
    global _boot_task
    bus.bind_loop(asyncio.get_running_loop())
    bus.on("assistant.say", lambda e: agent.speak(e.get("text", "")))
    bus.on("speech.end", _on_speech_end)
    _boot_task = asyncio.create_task(_boot())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    from audio.tts import speaker

    if listener is not None:
        listener.stop()
    speaker.stop()
    if _hotkey_listener is not None:
        with contextlib.suppress(Exception):
            _hotkey_listener.stop()
    await llm.close()


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def run() -> None:
    uvicorn.run(
        app,
        host=CFG.server.host,
        port=CFG.server.port,
        log_level="warning",
        ws_ping_interval=20,
    )


if __name__ == "__main__":
    run()
