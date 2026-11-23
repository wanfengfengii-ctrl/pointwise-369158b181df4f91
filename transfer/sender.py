import sqlite3

from catalog.progress import CatalogProgress, progress, read_progress
from catalog.receiving import confirm_written, recover_pending
from catalog.volumes import VolumeRegistry
from media.capacity import validate_volume_id
from media.writer import write_prefix
from transfer.attempts import AttemptStore
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
            pending = AttemptStore(db).pending_for_job(job_id)

        try:
            if pending is not None:
                recover_pending(workspace, manifest, pending)

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
