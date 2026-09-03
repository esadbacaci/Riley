"""Ollama istemcisi: akışlı (streaming) sohbet + araç çağırma (tool calling)."""
from __future__ import annotations

import asyncio
import contextvars
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from config import CFG


class OllamaError(RuntimeError):
    pass


class OllamaYenidenDene(OllamaError):
    """Servis toparlandı; çağıran isteği bir kez daha denemeli."""


# Toparlanma denemesinin kendi içinde döngüye girmesini engeller
_yeniden_deneniyor: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_yeniden_deneniyor", default=False
)


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None) -> None:
        self.host = (host or CFG.llm.host).rstrip("/")
        self.model = model or CFG.llm.model
        self._client: httpx.AsyncClient | None = None
        # Gözcü ve istek yolu aynı anda servisi başlatmaya kalkarsa iki
        # llama-server yarışır ve model yüklenirken çöker. Tek kapıdan geçir.
        self._toparlanma_kilidi = asyncio.Lock()

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- sağlık / model yönetimi -----------------------------------------
    async def is_alive(self) -> bool:
        try:
            http = await self._http()
            r = await http.get(f"{self.host}/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        http = await self._http()
        r = await http.get(f"{self.host}/api/tags")
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    async def servisi_baslat(self, bekleme_sn: float = 30.0) -> bool:
        """Ollama kapalıysa başlatmayı dener.

        Ollama Windows'ta bir arka plan servisi olarak kurulur ama çökebilir
        ya da kullanıcı kapatmış olabilir. Riley'nin bu yüzden tamamen
        işlevsiz kalmaması için servisi kendisi ayağa kaldırır.
        """
        import os
        import shutil
        import subprocess

        async with self._toparlanma_kilidi:
            if await self.is_alive():
                return True          # başkası çoktan halletmiş
            return await self._servisi_ayaga_kaldir(bekleme_sn)

    async def _servisi_ayaga_kaldir(self, bekleme_sn: float) -> bool:
        import os
        import shutil
        import subprocess

        calistirilabilir = shutil.which("ollama")
        if calistirilabilir is None:
            aday = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            if aday.exists():
                calistirilabilir = str(aday)
        if calistirilabilir is None:
            return False

        try:
            subprocess.Popen(
                [calistirilabilir, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,      # konsol penceresi açılmasın
            )
        except Exception:
            return False

        bitis = time.monotonic() + bekleme_sn
        while time.monotonic() < bitis:
            if await self.is_alive():
                return True
            await asyncio.sleep(1.0)
        return False

    async def warmup(self) -> None:
        """Modeli VRAM'e önceden yükle ki ilk soru gecikmesin."""
        http = await self._http()
        await http.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": CFG.llm.keep_alive,
                "options": {"num_predict": 1, "num_ctx": CFG.llm.num_ctx},
            },
        )

    # --- ana sohbet döngüsü ----------------------------------------------
    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[dict]:
        """Ollama /api/chat akışını normalize edilmiş olaylara çevirir.

        Üretilen olaylar:
          {"kind": "delta",      "text": str}
          {"kind": "tool_calls", "calls": [{"name": str, "arguments": dict}]}
          {"kind": "done",       "content": str, "stats": dict}
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": CFG.llm.keep_alive,
            "options": {
                "temperature": CFG.llm.temperature if temperature is None else temperature,
                "num_ctx": CFG.llm.num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools
        if CFG.llm.think is not None:
            payload["think"] = CFG.llm.think

        content_parts: list[str] = []
        tool_calls: list[dict] = []
        stats: dict = {}

        http = await self._http()
        try:
            async with http.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")

                    # Model yüklenirken llama-server çökebiliyor. Bu geçici
                    # bir durum; ölümcül saymak yerine bir kez daha denenir.
                    gecici = any(
                        isaret in body.lower()
                        for isaret in (
                            "process has terminated",
                            "loading",
                            "unavailable",
                            "connection refused",
                        )
                    )
                    if gecici and not _yeniden_deneniyor.get():
                        _yeniden_deneniyor.set(True)
                        try:
                            await asyncio.sleep(3.0)
                            raise OllamaYenidenDene(
                                "Model yüklenirken sorun oldu, tekrar deneniyor."
                            )
                        finally:
                            _yeniden_deneniyor.set(False)

                    raise OllamaError(f"Ollama {resp.status_code}: {body[:300]}")

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message") or {}

                    # Düşünme modu açıksa üretilen muhakeme metni seslendirilmez
                    if msg.get("thinking"):
                        yield {"kind": "thinking", "text": msg["thinking"]}

                    piece = msg.get("content")
                    if piece:
                        content_parts.append(piece)
                        yield {"kind": "delta", "text": piece}

                    for call in msg.get("tool_calls") or []:
                        fn = call.get("function", {})
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        tool_calls.append({"name": fn.get("name", ""), "arguments": args or {}})

                    if chunk.get("done"):
                        stats = {
                            "eval_count": chunk.get("eval_count", 0),
                            "eval_duration": chunk.get("eval_duration", 0),
                            "load_duration": chunk.get("load_duration", 0),
                        }
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # Servis çökmüş ya da kapatılmış olabilir: bir kez ayağa
            # kaldırmayı dene. Başarılıysa çağıran tekrar deneyebilsin diye
            # ayrı bir hata türü fırlatılır.
            if not _yeniden_deneniyor.get():
                _yeniden_deneniyor.set(True)
                try:
                    if await self.servisi_baslat():
                        raise OllamaYenidenDene(
                            "Ollama yeniden başlatıldı, istek tekrarlanıyor."
                        ) from exc
                finally:
                    _yeniden_deneniyor.set(False)

            raise OllamaError(
                "Ollama'ya bağlanılamadı. Servis çalışıyor mu? (`ollama serve`)"
            ) from exc

        if tool_calls:
            yield {"kind": "tool_calls", "calls": tool_calls}

        yield {"kind": "done", "content": "".join(content_parts), "stats": stats}


llm = OllamaClient()
