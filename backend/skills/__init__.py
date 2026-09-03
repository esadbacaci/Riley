"""Tüm beceri modüllerini yükler; import edilmeleri kayıt için yeterlidir."""
from skills import (  # noqa: F401
    apps, arama, ayarlar, files, misc, pencere, system, tarayici, web,
)
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
