from catalog.volumes import VolumeRegistration
from media.capacity import accepted_prefix_length
from media.records import MediumRow, MediumStore, VolumeHeader
from transfer.attempts import TransferAttempt
from transfer.manifest import ManifestRow
from workspace import EvidenceUnavailable


def write_prefix(
    workspace, volume: VolumeRegistration, attempt: TransferAttempt, rows: tuple[ManifestRow, ...]
):
    if (volume.state != 'mounted' or volume.volume_id != attempt.volume_id
        or volume.medium_file != workspace.volume_file(volume.volume_id).name):
        raise EvidenceUnavailable('write target differs from pending attempt')
    if len(rows) != attempt.stop - attempt.start or any(
        row.ordinal != ordinal for ordinal, row in enumerate(rows, start=attempt.start)
    ):
        raise EvidenceUnavailable('write rows differ from pending range')

    with workspace.medium(volume.volume_id, write=True) as db:
        store = MediumStore(db)
        store.require_header(VolumeHeader(volume.volume_id, volume.capacity))
        occupied = store.occupied_slots(volume.capacity)
        count = accepted_prefix_length(volume.capacity, occupied, len(rows))
        committed = tuple(
            MediumRow(slot, attempt.attempt_id, attempt.job_id, row.ordinal, row.raw, row.calibrated)
            for slot, row in enumerate(rows[:count], start=occupied)
        )
        store.append_rows(committed)
    return committed
