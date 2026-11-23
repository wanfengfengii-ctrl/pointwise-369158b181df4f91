def calibrate_reading(raw: int | None, multiplier: int) -> int | None:
    if raw is None:
        return None
    return raw * multiplier
