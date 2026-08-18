from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .config import AnalysisConfig
from .roi import RoiDefinition


@dataclass(frozen=True)
class AnalysisProfile:
    """Validated analysis calibration attached to one experiment."""

    schema_version: int
    config: AnalysisConfig
    roi: RoiDefinition

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported analysis profile version.")
        if self.roi.config_fingerprint != self.config.fingerprint:
            raise ValueError(
                "The ROI grid was detected with different analysis settings."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config": self.config.to_dict(),
            "roi": self.roi.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnalysisProfile:
        try:
            return cls(
                schema_version=int(value["schema_version"]),
                config=AnalysisConfig.from_dict(value["config"]),
                roi=RoiDefinition.from_dict(value["roi"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Analysis profile is invalid.") from exc

    def save(self, path: Path) -> None:
        from scripts.scheduling.make_schedule import atomic_write_text

        atomic_write_text(
            path, json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        )

    @classmethod
    def load(cls, path: Path) -> AnalysisProfile:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Analysis profile could not be read.") from exc
        if not isinstance(value, dict):
            raise ValueError("Analysis profile must be a JSON object.")
        return cls.from_dict(value)
