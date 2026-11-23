from dataclasses import dataclass

from intake.storage import BatchSnapshot


@dataclass(frozen=True)
class ManifestRow:
    ordinal: int
    raw: int | None
    calibrated: int | None


@dataclass(frozen=True)
class JobManifest:
    job_id: int
    batch_id: str
    rows: tuple[ManifestRow, ...]


def freeze_manifest(job_id: int, batch: BatchSnapshot) -> JobManifest:
    rows = tuple(ManifestRow(row.ordinal, row.raw, row.calibrated) for row in batch.rows)
    return JobManifest(job_id, batch.batch_id, rows)


def remaining_rows(manifest, confirmed_count):
    if type(confirmed_count) is not int or not 0 <= confirmed_count <= len(manifest.rows):
        raise ValueError('invalid confirmed prefix')
    return manifest.rows[confirmed_count:]
