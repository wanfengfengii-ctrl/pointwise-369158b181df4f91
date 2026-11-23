from collections.abc import Sequence


class InvalidBatch(ValueError):
    pass


def validate_batch_input(batch_id, multiplier, readings):
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise InvalidBatch('batch ID must be a nonblank string')
    try:
        batch_id.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise InvalidBatch('invalid batch ID text') from exc
    if type(multiplier) is not int:
        raise InvalidBatch('multiplier must be an integer')
    if not isinstance(readings, Sequence) or isinstance(
        readings, (str, bytes, bytearray, memoryview)
    ):
        raise InvalidBatch('readings must be an ordered sequence')
    raw = tuple(readings)
    for ordinal, reading in enumerate(raw):
        if reading is not None and type(reading) is not int:
            raise InvalidBatch(f'invalid reading at ordinal {ordinal}')
    return raw
