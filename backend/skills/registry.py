"""Beceri kayıt defteri.

Her beceri normal bir Python fonksiyonudur; dekoratör onu hem çalıştırılabilir
kilar hem de Ollama'nin beklediği JSON-Schema araç tanımına çevirir.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from config import CFG


class SkillError(Exception):
    """Kullanıcıya söylenebilecek, beklenen hata."""


class ConfirmationRequired(Exception):
    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


@dataclass
class Skill:
    name: str
    description: str
    fn: Callable
    params: dict = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    confirm: bool = False
    level: str = "medium"       # narrow | medium | wide -> gereken en düşük yetki
    speak: bool = True          # sonucu LLM'e geri besle

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                },
            },
        }


_LEVEL_ORDER = {"narrow": 0, "medium": 1, "wide": 2}
REGISTRY: dict[str, Skill] = {}


def skill(
    name: str,
    description: str,
    params: dict | None = None,
    required: list[str] | None = None,
    confirm: bool = False,
    level: str = "medium",
    speak: bool = True,
):
    def decorator(fn: Callable) -> Callable:
        REGISTRY[name] = Skill(
            name=name,
            description=description,
            fn=fn,
            params=params or {},
            required=required or [],
            confirm=confirm,
            level=level,
            speak=speak,
        )
        return fn

    return decorator


def available_skills() -> list[Skill]:
    """Kullanıcının yetki seviyesine uyan beceriler."""
    user_level = _LEVEL_ORDER.get(CFG.perms.level, 1)
    return [s for s in REGISTRY.values() if _LEVEL_ORDER.get(s.level, 1) <= user_level]


def tool_schemas() -> list[dict]:
    return [s.schema() for s in available_skills()]


def needs_confirmation(name: str) -> bool:
    sk = REGISTRY.get(name)
    if sk is None:
        return False
    return sk.confirm or name in CFG.perms.require_confirm


async def run_skill(name: str, arguments: dict[str, Any]) -> dict:
    """Beceriyi çalıştırır; her zaman {ok, result|error} döndürür."""
    sk = REGISTRY.get(name)
    if sk is None:
        return {"ok": False, "error": f"'{name}' adında bir becerim yok."}

    if _LEVEL_ORDER.get(sk.level, 1) > _LEVEL_ORDER.get(CFG.perms.level, 1):
        return {"ok": False, "error": f"'{name}' mevcut yetki seviyende kapalı."}

    # Fazladan/eksik parametreleri sessizce temizle
    sig = inspect.signature(sk.fn)
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not accepts_kwargs:
        arguments = {k: v for k, v in arguments.items() if k in sig.parameters}
    for req in sk.required:
        if req not in arguments:
            return {"ok": False, "error": f"'{req}' parametresi eksik."}

    try:
        if inspect.iscoroutinefunction(sk.fn):
            result = await sk.fn(**arguments)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, functools.partial(sk.fn, **arguments)
            )
        return {"ok": True, "result": result}
    except SkillError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=3),
        }
