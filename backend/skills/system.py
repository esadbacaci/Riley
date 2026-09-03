"""Sistem kontrolü: ses, ekran görüntüsü, medya tuşları, pano, guc, istatistik."""
from __future__ import annotations

import datetime as dt
import os
import subprocess

import psutil

from pathlib import Path

from config import DATA_DIR
from skills.registry import SkillError, skill

# --- Ses seviyesi (pycaw) ------------------------------------------------


def _volume_iface():
    """Sistem ses denetimini döndürür.

    pycaw'ın yeni sürümlerinde GetSpeakers() bir AudioDevice sarmalayıcısı
    döndürür ve arayüz .EndpointVolume ile alınır; eski sürümlerde ise ham
    COM nesnesi gelir ve Activate çağrılması gerekir. İkisi de desteklenir.
    """
    try:
        from comtypes import CoInitialize
        from pycaw.pycaw import AudioUtilities

        CoInitialize()
        speakers = AudioUtilities.GetSpeakers()

        arayuz = getattr(speakers, "EndpointVolume", None)
        if arayuz is not None:
            return arayuz

        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume

        ham = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(ham, POINTER(IAudioEndpointVolume))
    except Exception as exc:
        raise SkillError(f"Ses aygıtına erişemedim: {exc}") from exc


