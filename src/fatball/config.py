import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / "Library/Application Support/WhoAteTheFatBall"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    camera_port: int = 34567
    poll_interval_s: float = 5.0
    catchup_days: int = 7
    clock_tolerance_s: int = 120
    wrong_password_backoff_s: int = 600
    min_free_bytes: int = 2_000_000_000

    @classmethod
    def load(cls) -> "Settings":
        env = os.environ.get("FATBALL_DATA_DIR")
        return cls(data_dir=Path(env) if env else DEFAULT_DATA_DIR)

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.sqlite"
