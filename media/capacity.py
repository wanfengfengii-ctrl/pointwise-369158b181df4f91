import re

from workspace import InvalidVolume


_VOLUME_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', re.ASCII)
_MAX_CAPACITY = (1 << 63) - 1


def validate_volume_id(volume_id):
    if not isinstance(volume_id, str) or _VOLUME_ID.fullmatch(volume_id) is None:
        raise InvalidVolume('invalid volume ID')


def validate_capacity(capacity):
    if type(capacity) is not int or not 0 <= capacity <= _MAX_CAPACITY:
        raise InvalidVolume('capacity outside supported integer range')
    return capacity


def remaining_slots(capacity, occupied):
    if not 0 <= occupied <= capacity:
        raise ValueError('physical occupancy exceeds capacity')
    return capacity - occupied


def accepted_prefix_length(capacity, occupied, requested):
    return min(remaining_slots(capacity, occupied), requested)
