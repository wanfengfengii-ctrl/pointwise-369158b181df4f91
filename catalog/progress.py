from dataclasses import dataclass

from catalog.locations import ArchiveLocation, LocationStore
from transfer.attempts import AttemptStore
from transfer.jobs import load_job


@dataclass(frozen=True)
class CatalogProgress:
    job_id: int
    total_rows: int
    confirmed_count: int | None
    locations: tuple[ArchiveLocation, ...]

    @classmethod
    def unconfirmed(cls, job_id, total_rows):
        return cls(job_id, total_rows, None, ())


def read_progress(db, manifest):
    job_id = manifest.job_id
    total = len(manifest.rows)
    if AttemptStore(db).pending_for_job(job_id) is not None:
        return CatalogProgress.unconfirmed(job_id, total)
    locations = LocationStore(db).for_job(job_id)
    if len(locations) > total or any(
        location.ordinal != ordinal or manifest.rows[ordinal].ordinal != ordinal
        for ordinal, location in enumerate(locations)
    ):
        return CatalogProgress.unconfirmed(job_id, total)
    return CatalogProgress(job_id, total, len(locations), locations)


def progress(workspace, job_id):
    with workspace.center() as db:
        return read_progress(db, load_job(db, job_id))
