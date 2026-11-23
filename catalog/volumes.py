from dataclasses import dataclass

from workspace import EvidenceUnavailable, InvalidVolume


@dataclass(frozen=True)
class VolumeRegistration:
    volume_id: str
    capacity: int
    medium_file: str
    state: str


class VolumeRegistry:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_registry (
                volume_id TEXT PRIMARY KEY NOT NULL,
                capacity INTEGER NOT NULL CHECK (capacity >= 0),
                medium_file TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL CHECK (state IN ('mounted', 'retired'))
            )
        ''')

    def find(self, volume_id):
        row = self.db.execute(
            '''SELECT volume_id, capacity, medium_file, state
               FROM volume_registry WHERE volume_id = ?''',
            (volume_id,),
        ).fetchone()
        return VolumeRegistration(*row) if row is not None else None

    def require_mounted(self, volume_id):
        entry = self.find(volume_id)
        if entry is None or entry.state != 'mounted':
            raise InvalidVolume(f'volume is not writable: {volume_id}')
        return entry

    def register_mounted(self, volume_id, capacity, medium_file):
        self.db.execute(
            '''INSERT INTO volume_registry (volume_id, capacity, medium_file, state)
               VALUES (?, ?, ?, 'mounted')''',
            (volume_id, capacity, medium_file),
        )
        return VolumeRegistration(volume_id, capacity, medium_file, 'mounted')

    def mark_retired(self, volume_id):
        changed = self.db.execute(
            "UPDATE volume_registry SET state = 'retired' WHERE volume_id = ? AND state = 'mounted'",
            (volume_id,),
        ).rowcount
        if changed != 1:
            raise EvidenceUnavailable('volume registration changed during retirement')
