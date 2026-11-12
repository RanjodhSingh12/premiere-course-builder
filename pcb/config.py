"""Settings, read from ~/.config/pcb/config.toml (see config.example.toml). Everything has a default."""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PCB_CONFIG", "~/.config/pcb/config.toml")).expanduser()


@dataclass
class Config:
    # where jobs (working files, outputs, queue) live; put it on a reliable disk
    work_dir: Path = Path("~/pcb-work").expanduser()
    # Premiere install
    premiere_app: str = "Adobe Premiere Pro 2027"
    premiere_bundle_id: str = "com.adobe.PremierePro.27"
    # Whisper (whisper.cpp) binary + model
    whisper_bin: str = "whisper-cli"
    whisper_model: Path = Path("~/pcb-work/models/ggml-base.en-q5_1.bin").expanduser()
    # H.264 export preset shipped with the repo
    export_preset: Path = REPO / "presets" / "H264 Match Source High.epr"
    # timing
    lead_seconds: float = 0.15          # a build starts this long before its words are spoken
    audio_gap_seconds: float = 0.3      # gap between consecutive voiceover files
    tail_seconds: float = 1.0           # hold after the last word
    # away-only queue: optional extra rule "idle for N minutes" (0 = off)
    idle_minutes: float = 0
    extra: dict = field(default_factory=dict)

    @property
    def queue_dir(self) -> Path:
        return self.work_dir / "queue"

    @property
    def jobs_dir(self) -> Path:
        return self.work_dir / "jobs"

    @property
    def bin_dir(self) -> Path:
        return REPO / "bin"


def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        data = tomllib.loads(CONFIG_PATH.read_text())
        for k, v in data.items():
            if hasattr(cfg, k) and k != "extra":
                cur = getattr(cfg, k)
                setattr(cfg, k, Path(v).expanduser() if isinstance(cur, Path) else type(cur)(v))
            else:
                cfg.extra[k] = v
    return cfg


CFG = load()
