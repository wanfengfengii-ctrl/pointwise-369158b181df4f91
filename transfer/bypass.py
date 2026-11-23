from dataclasses import dataclass


@dataclass(frozen=True)
class BypassBinding:
    job_id: int
    original_volume_id: str
    original_attempt_id: int
    bypass_volume_id: str
    bypass_attempt_id: int


class BypassRegistry:
    """Records the single bypass pairing each job may register."""

    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS bypass_registry (
                job_id INTEGER PRIMARY KEY REFERENCES jobs(job_id),
                original_volume_id TEXT NOT NULL REFERENCES volume_registry(volume_id),
                original_attempt_id INTEGER NOT NULL REFERENCES transfer_attempts(attempt_id),
                bypass_volume_id TEXT NOT NULL REFERENCES volume_registry(volume_id),
                bypass_attempt_id INTEGER NOT NULL REFERENCES transfer_attempts(attempt_id)
            )
        ''')

    def find(self, job_id):
        row = self.db.execute(
            '''SELECT job_id, original_volume_id, original_attempt_id,
                      bypass_volume_id, bypass_attempt_id
               FROM bypass_registry WHERE job_id = ?''',
            (job_id,),
        ).fetchone()
        return BypassBinding(*row) if row is not None else None

    def register(self, binding):
        self.db.execute(
            '''INSERT INTO bypass_registry
               (job_id, original_volume_id, original_attempt_id, bypass_volume_id, bypass_attempt_id)
               VALUES (?, ?, ?, ?, ?)''',
            (
                binding.job_id, binding.original_volume_id, binding.original_attempt_id,
                binding.bypass_volume_id, binding.bypass_attempt_id,
            ),
        )
        return binding
