from catalog.locations import ArchiveLocation, LocationStore
from catalog.volumes import VolumeRegistry
from media.reader import read_attempt_rows
from media.records import MediumRow
from transfer.attempts import AttemptStore, TransferAttempt
from transfer.manifest import JobManifest
from workspace import EvidenceUnavailable


def _actual_locations(
    manifest: JobManifest, attempt: TransferAttempt, records: tuple[MediumRow, ...], capacity: int
):
    if (attempt.job_id != manifest.job_id or not 0 <= attempt.start < attempt.stop <= len(manifest.rows)
        or len(records) > attempt.stop - attempt.start):
        raise EvidenceUnavailable('invalid attempt range or recorded length')

    locations = []
    for ordinal, record in enumerate(records, start=attempt.start):
        row = manifest.rows[ordinal]
        if (record.attempt_id != attempt.attempt_id or record.job_id != manifest.job_id
            or record.ordinal != ordinal or row.ordinal != ordinal
            or record.raw != row.raw or record.calibrated != row.calibrated):
            raise EvidenceUnavailable('physical record differs from fixed manifest and attempt')
        expected_slot = records[0].slot + ordinal - attempt.start
        if record.slot != expected_slot or not 0 <= record.slot < capacity:
            raise EvidenceUnavailable('attempt occupies invalid physical slots')
        locations.append(
            ArchiveLocation(record.job_id, ordinal, attempt.volume_id, record.slot, attempt.attempt_id)
        )
    return locations


def confirm_written(workspace, manifest, attempt, records):
    with workspace.center(write=True) as db:
        attempts = AttemptStore(db)
        if attempts.pending_for_job(manifest.job_id) != attempt:
            raise EvidenceUnavailable('attempt is not the pending operation for this job')
        volume = VolumeRegistry(db).find(attempt.volume_id)
        if volume is None or volume.state != 'mounted':
            raise EvidenceUnavailable('pending volume is unavailable')
        locations = LocationStore(db)
        before = locations.for_job(manifest.job_id)
        if len(before) != attempt.start or any(
            location.ordinal != ordinal for ordinal, location in enumerate(before)
        ):
            raise EvidenceUnavailable('attempt does not follow the confirmed prefix')
        for location in _actual_locations(manifest, attempt, records, volume.capacity):
            locations.record_actual(location)
        attempts.settle(attempt)


def recover_pending(workspace, manifest, attempt):
    records = read_attempt_rows(workspace, attempt)
    confirm_written(workspace, manifest, attempt, records)
