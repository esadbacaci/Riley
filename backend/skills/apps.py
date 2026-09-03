"""Uygulama açma/kapatma ve pencere yönetimi (Windows)."""
from __future__ import annotations

import difflib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

import psutil

from skills.registry import SkillError, skill

# Isimden komuta doğrudan eşleşmeler (Start Menu aramasından önce denenir)
ALIASES: dict[str, str] = {
    "not defteri": "notepad.exe", "notepad": "notepad.exe",
    "hesap makinesi": "calc.exe", "hesap makinasi": "calc.exe", "calculator": "calc.exe",
    "paint": "mspaint.exe", "boya": "mspaint.exe",
    "dosya gezgini": "explorer.exe", "gezgin": "explorer.exe", "explorer": "explorer.exe",
    "komut istemi": "cmd.exe", "cmd": "cmd.exe", "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "görev yöneticisi": "taskmgr.exe", "task manager": "taskmgr.exe",
    "ayarlar": "ms-settings:", "settings": "ms-settings:",
    "denetim masası": "control.exe",
    "kayıt defteri": "regedit.exe",
    "kamera": "microsoft.windows.camera:",
    "takvim": "outlookcal:", "saat": "ms-clock:",
    "mağaza": "ms-windows-store:", "store": "ms-windows-store:",
}

_START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path.home() / "Desktop",
]


@lru_cache(maxsize=1)
def _shortcut_index() -> dict[str, str]:
    """Start Menu'deki tum kısayolları {kucuk_isim: yol} olarak tarar."""
    index: dict[str, str] = {}
    for base in _START_MENU_DIRS:
        if not base.exists():
            continue
        try:
            for path in base.rglob("*"):
                if path.suffix.lower() in (".lnk", ".url", ".appref-ms"):
                    index.setdefault(path.stem.lower(), str(path))
        except (PermissionError, OSError):
            continue
    return index


def _fold(text: str) -> str:
    """Turkce karakterleri sadeleştirir; 'Görev' ile 'gorev' aynı kabul edilsin."""
    table = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")
    return text.strip().lower().translate(table)


_FOLDED_ALIASES = {_fold(k): v for k, v in ALIASES.items()}


def _resolve(name: str) -> str:
    key = _fold(name)

    if key in _FOLDED_ALIASES:
        return _FOLDED_ALIASES[key]

    index = {_fold(k): v for k, v in _shortcut_index().items()}
    if key in index:
        return index[key]

    # "chrome" -> "Google Chrome" gibi kısmi eşleşme
    partial = [k for k in index if key in k or k in key]
    if partial:
        return index[min(partial, key=len)]

    close = difflib.get_close_matches(key, list(index), n=1, cutoff=0.62)
    if close:
        return index[close[0]]

    # PATH üzerinde doğrudan çalıştırılabilir mi?
    for candidate in (key, f"{key}.exe"):
        found = subprocess.run(
            ["where", candidate], capture_output=True, text=True, shell=True
        )
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip().splitlines()[0]

    raise SkillError(
        f"'{name}' adında bir uygulama bulamadım. Tam adını söyler misin?"
    )


@skill(
    name="open_app",
    description=(
        "Bilgisayarda bir uygulamayı açar. Kullanıcı 'X'i ac', 'X'i baslat' dediğinde "
        "kullan. Örnek: chrome, spotify, not defteri, hesap makinesi, vscode, discord."
    ),
    params={"app": {"type": "string", "description": "Açılacak uygulamanın adı"}},
    required=["app"],
    level="narrow",
)
def open_app(app: str) -> str:
    target = _resolve(app)
    try:
        if target.endswith(":") or "://" in target:      # ms-settings: gibi URI'ler
            os.startfile(target)
        else:
            os.startfile(target)
    except OSError as exc:
        raise SkillError(f"'{app}' açılamadı: {exc}") from exc
    return f"{app} açıldı."


@skill(
    name="close_app",
    description=(
        "Çalışan bir uygulamayı kapatır. Kullanıcı 'X'i kapat' dediğinde kullan."
    ),
    params={"app": {"type": "string", "description": "Kapatılacak uygulamanın adı"}},
    required=["app"],
)
def close_app(app: str) -> str:
    key = app.strip().lower().replace(".exe", "")
    killed: list[str] = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            pname = (proc.info["name"] or "").lower()
            if key in pname.replace(".exe", ""):
                proc.terminate()
                killed.append(proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not killed:
        raise SkillError(f"'{app}' çalışmıyor görünüyor.")
    return f"{len(killed)} süreç kapatıldı: {', '.join(sorted(set(killed))[:5])}"


@skill(
    name="list_windows",
    description="Su anda açık olan pencerelerin başlık listesini döndürür.",
    level="narrow",
)
def list_windows() -> str:
    import pygetwindow as gw

    titles = [t for t in gw.getAllTitles() if t and t.strip()]
    if not titles:
        return "Açık pencere yok."
    return "Açık pencereler: " + "; ".join(titles[:15])


@skill(
    name="focus_window",
    description="Adı verilen pencereyi one getirir ve odaklar.",
    params={"title": {"type": "string", "description": "Pencere başlığının bir parçası"}},
    required=["title"],
    level="narrow",
)
def focus_window(title: str) -> str:
    import pygetwindow as gw

    matches = [w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower()]
    if not matches:
        raise SkillError(f"'{title}' başlığıyla eşleşen pencere yok.")
    win = matches[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
    except Exception as exc:
        raise SkillError(f"Pencere one getirilemedi: {exc}") from exc
    return f"'{win.title}' one getirildi."
