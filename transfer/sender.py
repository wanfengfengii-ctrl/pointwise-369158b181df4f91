import sqlite3

from catalog.locations import LocationStore
from catalog.progress import CatalogProgress, progress, read_progress
from catalog.receiving import actual_locations, confirm_written, recover_pending, settle_attempt
from catalog.volumes import VolumeRegistry
from media.capacity import validate_volume_id
from media.reader import read_attempt_rows
from media.writer import write_prefix
from transfer.attempts import AttemptStore, TransferAttempt
from transfer.bypass import BypassBinding, BypassRegistry
from transfer.jobs import load_job
from transfer.manifest import remaining_rows
from transfer.progress import resume_offset, shipping_result
from workspace import EvidenceUnavailable


def ship(workspace, job_id, volume_id):
    validate_volume_id(volume_id)
    with workspace.operation():
        with workspace.center() as db:
            manifest = load_job(db, job_id)
            volume = VolumeRegistry(db).require_mounted(volume_id)
            pending = AttemptStore(db).pending_for_job_all(job_id)
            paired = BypassRegistry(db).find(job_id) is not None

        try:
            if paired:
                # A bypass pair settles through its two registered attempts; no
                # third shipment opens until both are settled.
                for attempt in pending:
                    settle_attempt(workspace, manifest, attempt)
            elif pending:
                recover_pending(workspace, manifest, pending[0])

            with workspace.center(write=True) as db:
                before = read_progress(db, manifest)
                start = resume_offset(before)
                rows = remaining_rows(manifest, start)
                if not rows:
                    return shipping_result(before)
                attempt = AttemptStore(db).begin(job_id, volume_id, start, len(manifest.rows))

            committed = write_prefix(workspace, volume, attempt, rows)
            confirm_written(workspace, manifest, attempt, committed)
            return shipping_result(progress(workspace, job_id))
        except (EvidenceUnavailable, sqlite3.Error):
            return shipping_result(CatalogProgress.unconfirmed(job_id, len(manifest.rows)))


def ship_bypass(workspace, job_id, volume_id):
    """Ship the unconfirmed tail to another mounted volume while the original is away."""
    validate_volume_id(volume_id)
    with workspace.operation():
        with workspace.center() as db:
            manifest = load_job(db, job_id)
            attempts = AttemptStore(db)
            binding = BypassRegistry(db).find(job_id)
            original = None
            if binding is None:
                volume = VolumeRegistry(db).require_mounted(volume_id)
                pending = attempts.pending_for_job_all(job_id)
                if len(pending) != 1:
                    raise ValueError('bypass requires exactly one pending original volume')
                original = pending[0]
                if volume_id == original.volume_id:
                    raise ValueError('bypass volume must differ from the pending original volume')
            else:
                if volume_id != binding.bypass_volume_id:
                    raise ValueError('job is already bound to another bypass volume')
                found = attempts.find(binding.bypass_attempt_id)
                if found is None:
                    raise ValueError('bypass binding refers to an unknown attempt')
                attempt, is_pending = found
                if not is_pending:
                    return shipping_result(progress(workspace, job_id))
                volume = VolumeRegistry(db).require_mounted(volume_id)

        if binding is None:
            try:
                read_attempt_rows(workspace, original)
            except EvidenceUnavailable:
                pass
            else:
                raise ValueError('original volume is still readable; bypass is not allowed')
            try:
                with workspace.center(write=True) as db:
                    confirmed = LocationStore(db).for_job(job_id)
                    if any(location.ordinal != ordinal for ordinal, location in enumerate(confirmed)):
                        raise EvidenceUnavailable('confirmed prefix is inconsistent')
                    attempt = AttemptStore(db).begin(
                        job_id, volume_id, len(confirmed), len(manifest.rows))
                    binding = BypassRegistry(db).register(BypassBinding(
                        job_id, original.volume_id, original.attempt_id,
                        volume_id, attempt.attempt_id))
            except (EvidenceUnavailable, sqlite3.Error):
                return shipping_result(CatalogProgress.unconfirmed(job_id, len(manifest.rows)))

        try:
            # Resume the registered attempt: rows already written keep their
            # slots, the tail appends after them under the same attempt.
            existing = read_attempt_rows(workspace, attempt)
            actual_locations(manifest, attempt, existing, volume.capacity)
            written = len(existing)
            if attempt.start + written < attempt.stop:
                tail = TransferAttempt(
                    attempt.attempt_id, attempt.job_id, attempt.volume_id,
                    attempt.start + written, attempt.stop)
                rows = remaining_rows(manifest, attempt.start + written)
                rows = rows[:attempt.stop - attempt.start - written]
                if rows:
                    write_prefix(workspace, volume, tail, rows)
            settle_attempt(workspace, manifest, attempt)
            return shipping_result(progress(workspace, job_id))
        except (EvidenceUnavailable, sqlite3.Error):
            return shipping_result(CatalogProgress.unconfirmed(job_id, len(manifest.rows)))


def settle_volume(workspace, job_id, volume_id):
    """Settle the registered attempt for one volume of a job's bypass pair."""
    validate_volume_id(volume_id)
    with workspace.operation():
        with workspace.center() as db:
            manifest = load_job(db, job_id)
            binding = BypassRegistry(db).find(job_id)
            if binding is None or volume_id not in (
                binding.original_volume_id, binding.bypass_volume_id
            ):
                raise ValueError('volume is not part of this job\'s bypass pair')
            attempt_id = (
                binding.original_attempt_id if volume_id == binding.original_volume_id
                else binding.bypass_attempt_id
            )
            found = AttemptStore(db).find(attempt_id)
        if found is None:
            raise ValueError('bypass pair refers to an unknown attempt')
        attempt, is_pending = found
        if not is_pending:
            # An already settled attempt may be rechecked by its binding even
            # after the volume itself has retired.
            return True
        try:
            settle_attempt(workspace, manifest, attempt)
        except (EvidenceUnavailable, sqlite3.Error):
            return False
        return True
