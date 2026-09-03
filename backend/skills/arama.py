"""Dosya içeriğinde arama.

search_files yalnızca dosya adına bakar. Çoğu zaman aranan şey adda değil
içeriktedir: "içinde fatura geçen dosya hangisiydi". Bu beceri metin
dosyalarının içine bakar ve eşleşen satırı bağlamıyla döndürür.
"""
from __future__ import annotations

import os
from pathlib import Path

from skills.registry import SkillError, skill

# İçine bakmanın anlamlı olduğu uzantılar. İkili dosyalar taranmaz.
METIN_UZANTILARI = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini", ".cfg",
    ".log", ".html", ".css", ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h",
    ".cs", ".go", ".rs", ".php", ".rb", ".sh", ".ps1", ".bat", ".sql", ".srt",
}

ARAMA_KOKLERI = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]

ATLANACAK = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "AppData",
    "$RECYCLE.BIN", "dist", "build", ".next", "target",
}

AZAMI_DOSYA_BOYUTU = 3_000_000     # 3 MB üzeri dosyalar atlanır
AZAMI_TARANAN = 4000               # en fazla bu kadar dosya açılır


def _sadelestir(metin: str) -> str:
    return metin.translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")).lower()


@skill(
    name="search_in_files",
    description=(
        "Dosyaların İÇERİĞİNDE metin arar ve eşleşen satırı gösterir. "
        "'İçinde X geçen dosya', 'X'i nerede yazmıştım', 'şu kelimenin geçtiği "
        "belge' gibi isteklerde bunu kullan; dosya adına bakan search_files "
        "değil. Kullanıcının verdiği kelimeyi olduğu gibi ara, başka dile "
        "çevirme, Türkçe kelimeyi Türkçe ara."
    ),
    params={
        "query": {"type": "string", "description": "Dosya içinde aranacak metin"},
        "folder": {
            "type": "string",
            "description": "Aranacak klasör; boşsa Masaüstü, Belgeler ve İndirilenler",
        },
        "limit": {"type": "integer", "description": "En fazla kaç sonuç, varsayılan 10"},
    },
    required=["query"],
    level="narrow",
)
def search_in_files(query: str, folder: str = "", limit: int = 10) -> str:
    aranan = _sadelestir(query.strip())
    if len(aranan) < 2:
        raise SkillError("Aranacak metin en az iki karakter olmalı.")

    limit = max(1, min(30, int(limit)))

    if folder:
        from skills.files import _expand

        kok = _expand(folder)
        if not kok.exists():
            raise SkillError(f"Klasör bulunamadı: {kok}")
        kokler = [kok]
    else:
        kokler = [k for k in ARAMA_KOKLERI if k.exists()]

    bulunanlar: list[str] = []
    taranan = 0

    for kok in kokler:
        for dizin, altlar, dosyalar in os.walk(kok):
            altlar[:] = [
                a for a in altlar if a not in ATLANACAK and not a.startswith(".")
            ]
            for ad in dosyalar:
                if Path(ad).suffix.lower() not in METIN_UZANTILARI:
                    continue

                yol = Path(dizin) / ad
                try:
                    if yol.stat().st_size > AZAMI_DOSYA_BOYUTU:
                        continue
                except OSError:
                    continue

                taranan += 1
                if taranan > AZAMI_TARANAN:
                    break

                eslesme = _dosyada_ara(yol, aranan)
                if eslesme:
                    satir_no, satir = eslesme
                    bulunanlar.append(f"{yol}  (satır {satir_no})\n    {satir}")
                    if len(bulunanlar) >= limit:
                        break
            if len(bulunanlar) >= limit or taranan > AZAMI_TARANAN:
                break
        if len(bulunanlar) >= limit or taranan > AZAMI_TARANAN:
            break

    if not bulunanlar:
        nerede = f"'{folder}' içinde" if folder else "olağan klasörlerde"
        return f"{nerede} '{query}' geçen dosya bulamadım. ({taranan} dosya tarandı)"

    return (
        f"'{query}' şu dosyalarda geçiyor ({taranan} dosya tarandı):\n"
        + "\n".join(bulunanlar)
    )


def _dosyada_ara(yol: Path, aranan: str) -> tuple[int, str] | None:
    """Dosyadaki ilk eşleşmeyi (satır numarası, satır) olarak döndürür."""
    for kodlama in ("utf-8", "cp1254"):
        try:
            with open(yol, "r", encoding=kodlama, errors="strict") as fh:
                for numara, satir in enumerate(fh, 1):
                    if aranan in _sadelestir(satir):
                        kirpik = satir.strip()
                        if len(kirpik) > 160:
                            kirpik = kirpik[:160] + "…"
                        return numara, kirpik
            return None
        except (UnicodeDecodeError, UnicodeError):
            continue      # başka kodlamayla dene
        except (OSError, PermissionError):
            return None
    return None