@skill(
    name="set_volume",
    description=(
        "Sistem ses seviyesini yüzde olarak ayarlar (0-100). "
        "Kullanıcı sesi kis, sesi ac ya da sesi yüzde elli yap dediğinde kullan."
    ),
    params={"percent": {"type": "integer", "description": "0 ile 100 arası ses seviyesi"}},
    required=["percent"],
)
def set_volume(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    vol = _volume_iface()
    vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
    return f"Ses %{percent} yapıldı."


@skill(
    name="get_volume",
    description="Mevcut sistem ses seviyesini yüzde olarak döndürür.",
    level="narrow",
)
def get_volume() -> str:
    vol = _volume_iface()
    return f"Ses seviyesi %{round(vol.GetMasterVolumeLevelScalar() * 100)}."


@skill(
    name="mute",
    description="Sesi tamamen kapatır veya geri açar.",
    params={"on": {"type": "boolean", "description": "true = sessize al, false = sesi ac"}},
    required=["on"],
)
def mute(on: bool) -> str:
    vol = _volume_iface()
    vol.SetMute(bool(on), None)
    return "Ses kapatıldı." if on else "Ses açıldı."


# --- Medya tuşları -------------------------------------------------------

_MEDIA_KEYS = {
    "play": "playpause",
    "pause": "playpause",
    "playpause": "playpause",
    "next": "nexttrack",
    "sonraki": "nexttrack",
    "previous": "prevtrack",
    "önceki": "prevtrack",
    "stop": "stop",
}


@skill(
    name="media_control",
    description=(
        "Muzik veya video oynatmayı kontrol eder: oynat-duraklat, sonraki parça, "
        "önceki parça, durdur. Spotify ve YouTube dahil tum uygulamalarda çalışır."
    ),
    params={
        "action": {
            "type": "string",
            "enum": ["playpause", "next", "previous", "stop"],
            "description": "Yapılacak işlem",
        }
    },
    required=["action"],
)
def media_control(action: str) -> str:
    import pyautogui

    key = _MEDIA_KEYS.get(action.lower())
    if not key:
        raise SkillError(f"{action} bilinmeyen bir medya komutu.")
    pyautogui.press(key)
    labels = {
        "playpause": "Oynat/duraklat gönderildi.",
        "nexttrack": "Sonraki parçaya geçildi.",
        "prevtrack": "Önceki parçaya dönüldü.",
        "stop": "Oynatma durduruldu.",
    }
    return labels[key]


# --- Ekran görüntüsü -----------------------------------------------------


@skill(
    name="take_screenshot",
    description=(
        "Ekranın görüntüsünü alır ve dosyaya kaydeder. Kullanıcı ekran görüntüsü al "
        "ya da ekranı kaydet dediğinde kullan."
    ),
    params={
        "monitor": {
            "type": "integer",
            "description": "Ekran numarası; 0 = tum ekranlar, 1 = birincil ekran",
        }
    },
)
def take_screenshot(monitor: int = 1) -> str:
    import mss
    import mss.tools

    # Resimler klasörü, proje içindeki data klasöründen daha bulunabilir
    out_dir = Path.home() / "Pictures" / "Riley"
    if not out_dir.parent.exists():
        out_dir = DATA_DIR / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"ekran_{stamp}.png"

    with mss.mss() as sct:
        idx = 0 if monitor == 0 else min(max(1, monitor), len(sct.monitors) - 1)
        shot = sct.grab(sct.monitors[idx])
        mss.tools.to_png(shot.rgb, shot.size, output=str(path))

    return f"Ekran görüntüsü kaydedildi: {path}"


# --- Pano ----------------------------------------------------------------


@skill(
    name="clipboard_read",
    description="Panodaki kopyalanmış metni okur.",
    level="narrow",
)
def clipboard_read() -> str:
    import pyperclip

    text = pyperclip.paste() or ""
    if not text.strip():
        return "Pano boş."
    return f"Panodaki metin: {text[:1500]}"


@skill(
    name="clipboard_write",
    description="Verilen metni panoya kopyalar.",
    params={"text": {"type": "string", "description": "Panoya kopyalanacak metin"}},
    required=["text"],
)
def clipboard_write(text: str) -> str:
    import pyperclip

    pyperclip.copy(text)
    return "Metin panoya kopyalandı."


@skill(
    name="type_text",
    description=(
        "Odakta olan pencereye klavyeden yazıyormuş gibi metin yazar. "
        "Kullanıcı bir yere metin yazdırmak istediğinde kullan."
    ),
    params={"text": {"type": "string", "description": "Yazılacak metin"}},
    required=["text"],
)
def type_text(text: str) -> str:
    import pyautogui
    import pyperclip

    # Türkçe karakterler pyautogui.write ile bozulur; pano + Ctrl+V güvenli yol.
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    return f"{len(text)} karakter yazıldı."


# --- Sistem durumu -------------------------------------------------------


def _gpu_stats() -> str:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return ""
        util, used, total, temp = [x.strip() for x in out.stdout.strip().split(",")]
        return f"ekran kartı %{util} ({used}/{total} MB, {temp} derece)"
    except Exception:
        return ""


@skill(
    name="system_stats",
    description=(
        "Bilgisayarın anlık durumunu döndürür: işlemci, bellek, disk kullanımı, "
        "pil ve açık kalma süresi. Bilgisayarın durumu nasıl sorusunda kullan."
    ),
    level="narrow",
)
def system_stats() -> str:
    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    boot = dt.datetime.fromtimestamp(psutil.boot_time())
    uptime = dt.datetime.now() - boot

    parts = [
        f"işlemci %{cpu:.0f}",
        f"bellek %{mem.percent:.0f} ({mem.used / 1e9:.1f}/{mem.total / 1e9:.1f} GB)",
        f"C diski %{disk.percent:.0f} dolu ({disk.free / 1e9:.0f} GB boş)",
        f"açık kalma süresi {uptime.days} gün {uptime.seconds // 3600} saat",
    ]

    battery = psutil.sensors_battery()
    if battery:
        parts.append(
            f"pil %{battery.percent:.0f}" + (" şarjda" if battery.power_plugged else "")
        )

    gpu = _gpu_stats()
    if gpu:
        parts.append(gpu)

    return "Sistem durumu: " + ", ".join(parts) + "."


# --- Guc / oturum --------------------------------------------------------


@skill(
    name="lock_screen",
    description="Bilgisayarı kilitler, oturumu kapatmaz.",
)
def lock_screen() -> str:
    os.system("rundll32.exe user32.dll,LockWorkStation")
    return "Bilgisayar kilitlendi."


@skill(
    name="shutdown",
    description=(
        "Bilgisayarı kapatır veya yeniden başlatır. Yıkıcı işlem olduğu için "
        "her zaman kullanıcıdan onay alınır."
    ),
    params={
        "mode": {
            "type": "string",
            "enum": ["shutdown", "restart"],
            "description": "Işlem turu",
        },
        "delay_seconds": {
            "type": "integer",
            "description": "Kac saniye sonra yapılacağı, varsayılan 30",
        },
    },
    required=["mode"],
    confirm=True,
)
def shutdown(mode: str, delay_seconds: int = 30) -> str:
    flag = "/s" if mode == "shutdown" else "/r"
    subprocess.run(["shutdown", flag, "/t", str(max(0, int(delay_seconds)))], check=False)
    label = "kapatılacak" if mode == "shutdown" else "yeniden başlatılacak"
    return f"Bilgisayar {delay_seconds} saniye sonra {label}. Iptal için iptal et de."


@skill(
    name="cancel_shutdown",
    description="Planlanmış kapatma veya yeniden başlatma işlemini iptal eder.",
)
def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"], check=False)
    return "Kapatma işlemi iptal edildi."
