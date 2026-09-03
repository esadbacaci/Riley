"""Dosya ve klasör becerileri. Yazma işlemleri izin verilen koklarla sınırlıdır."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from config import CFG
from skills.registry import SkillError, skill

MAX_READ_CHARS = 6000
SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
]
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "AppData", "$RECYCLE.BIN"}


def _expand(raw: str) -> Path:
    """Kullanıcının söylediği yolu gerçek bir Path'e çevirir."""
    text = (raw or "").strip().strip('"').strip("'")
    turkish = {
        "masaustu": "Desktop", "masaüstü": "Desktop", "desktop": "Desktop",
        "belgeler": "Documents", "belgelerim": "Documents", "documents": "Documents",
        "indirilenler": "Downloads", "downloads": "Downloads",
        "resimler": "Pictures", "pictures": "Pictures",
        "muzikler": "Music", "müzikler": "Music", "music": "Music",
        "videolar": "Videos", "videos": "Videos",
    }
    low = text.lower()
    if low in turkish:
        return Path.home() / turkish[low]

    # "masaustu/notlar.txt" gibi karma yollar
    head, sep, tail = text.replace("\\", "/").partition("/")
    if sep and head.lower() in turkish:
        return Path.home() / turkish[head.lower()] / tail

    return Path(os.path.expandvars(os.path.expanduser(text)))


def _assert_writable(path: Path) -> None:
    resolved = path.resolve()
    for root in CFG.perms.allowed_write_roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return
        except ValueError:
            continue
    allowed = ", ".join(Path(r).name for r in CFG.perms.allowed_write_roots)
    raise SkillError(
        f"Bu konuma yazma yetkim yok: {resolved}. Sadece su klasörlerde yazabilirim: {allowed}."
    )


@skill(
    name="search_files",
    description=(
        "Masaustu, Belgeler, Indirilenler gibi klasörlerde isme göre dosya arar. "
        "Kullanıcı bir dosyayı bulmanı istediğinde kullan."
    ),
    params={
        "query": {"type": "string", "description": "Dosya adında geçen kelime"},
        "limit": {"type": "integer", "description": "En fazla kac sonuç, varsayılan 12"},
    },
    required=["query"],
    level="narrow",
)
def search_files(query: str, limit: int = 12) -> str:
    needle = query.lower().strip()
    if not needle:
        raise SkillError("Ne arayacağımı söylemedin.")

    hits: list[str] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if needle in name.lower():
                    hits.append(str(Path(dirpath) / name))
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    if not hits:
        return f"{query} ile eşleşen dosya bulamadım."
    return f"{len(hits)} sonuç bulundu:\n" + "\n".join(hits)


@skill(
    name="list_dir",
    description="Bir klasörün içeriğini listeler.",
    params={"path": {"type": "string", "description": "Klasör yolu, orn: masaustu"}},
    required=["path"],
    level="narrow",
)
def list_dir(path: str) -> str:
    target = _expand(path)
    if not target.exists():
        raise SkillError(f"Bulamadım: {target}")
    if not target.is_dir():
        raise SkillError(f"Bu bir klasör değil: {target}")

    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        return f"{target} boş."
    lines = [
        ("[K] " if e.is_dir() else "    ") + e.name
        for e in entries[:60]
    ]
    extra = f"\n... ve {len(entries) - 60} kayıt daha" if len(entries) > 60 else ""
    return f"{target} içeriği ({len(entries)} kayıt):\n" + "\n".join(lines) + extra


@skill(
    name="read_file",
    description=(
        "Bir metin dosyasının içeriğini okur. Kullanıcı bir dosyayı okumanı, "
        "özetlemeni veya içinde ne yazdığını sorduğunda kullan."
    ),
    params={"path": {"type": "string", "description": "Dosyanin tam yolu"}},
    required=["path"],
    level="narrow",
)
def read_file(path: str) -> str:
    target = _expand(path)
    if not target.exists():
        raise SkillError(f"Dosya yok: {target}")
    if target.is_dir():
        raise SkillError("Bu bir klasör; içeriği için list_dir kullan.")
    if target.stat().st_size > 5_000_000:
        raise SkillError("Dosya cok büyük (5 MB üzeri).")

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = target.read_text(encoding="cp1254")
        except Exception as exc:
            raise SkillError(f"Bu dosya metin olarak okunamıyor: {exc}") from exc

    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n... (ilk {MAX_READ_CHARS} karakter gösterildi)"
    return f"{target.name} içeriği:\n{text}"


@skill(
    name="write_file",
    description=(
        "Bir metin dosyası oluşturur veya üzerine yazar. Kullanıcı not almanı, "
        "bir dosya oluşturmanı istediğinde kullan."
    ),
    params={
        "path": {"type": "string", "description": "Dosya yolu, orn: masaustu/notlar.txt"},
        "content": {"type": "string", "description": "Dosyaya yazılacak içerik"},
        "append": {"type": "boolean", "description": "true ise sonuna ekler"},
    },
    required=["path", "content"],
)
def write_file(path: str, content: str, append: bool = False) -> str:
    target = _expand(path)
    _assert_writable(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if append else "w"
    with open(target, mode, encoding="utf-8") as fh:
        fh.write(content if not append else "\n" + content)

    action = "eklendi" if append else "yazıldı"
    return f"{target} dosyasına {len(content)} karakter {action}."


@skill(
    name="open_path",
    description=(
        "Bir dosyayı varsayılan uygulamasıyla açar veya bir klasörü dosya "
        "gezgininde gösterir."
    ),
    params={"path": {"type": "string", "description": "Açılacak dosya veya klasör yolu"}},
    required=["path"],
    level="narrow",
)
def open_path(path: str) -> str:
    target = _expand(path)
    if not target.exists():
        raise SkillError(f"Bulamadım: {target}")
    os.startfile(str(target))
    return f"{target.name} açıldı."


@skill(
    name="delete_path",
    description=(
        "Bir dosyayı veya klasörü siler. Geri alınamaz, bu yüzden her zaman "
        "kullanıcıdan onay alınır."
    ),
    params={"path": {"type": "string", "description": "Silinecek dosya veya klasör yolu"}},
    required=["path"],
    confirm=True,
)
def delete_path(path: str) -> str:
    target = _expand(path)
    _assert_writable(target)
    if not target.exists():
        raise SkillError(f"Zaten yok: {target}")

    if target.is_dir():
        shutil.rmtree(target)
        return f"{target} klasörü silindi."
    target.unlink()
    return f"{target.name} silindi."
