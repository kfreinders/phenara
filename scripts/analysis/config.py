from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, ClassVar


@dataclass(frozen=True)
class AnalysisConfig:
    """Validated, serializable parameters for one analysis run."""

    SCHEMA_VERSION: ClassVar[int] = 1

    rotate_angle: float = 0.0
    sepchannel: str = "a"
    threshold: int = 145
    fill_size: int = 200
    margin_x: int = 200
    margin_y: int = 200
    frame_source: str = "pot-grid"
    pot_frame_padding_x: int = 0
    pot_frame_padding_y: int = 0
    grid_x: int | None = None
    grid_y: int | None = None
    grid_width: int | None = None
    grid_height: int | None = None
    roi_rows: int = 5
    roi_cols: int = 9
    roi_diameter_scale: float = 1.0
    grid_margin_x: int = 0
    grid_margin_y: int = 0
    grid_cell_padding_x: int = 0
    grid_cell_padding_y: int = 0
    min_component_area: int = 50
    pot_diameter_cm: float = 5.0
    pot_diameter_px: float = 250.0
    debug: str | None = None
    dpi: int = 300

    def __post_init__(self) -> None:
        if not math.isfinite(self.rotate_angle):
            raise ValueError("Rotation angle must be a finite number.")
        if self.sepchannel not in {"l", "a", "b"}:
            raise ValueError("LAB channel must be one of: l, a, b.")
        if not 0 <= self.threshold <= 255:
            raise ValueError("Threshold must be between 0 and 255.")
        if self.frame_source not in {"pot-grid", "plant-mask"}:
            raise ValueError("Frame source must be 'pot-grid' or 'plant-mask'.")
        if self.debug not in {None, "print", "plot"}:
            raise ValueError("Debug mode must be 'print', 'plot', or null.")

        self._require_non_negative(
            "fill size",
            self.fill_size,
            "horizontal margin",
            self.margin_x,
            "vertical margin",
            self.margin_y,
            "horizontal pot-frame padding",
            self.pot_frame_padding_x,
            "vertical pot-frame padding",
            self.pot_frame_padding_y,
            "horizontal grid margin",
            self.grid_margin_x,
            "vertical grid margin",
            self.grid_margin_y,
            "horizontal grid-cell padding",
            self.grid_cell_padding_x,
            "vertical grid-cell padding",
            self.grid_cell_padding_y,
            "minimum component area",
            self.min_component_area,
        )
        self._require_positive(
            "ROI rows",
            self.roi_rows,
            "ROI columns",
            self.roi_cols,
            "pot diameter in centimetres",
            self.pot_diameter_cm,
            "pot diameter in pixels",
            self.pot_diameter_px,
            "DPI",
            self.dpi,
        )
        if self.roi_rows > 30 or self.roi_cols > 30:
            raise ValueError("ROI rows and columns cannot exceed 30.")
        if not math.isfinite(self.roi_diameter_scale):
            raise ValueError("ROI diameter scale must be finite.")
        if not 0.5 <= self.roi_diameter_scale <= 2.0:
            raise ValueError("ROI diameter scale must be between 0.5 and 2.0.")

        manual_bounds = (
            self.grid_x,
            self.grid_y,
            self.grid_width,
            self.grid_height,
        )
        if any(value is not None for value in manual_bounds):
            if any(value is None for value in manual_bounds):
                raise ValueError(
                    "Manual grid bounds require x, y, width, and height."
                )
            assert all(value is not None for value in manual_bounds)
            if self.grid_x < 0 or self.grid_y < 0:
                raise ValueError("Manual grid x and y must be non-negative.")
            if self.grid_width <= 0 or self.grid_height <= 0:
                raise ValueError(
                    "Manual grid width and height must be positive."
                )

    @staticmethod
    def _require_non_negative(*names_and_values: object) -> None:
        for name, value in zip(
            names_and_values[::2], names_and_values[1::2], strict=True
        ):
            if value < 0:  # type: ignore[operator]
                label = str(name)
                raise ValueError(
                    f"{label[:1].upper()}{label[1:]} must be non-negative."
                )

    @staticmethod
    def _require_positive(*names_and_values: object) -> None:
        for name, value in zip(
            names_and_values[::2], names_and_values[1::2], strict=True
        ):
            if value <= 0:  # type: ignore[operator]
                label = str(name)
                raise ValueError(
                    f"{label[:1].upper()}{label[1:]} must be positive."
                )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnalysisConfig:
        data = dict(value)
        version = data.pop("schema_version", cls.SCHEMA_VERSION)
        if version != cls.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported analysis configuration version: {version}."
            )

        known_fields = {field.name for field in fields(cls)}
        unknown = sorted(set(data) - known_fields)
        if unknown:
            raise ValueError(
                f"Unknown analysis configuration field(s): {', '.join(unknown)}."
            )
        try:
            return cls(**data)
        except TypeError as exc:
            raise ValueError(f"Invalid analysis configuration: {exc}") from exc

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, value: str) -> AnalysisConfig:
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Analysis configuration is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Analysis configuration must be a JSON object.")
        return cls.from_dict(data)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def save(self, path: Path) -> None:
        """Atomically persist this configuration."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path) -> AnalysisConfig:
        try:
            return cls.from_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(
                f"Analysis configuration could not be read: {path}"
            ) from exc
