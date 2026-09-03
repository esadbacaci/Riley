"""Merkezi yapılandırma. Tum yollar ve ayarlar buradan okunur."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
TOOLS_DIR = ROOT / "tools"

for _d in (DATA_DIR, DATA_DIR / "logs", DATA_DIR / "captures", MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

USER_SETTINGS = DATA_DIR / "settings.json"


@dataclass
class LLMConfig:
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    temperature: float = 0.6
    num_ctx: int = 8192
    keep_alive: str = "30m"
    # qwen3 varsayılan olarak "düşünme" modunda çalışır: cevap öncesi uzun bir
    # muhakeme metni üretir. Sesli asistanda bu hem gecikme hem de saçma
    # seslendirme demek, o yüzden kapalı.
    think: bool = False
    max_tool_rounds: int = 5


@dataclass
class STTConfig:
    model_size: str = "small"          # tiny | base | small | medium
    # RTX 5060 (Blackwell) için CTranslate2 CUDA desteği henüz oturmadı;
    # "auto" önce GPU dener, hata alırsa CPU'ya düşer.
    device: str = "auto"
    compute_type_gpu: str = "float16"
    compute_type_cpu: str = "int8"
    language: str = "tr"
    beam_size: int = 1
    vad_aggressiveness: int = 2        # 0-3, yüksek = daha agresif sessizlik kesme
    silence_ms: int = 800              # bu kadar sessizlikten sonra konuşma bitti say
    max_utterance_s: float = 20.0
    min_utterance_ms: int = 350
    # Whisper "Riley" gibi yabancı bir adı Türkçe konuşma içinde tanıyamaz;
    # bu iki ipucu birlikte verildiğinde adı doğru yazıyor.
    initial_prompt: str = "Riley'e sesleniyorum."
    hotwords: str = "Riley"
    # Halüsinasyon süzgeci: bu eşiklerin dışındaki çözümlemeler atılır
    no_speech_max: float = 0.6     # konuşma yokluğu olasılığı üst sınırı
    min_logprob: float = -1.0      # ortalama güven alt sınırı


@dataclass
class TTSConfig:
    engine: str = "piper"              # piper | sapi
    voice: str = "tr_TR-dfki-medium"
    speed: float = 0.80                # <1 hızlı, >1 yavaş (piper length_scale)
    sentence_silence: float = 0.12     # cümleler arası duraklama, saniye
    noise_scale: float = 0.6           # düşük = daha düz ve net tonlama
    noise_w: float = 0.75              # düşük = daha az duraksama


@dataclass
class WakeConfig:
    # "name"     -> adını söyleyerek uyandır: "Riley, sesi kıs"
    # "wakeword" -> openWakeWord hazır modeli (şu an sadece İngilizce sözcükler)
    # "hotkey"   -> yalnızca kısayol tuşu, mikrofon pasif bekler
    mode: str = "name"
    model: str = "hey_jarvis"          # sadece mode="wakeword" iken kullanılır
    # mode="name" iken kabul edilen sesleniş biçimleri. Whisper aynı sesi
    # her zaman aynı yazmadığı için yakın varyantlar da listede.
    # Not: "raylı" listede yok; "raylı sistem" gibi gerçek Türkçe
    # tabirlerde yanlış uyanmaya yol açıyordu.
    names: list[str] = field(default_factory=lambda: [
        "riley", "rayli", "reyli", "rayly", "raily", "gayli", "asistan",
    ])
    threshold: float = 0.55
    cooldown_s: float = 1.5
    # Riley cevabını bitirdikten sonra kaç saniye boyunca adı söylemeden
    # konuşmaya devam edilebilir
    follow_up_s: float = 8.0
    hotkey: str = "<ctrl>+<alt>+r"     # bas-konuş / uyandırma kısayolu


@dataclass
class AudioConfig:
    input_device: int | None = None    # None = sistem varsayılanı
    output_device: int | None = None
    sample_rate: int = 16000           # STT ve wake word bu hızda çalışır
    block_ms: int = 30                 # webrtcvad 10/20/30 ms kabul eder


@dataclass
class PermissionConfig:
    """'Orta' seviye: günlük işler serbest, yıkıcı işlemler onay ister."""
    level: str = "medium"              # narrow | medium | wide
    allowed_write_roots: list[str] = field(default_factory=lambda: [
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
        str(Path.home() / "Downloads"),
        str(ROOT),
    ])
    require_confirm: list[str] = field(default_factory=lambda: [
        "delete_path", "shutdown", "restart", "kill_process", "run_command",
    ])


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8756


@dataclass
class PersonaConfig:
    name: str = "Riley"
    address: str = "Efendim"           # kullanıcıya hitap
    style: str = "cinematic"


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    perms: PermissionConfig = field(default_factory=PermissionConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        USER_SETTINGS.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _merge(dc, data: dict):
    for key, value in data.items():
        if hasattr(dc, key):
            current = getattr(dc, key)
            if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                _merge(current, value)
            else:
                setattr(dc, key, value)


def load() -> Config:
    cfg = Config()
    if USER_SETTINGS.exists():
        try:
            _merge(cfg, json.loads(USER_SETTINGS.read_text(encoding="utf-8")))
        except Exception as exc:  # bozuk dosya kullanıcıyı kilitlemesin
            print(f"[config] settings.json okunamadı, varsayılanlar kullanılıyor: {exc}")
    # Ortam değişkeni her şeyi ezer (hızlı deneme için)
    if os.getenv("RILEY_MODEL"):
        cfg.llm.model = os.environ["RILEY_MODEL"]
    if os.getenv("RILEY_PORT"):
        cfg.server.port = int(os.environ["RILEY_PORT"])
    if os.getenv("RILEY_VOICE"):
        cfg.tts.voice = os.environ["RILEY_VOICE"]
    return cfg


CFG = load()


def mikrofon_kapali() -> bool:
    """RILEY_NO_MIC=1 ile mikrofon tamamen kapatılır.

    Bu bir ortam anahtarıdır; CFG'ye yazılmaz ki settings.json'a sızıp
    kalıcı hâle gelmesin.
    """
    return os.getenv("RILEY_NO_MIC") == "1" or CFG.wake.mode == "off"
