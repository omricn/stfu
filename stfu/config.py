"""Persistent settings, stored as JSON under %LOCALAPPDATA%\\STFU."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass, fields
from pathlib import Path

THRESHOLD_MODES = ("wizard", "manual", "adaptive")
SESSION_RESET_MODES = ("session", "rolling_60m", "nightly")

SAMPLE_RATE = 16_000
FRAME_MS = 20

_PBKDF2_ROUNDS = 200_000


@dataclass
class Config:
    # Pinned capture device: name plus host API, matched on startup.
    device_name: str = ""
    device_hostapi: str = ""

    # Detection
    threshold_mode: str = "wizard"
    spike_threshold_dbfs: float = -12.0
    spike_window_ms: int = 150
    sustain_enabled: bool = False
    sustain_threshold_dbfs: float = -24.0
    sustain_window_ms: int = 3000
    cooldown_seconds: int = 30

    # Adaptive mode
    adaptive_delta_db: float = 18.0
    adaptive_min_threshold_dbfs: float = -20.0
    adaptive_max_threshold_dbfs: float = -6.0
    adaptive_baseline_minutes: int = 10

    # Strike ladder
    session_reset_mode: str = "session"
    rolling_reset_minutes: int = 60
    nightly_reset_hour: int = 4

    # Actions (consumed by Plan 2, stored here so settings stay in one place)
    overlay_clicks_required: int = 4
    desktop_message_seconds: int = 10
    sound_enabled: bool = True
    popups_enabled: bool = True
    sound_gain: float = 1.0
    max_clip_seconds: int = 15

    # Control
    pin_hash: str = ""
    pin_salt: str = ""
    autostart: bool = True


def data_dir() -> Path:
    """%LOCALAPPDATA%\\STFU, created if absent."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / "STFU"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def _coerce(cfg: Config) -> Config:
    """Replace nonsensical values with defaults. A bad config must never
    silently disable detection."""
    default = Config()
    if cfg.threshold_mode not in THRESHOLD_MODES:
        cfg.threshold_mode = default.threshold_mode
    if cfg.session_reset_mode not in SESSION_RESET_MODES:
        cfg.session_reset_mode = default.session_reset_mode
    if cfg.cooldown_seconds < 5 or cfg.cooldown_seconds > 300:
        cfg.cooldown_seconds = default.cooldown_seconds
    if cfg.spike_window_ms < FRAME_MS:
        cfg.spike_window_ms = default.spike_window_ms
    if cfg.sustain_window_ms < FRAME_MS:
        cfg.sustain_window_ms = default.sustain_window_ms
    if cfg.overlay_clicks_required < 1:
        cfg.overlay_clicks_required = default.overlay_clicks_required
    if cfg.desktop_message_seconds < 1:
        cfg.desktop_message_seconds = default.desktop_message_seconds
    if cfg.max_clip_seconds < 1 or cfg.max_clip_seconds > 120:
        cfg.max_clip_seconds = default.max_clip_seconds
    if not 0.0 < cfg.sound_gain <= 4.0:
        cfg.sound_gain = default.sound_gain
    if not 0 <= cfg.nightly_reset_hour <= 23:
        cfg.nightly_reset_hour = default.nightly_reset_hour
    if cfg.adaptive_min_threshold_dbfs > cfg.adaptive_max_threshold_dbfs:
        cfg.adaptive_min_threshold_dbfs = default.adaptive_min_threshold_dbfs
        cfg.adaptive_max_threshold_dbfs = default.adaptive_max_threshold_dbfs
    return cfg


def load_config(path: Path | None = None) -> Config:
    """Load config, tolerating absent, corrupt, older, and newer files."""
    path = Path(path) if path is not None else config_path()
    if not path.exists():
        return Config()

    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("config root is not an object")
    except (json.JSONDecodeError, ValueError):
        path.with_suffix(".json.bad").write_text(raw, encoding="utf-8")
        return Config()

    known = {f.name for f in fields(Config)}
    return _coerce(Config(**{k: v for k, v in data.items() if k in known}))


def save_config(cfg: Config, path: Path | None = None) -> None:
    """Write atomically so a crash mid-write cannot corrupt the config."""
    path = Path(path) if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def hash_pin(pin: str) -> tuple[str, str]:
    """Return (hash_hex, salt_hex) for a PIN."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return digest.hex(), salt.hex()


def verify_pin(pin: str, pin_hash: str, pin_salt: str) -> bool:
    """Constant-time PIN check. Returns False when no PIN has been set."""
    if not pin_hash or not pin_salt:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), bytes.fromhex(pin_salt), _PBKDF2_ROUNDS
    )
    return hmac.compare_digest(digest.hex(), pin_hash)
