from dataclasses import dataclass

from workspace import EvidenceUnavailable


@dataclass(frozen=True)
class TransferAttempt:
    attempt_id: int
    job_id: int
    volume_id: str
    start: int
    stop: int


class AttemptStore:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS transfer_attempts (
                attempt_id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(job_id),
                volume_id TEXT NOT NULL REFERENCES volume_registry(volume_id),
                start_ordinal INTEGER NOT NULL CHECK (start_ordinal >= 0),
                stop_ordinal INTEGER NOT NULL CHECK (stop_ordinal > start_ordinal),
                pending INTEGER NOT NULL DEFAULT 1 CHECK (pending IN (0, 1))
            )
        ''')
        # A bypass pair keeps one pending attempt per (job, volume); older
        # workspaces carried a single pending attempt per job.
        self.db.execute('DROP INDEX IF EXISTS one_pending_per_job')
        self.db.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS one_pending_attempt_per_volume
            ON transfer_attempts(job_id, volume_id) WHERE pending = 1
        ''')
        self.db.execute('''
            CREATE INDEX IF NOT EXISTS pending_attempts_by_volume
            ON transfer_attempts(volume_id) WHERE pending = 1
        ''')

    def begin(self, job_id, volume_id, start, stop):
        cursor = self.db.execute(
            '''INSERT INTO transfer_attempts (job_id, volume_id, start_ordinal, stop_ordinal)
               VALUES (?, ?, ?, ?)''',
            (job_id, volume_id, start, stop),
        )
        return TransferAttempt(cursor.lastrowid, job_id, volume_id, start, stop)

    def pending_for_job(self, job_id):
        row = self.db.execute(
            '''SELECT attempt_id, job_id, volume_id, start_ordinal, stop_ordinal
               FROM transfer_attempts WHERE pending = 1 AND job_id = ?''',
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return TransferAttempt(*row)

    def pending_for_job_all(self, job_id):
        rows = self.db.execute(
            '''SELECT attempt_id, job_id, volume_id, start_ordinal, stop_ordinal
               FROM transfer_attempts WHERE pending = 1 AND job_id = ? ORDER BY attempt_id''',
            (job_id,),
        )
        return tuple(TransferAttempt(*row) for row in rows)

    def find(self, attempt_id):
        row = self.db.execute(
            '''SELECT attempt_id, job_id, volume_id, start_ordinal, stop_ordinal, pending
               FROM transfer_attempts WHERE attempt_id = ?''',
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        *fields, pending = row
        return TransferAttempt(*fields), bool(pending)

    def pending_for_volume(self, volume_id):
        rows = self.db.execute(
            '''SELECT attempt_id, job_id, volume_id, start_ordinal, stop_ordinal
               FROM transfer_attempts WHERE pending = 1 AND volume_id = ? ORDER BY attempt_id''',
            (volume_id,),
        )
        return tuple(TransferAttempt(*row) for row in rows)

    def settle(self, attempt):
        changed = self.db.execute(
            'UPDATE transfer_attempts SET pending = 0 WHERE attempt_id = ? AND pending = 1',
            (attempt.attempt_id,),
        ).rowcount
        if changed != 1:
            raise EvidenceUnavailable('attempt no longer pending')
