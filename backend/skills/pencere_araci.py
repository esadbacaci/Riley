"""Pencereleri öne getirmek için ortak yardımcı.

pygetwindow'un activate() yöntemi Windows'ta işlem başarılı olsa bile
"Error code from Windows: 0 - The operation completed successfully" diye
hata fırlatabiliyor. Buna güvenip pencereyi bulunamadı saymak yerine
sonucu doğrudan doğruluyoruz.
"""
from __future__ import annotations

import ctypes
import time

SW_RESTORE = 9

# Oturum kilitliyken bu süreçler öndedir ve Windows başka hiçbir pencerenin
# öne gelmesine izin vermez. Bunu "pencere bulunamadı" sanmamak gerekiyor.
KILIT_SURECLERI = {"lockapp.exe", "logonui.exe"}


def one_getir(pencere, bekleme: float = 0.35) -> bool:
    """Pencereyi öne getirir; gerçekten öne geldiyse True döner."""
    user32 = ctypes.windll.user32
    hwnd = getattr(pencere, "_hWnd", None)
    if hwnd is None:
        return False

    try:
        if pencere.isMinimized:
            pencere.restore()
    except Exception:
        user32.ShowWindow(hwnd, SW_RESTORE)

    try:
        pencere.activate()
    except Exception:
        pass                      # kütüphane yanlış hata atıyor, yok say

    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

    time.sleep(bekleme)
    try:
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def surec_adi(pencere) -> str:
    """Pencerenin ait olduğu sürecin adı (küçük harf), bulunamazsa boş."""
    try:
        import psutil

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            pencere._hWnd, ctypes.byref(pid)
        )
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def ekran_kilitli() -> bool:
    """Oturum kilitliyse True. Kilitliyken pencere öne getirilemez."""
    try:
        import pygetwindow as gw

        onde = gw.getActiveWindow()
        if onde is None:
            return False
        return surec_adi(onde) in KILIT_SURECLERI
    except Exception:
        return False
