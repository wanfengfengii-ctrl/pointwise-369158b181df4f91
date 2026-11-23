from dataclasses import dataclass

from catalog.progress import read_progress
from workspace import IncompleteJob


@dataclass(frozen=True)
class ReconciledLine:
    ordinal: int
    raw: int | None
    calibrated: int | None
    volume_id: str
    slot: int


def reconcile_job(db, manifest):
    confirmed = read_progress(db, manifest)
    if confirmed.confirmed_count != len(manifest.rows):
        raise IncompleteJob(f'job {manifest.job_id} has incomplete or unconfirmed evidence')

    lines = []
    seen = set()
    for ordinal, (row, location) in enumerate(zip(manifest.rows, confirmed.locations, strict=True)):
        position = (location.volume_id, location.slot)
        if (row.ordinal != ordinal or location.ordinal != ordinal
            or location.job_id != manifest.job_id or position in seen):
            raise IncompleteJob(f'job {manifest.job_id} has inconsistent archive locations')
        seen.add(position)
        lines.append(ReconciledLine(ordinal, row.raw, row.calibrated, *position))
    return tuple(lines)
