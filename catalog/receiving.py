from catalog.locations import ArchiveLocation, LocationStore, RedundantSlotStore
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


def actual_locations(
    manifest: JobManifest, attempt: TransferAttempt, records: tuple[MediumRow, ...], capacity: int
):
    """Verify medium records against the fixed manifest and the registered attempt."""
    return _actual_locations(manifest, attempt, records, capacity)


def confirm_written(workspace, manifest, attempt, records):
    with workspace.center(write=True) as db:
        attempts = AttemptStore(db)
        if attempt not in attempts.pending_for_job_all(manifest.job_id):
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


def settle_attempt(workspace, manifest, attempt):
    """Settle one registered attempt from the physical evidence on its volume.

    The first confirmed read evidence fixes each ordinal's official location;
    a later verified slot for an already-located ordinal is only a redundant
    physical write. All of the volume's verified slots, the newly gained
    official locations and the attempt settlement commit together, so a
    failure keeps the pending state and every earlier confirmation.
    """
    records = read_attempt_rows(workspace, attempt)
    with workspace.center(write=True) as db:
        attempts = AttemptStore(db)
        if attempt not in attempts.pending_for_job_all(manifest.job_id):
            raise EvidenceUnavailable('attempt is not pending for this job')
        volume = VolumeRegistry(db).find(attempt.volume_id)
        if volume is None or volume.state != 'mounted':
            raise EvidenceUnavailable('pending volume is unavailable')
        locations = _actual_locations(manifest, attempt, records, volume.capacity)
        store = LocationStore(db)
        redundant = RedundantSlotStore(db)
        official = {location.ordinal for location in store.for_job(manifest.job_id)}
        for location in locations:
            if location.ordinal in official:
                redundant.record(location)
            else:
                store.record_actual(location)
                official.add(location.ordinal)
        attempts.settle(attempt)
