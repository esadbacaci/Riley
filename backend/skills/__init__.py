"""Tum beceri modüllerini yükler; import edilmeleri kayıt için yeterlidir."""
from skills import apps, files, misc, system, web  # noqa: F401
from skills.registry import (  # noqa: F401
    REGISTRY,
    ConfirmationRequired,
    Skill,
    SkillError,
    available_skills,
    needs_confirmation,
    run_skill,
    tool_schemas,
)
