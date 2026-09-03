"""Merkezi yapılandırma. Tüm yollar ve ayarlar buradan okunur."""
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
    # Ölçülen çok dilli kelime hata oranı: small ~%7, large-v3-turbo ~%3.7.
    # Yani turbo hataların yaklaşık yarısını siliyor ve fark, Türkçe gibi
    # kaynağı az dillerde daha da açılıyor. Bedeli ~1 GB fazla bellek ve
    # çözümleme başına birkaç yüz milisaniye; buna değer.
    # Bellek dar gelirse "small" hâlâ seçilebilir.
    model_size: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    # "auto" önce GPU dener, hata alırsa işlemciye düşer.
    device: str = "auto"
    compute_type_gpu: str = "float16"
    compute_type_cpu: str = "int8"
    language: str = "tr"
    beam_size: int = 5                 # 1 en hızlı, 5 belirgin daha doğru
    # Konuşma tespiti. "silero" küçük bir sinir ağı ve klavye/fan gibi
    # sesleri konuşma sanmıyor; webrtcvad ham genliğe baktığı için hem
    # yanlış tetikleniyor hem kısık konuşmayı kaçırıyordu.
    vad_yontemi: str = "auto"          # auto | silero | webrtcvad | enerji
    vad_esigi: float = 0.5             # silero konuşma olasılığı eşiği
    vad_aggressiveness: int = 2        # yalnızca webrtcvad için, 0-3
    # Konuşma sonu tespiti. Bu eşikler gecikme uğruna fazla kısaltılmıştı ve
    # cümle ortasındaki normal duraklamalarda kullanıcının sözü kesiliyordu;
    # yarım cümle Whisper'a gidince de "beni anlamıyor" hissi doğuyordu.
    # İnsanlar konuşurken 300-600 ms rahat duraklar, eşikler bunun üstünde.
    silence_ms: int = 850              # varsayılan bekleme
    kisa_sessizlik_ms: int = 700       # uzun söylemden sonra bu kadar yeter
    uzun_soylem_ms: int = 2000         # bu kadar konuşulduysa "uzun" sayılır
    max_utterance_s: float = 20.0
    min_utterance_ms: int = 350
    # Whisper "Riley" gibi yabancı bir adı Türkçe konuşma içinde zor tanır.
    # Kısa bir ön metin yardımcı oluyor. Uzun ipucu listesi denendi ve
    # geri tepti: büyük model listeyi cevabın içine kusuyordu
    # ("Google Chrome, aç, kapat, ekran görüntüsü, ses, yüzde..."). Bu yüzden
    # ipuçları kısa tutuluyor ve çıktı sızıntıya karşı ayrıca süzülüyor.
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
    # --- söz kesme ---
    # HOPARLÖRDE VARSAYILAN OLARAK KAPALI.
    # Riley konuşurken mikrofon kendi sesini de duyar. Akustik yankı
    # bastırma olmadan "bu Riley'nin sesi mi, kullanıcının sesi mi"
    # sorusunu yalnızca ses seviyesine bakarak güvenilir biçimde
    # ayırt etmek mümkün değil: Riley kendi sesini araya giren biri
    # sanıp kendini kesiyor, sonra kendi sesini komut olarak işleyip
    # döngüye giriyor.
    #
    # Kulaklık kullanıyorsan mikrofon Riley'yi duymaz ve bu özellik
    # sorunsuz çalışır; ayarlardan ya da buradan açabilirsin.
    # Kapalıyken Esc, DUR düğmesi ve "dur" komutu her zaman çalışır.
    barge_in: bool = False
    barge_in_taban_ms: int = 1200      # konuşmanın ilk bu kadarı ölçüme ayrılır
    barge_in_kat: float = 3.5          # yankı tabanı kaç kat aşılırsa kesilir
    # Mutlak alt sınır: hoparlör yankısının bunun altında kalması beklenir.
    # Fazla düşük tutulursa Riley kendi sesiyle tetiklenir.
    barge_in_asgari: float = 0.030
    barge_in_ortam_kat: float = 8.0    # ölçülen ortam gürültüsünün kaç katı
    # Riley sustuktan sonra mikrofonun sağır kalacağı süre. Odadaki yankı
    # ve konuşmanın kuyruğu komut sanılmasın diye.
    konusma_sonrasi_sagirlik_ms: int = 450
    barge_in_cerceve: int = 6          # üst üste kaç çerçeve (yaklaşık 180 ms)
    # Riley cevabını bitirdikten sonra kaç saniye boyunca adı söylemeden
    # konuşmaya devam edilebilir
    follow_up_s: float = 8.0
    hotkey: str = "<ctrl>+<alt>+r"     # bas-konuş / uyandırma kısayolu


@dataclass
class AudioConfig:
    input_device: int | None = None    # None = sistem varsayılanı
    output_device: int | None = None
    sample_rate: int = 16000           # STT ve wake word bu hızda çalışır
    # Silero VAD 16 kHz'de 512 örneklik pencere ister; 32 ms tam denk gelir.
    block_ms: int = 32


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


# settings.json bütün ayarları kaydettiği için, bir varsayılanı sonradan
# iyileştirdiğimizde eski dosya onu maskeliyor. Sürüm numarası artınca
# GECISLER'de sayılan alanlar diskten değil koddan alınır.
AYAR_SURUMU = 4

GECISLER: dict[int, list[str]] = {
    # Söz kesme eşikleri fazla hassastı: Riley kendi sesini araya giren
    # biri sanıp kendini kesiyor, sonra kendi cevabını komut olarak işleyip
    # döngüye giriyordu. Bu alanlar yeni varsayılanlara döndürülür.
    2: [
        "wake.barge_in",
        "wake.barge_in_taban_ms",
        "wake.barge_in_kat",
        "wake.barge_in_asgari",
        "wake.barge_in_cerceve",
    ],
    # Konuşma sonu eşikleri gecikme uğruna fazla kısaltılmıştı ve cümle
    # ortasındaki duraklamalarda kullanıcının sözü kesiliyordu.
    3: [
        "stt.silence_ms",
        "stt.kisa_sessizlik_ms",
        "stt.uzun_soylem_ms",
    ],
    # Ses tanıma modeli turbo'ya geçti (hataların yarısı), konuşma tespiti
    # Silero'ya geçti ve onun istediği pencere 32 ms.
    4: [
        "stt.model_size",
        "audio.block_ms",
    ],
}


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
    ayar_surumu: int = AYAR_SURUMU

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        self.ayar_surumu = AYAR_SURUMU
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


def _eski_alanlari_ayikla(data: dict) -> list[str]:
    """Kaydedilmiş ayarlardan, artık koddaki değeri geçerli olanları siler."""
    kayitli_surum = int(data.get("ayar_surumu", 1))
    if kayitli_surum >= AYAR_SURUMU:
        return []

    silinen = []
    for surum in range(kayitli_surum + 1, AYAR_SURUMU + 1):
        for yol in GECISLER.get(surum, []):
            bolum, _, alan = yol.partition(".")
            if isinstance(data.get(bolum), dict) and alan in data[bolum]:
                data[bolum].pop(alan)
                silinen.append(yol)
    return silinen


def load() -> Config:
    cfg = Config()
    if USER_SETTINGS.exists():
        try:
            kayitli = json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
            silinen = _eski_alanlari_ayikla(kayitli)
            _merge(cfg, kayitli)
            if silinen:
                cfg.save()      # sürümü yükselt, bir daha uygulanmasın
                print(
                    "[config] güvenli varsayılanlara döndürülen ayarlar: "
                    + ", ".join(silinen)
                )
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
