from dataclasses import dataclass

from workspace import EvidenceUnavailable


@dataclass(frozen=True)
class ArchiveLocation:
    job_id: int
    ordinal: int
    volume_id: str
    slot: int
    attempt_id: int


class LocationStore:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS archive_locations (
                job_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                volume_id TEXT NOT NULL REFERENCES volume_registry(volume_id),
                slot INTEGER NOT NULL CHECK (slot >= 0),
                attempt_id INTEGER NOT NULL REFERENCES transfer_attempts(attempt_id),
                FOREIGN KEY (job_id, ordinal) REFERENCES manifest_rows(job_id, ordinal),
                PRIMARY KEY (job_id, ordinal),
                UNIQUE (volume_id, slot)
            )
        ''')

    def record_actual(self, location):
        self.db.execute(
            '''INSERT INTO archive_locations (job_id, ordinal, volume_id, slot, attempt_id)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(job_id, ordinal) DO NOTHING''',
            (location.job_id, location.ordinal, location.volume_id, location.slot, location.attempt_id),
        )
        saved = self.db.execute(
            '''SELECT volume_id, slot, attempt_id FROM archive_locations
               WHERE job_id = ? AND ordinal = ?''',
            (location.job_id, location.ordinal),
        ).fetchone()
        if saved != (location.volume_id, location.slot, location.attempt_id):
            raise EvidenceUnavailable('conflicting physical location for original row')

    def for_job(self, job_id):
        rows = self.db.execute(
            '''SELECT job_id, ordinal, volume_id, slot, attempt_id FROM archive_locations
               WHERE job_id = ? ORDER BY ordinal''',
            (job_id,),
        )
        return tuple(ArchiveLocation(*row) for row in rows)

    def for_volume(self, volume_id):
        rows = self.db.execute(
            '''SELECT job_id, ordinal, volume_id, slot, attempt_id FROM archive_locations
               WHERE volume_id = ? ORDER BY slot''',
            (volume_id,),
        )
        return tuple(ArchiveLocation(*row) for row in rows)
