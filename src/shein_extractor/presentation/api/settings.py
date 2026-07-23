from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiSettings:
    api_key: str
    output_directory: Path = Path("outputs")
    export_directory: Path = Path("exports")
    image_max_attempts: int = 10
    image_timeout_seconds: float = 15
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> ApiSettings:
        return cls(
            api_key=os.getenv("SHEIN_API_KEY", "").strip(),
            output_directory=Path(os.getenv("SHEIN_OUTPUT_DIR", "outputs")),
            export_directory=Path(os.getenv("SHEIN_EXPORT_DIR", "exports")),
            image_max_attempts=_positive_int("SHEIN_IMAGE_MAX_ATTEMPTS", 10),
            image_timeout_seconds=_positive_float(
                "SHEIN_IMAGE_TIMEOUT_SECONDS",
                15,
            ),
            host=os.getenv("SHEIN_API_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_positive_int("SHEIN_API_PORT", 8000),
        )


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = float(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value
