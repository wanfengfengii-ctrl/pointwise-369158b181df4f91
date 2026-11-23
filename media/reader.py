import sqlite3

from catalog.volumes import VolumeRegistry
from media.capacity import validate_volume_id
from media.records import MediumStore, VolumeHeader
from workspace import EvidenceUnavailable


def _read_rows(workspace, volume_id, attempt_id):
    validate_volume_id(volume_id)
    with workspace.center() as db:
        volume = VolumeRegistry(db).find(volume_id)
    if (volume is None or volume.state != 'mounted'
        or volume.medium_file != workspace.volume_file(volume_id).name):
        raise EvidenceUnavailable(f'volume unavailable online: {volume_id}')
    try:
        with workspace.medium(volume_id) as db:
            medium = MediumStore(db)
            medium.require_header(VolumeHeader(volume_id, volume.capacity))
            medium.occupied_slots(volume.capacity)
            return medium.read_rows(attempt_id)
    except (sqlite3.Error, ValueError) as exc:
        raise EvidenceUnavailable(f'cannot read medium evidence: {volume_id}') from exc


def read_attempt_rows(workspace, attempt):
    return _read_rows(workspace, attempt.volume_id, attempt.attempt_id)


def read_mounted_rows(workspace, volume_id):
    return _read_rows(workspace, volume_id, None)
