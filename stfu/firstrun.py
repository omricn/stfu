"""First-run setup: every question the app needs, asked once.

The flow is a pure state machine so the wizard's rules -- what order, what may
be skipped, when setup is finished -- are testable without opening a window.
The Tk screens are a thin rendering of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stfu.config import Config, hash_pin

STEPS = (
    "welcome",
    "device",
    "calibrate",
    "test",
    "pin",
    "sounds",
    "autostart",
)

# Steps that cannot be left until they have produced something.
REQUIRED = {
    "device": ("device_name",),
    "calibrate": ("spike_threshold_dbfs",),
    "pin": ("pin",),
}


def needs_setup(config: Config) -> bool:
    """True when the app has not been through setup.

    A pinned device and a PIN are the two things nothing else can supply. A
    missing threshold is survivable -- there is a default -- but a missing
    device means there is nothing to listen to.
    """
    return not config.device_name or not config.pin_hash


@dataclass
class FirstRunFlow:
    index: int = 0
    answers: dict[str, Any] = field(default_factory=dict)

    @property
    def current(self) -> str:
        return STEPS[min(self.index, len(STEPS) - 1)]

    @property
    def is_complete(self) -> bool:
        return self.index >= len(STEPS)

    def goto(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown setup step: {step!r}")
        self.index = STEPS.index(step)

    def record(self, **answers: Any) -> None:
        self.answers.update(answers)

    def can_advance(self) -> bool:
        for key in REQUIRED.get(self.current, ()):
            # Presence, not truthiness. spike_threshold_dbfs is a float that can
            # legitimately be 0.0 -- a yell loud enough to clip the mic clamps
            # there -- and 0.0 is falsy, which would strand the user on the
            # calibrate step with a correct threshold and a dead Next button.
            value = self.answers.get(key)
            if value is None or value == "":
                return False
        return True

    def advance(self) -> bool:
        """Move to the next step. False once there are none left."""
        if self.index >= len(STEPS) - 1:
            self.index = len(STEPS)
            return False
        self.index += 1
        return True

    def back(self) -> bool:
        if self.index == 0:
            return False
        self.index -= 1
        return True

    def to_config(self, base: Config) -> Config:
        """Fold the answers into a Config. The PIN is hashed, never stored."""
        config = base
        for key in (
            "device_name",
            "device_hostapi",
            "spike_threshold_dbfs",
            "sustain_threshold_dbfs",
            "autostart",
        ):
            if key in self.answers:
                setattr(config, key, self.answers[key])

        if self.answers.get("pin"):
            config.pin_hash, config.pin_salt = hash_pin(self.answers["pin"])

        config.threshold_mode = "wizard"
        return config
