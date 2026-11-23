from dataclasses import dataclass

from intake.calibration import calibrate_reading


@dataclass(frozen=True)
class IntakeRow:
    ordinal: int
    raw: int | None
    calibrated: int | None


def make_intake_rows(readings, multiplier):
    return tuple(
        IntakeRow(ordinal, raw, calibrate_reading(raw, multiplier))
        for ordinal, raw in enumerate(readings)
    )


def encode_reading(value: int | None) -> str | None:
    if value is None:
        return None
    return format(value, 'x')


def decode_reading(encoded: str | None) -> int | None:
    if encoded is None:
        return None
    return int(encoded, 16)
