import sqlite3

from catalog.locations import ArchiveLocation, LocationStore
from catalog.volumes import VolumeRegistry
from media.capacity import validate_volume_id
from media.reader import read_mounted_rows
from transfer.attempts import AttemptStore
from workspace import EvidenceUnavailable, InvalidVolume


def retire(workspace, volume_id):
    validate_volume_id(volume_id)
    with workspace.operation():
        try:
            with workspace.center() as db:
                volume = VolumeRegistry(db).find(volume_id)
                if volume is None:
                    raise InvalidVolume(f'unknown volume: {volume_id}')
                if volume.state == 'retired':
                    return True
                if AttemptStore(db).pending_for_volume(volume_id):
                    return False
                expected = LocationStore(db).for_volume(volume_id)

            rows = read_mounted_rows(workspace, volume_id)
            actual = tuple(
                ArchiveLocation(row.job_id, row.ordinal, volume_id, row.slot, row.attempt_id)
                for row in rows
            )
            if actual != expected:
                return False
            with workspace.center(write=True) as db:
                VolumeRegistry(db).mark_retired(volume_id)
        except (EvidenceUnavailable, sqlite3.Error):
            return False
    return True
