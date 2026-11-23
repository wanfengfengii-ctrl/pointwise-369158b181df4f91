from dataclasses import dataclass

from intake.records import decode_reading, encode_reading
from workspace import EvidenceUnavailable


@dataclass(frozen=True)
class VolumeHeader:
    volume_id: str
    capacity: int


@dataclass(frozen=True)
class MediumRow:
    slot: int
    attempt_id: int
    job_id: int
    ordinal: int
    raw: int | None
    calibrated: int | None


class MediumStore:
    def __init__(self, db):
        self.db = db

    def initialize(self, header):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_header (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                volume_id TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK (capacity >= 0)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS medium_rows (
                slot INTEGER PRIMARY KEY CHECK (slot >= 0),
                attempt_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                raw TEXT,
                calibrated TEXT,
                CHECK ((raw IS NULL) = (calibrated IS NULL)),
                UNIQUE (job_id, ordinal)
            )
        ''')
        self.db.execute(
            '''INSERT INTO volume_header (singleton, volume_id, capacity) VALUES (1, ?, ?)
               ON CONFLICT (singleton) DO NOTHING''',
            (header.volume_id, header.capacity),
        )
        self.require_header(header)

    def read_header(self):
        row = self.db.execute(
            'SELECT volume_id, capacity FROM volume_header WHERE singleton = 1'
        ).fetchone()
        if row is None:
            raise EvidenceUnavailable('medium header missing')
        return VolumeHeader(*row)

    def require_header(self, expected):
        if self.read_header() != expected:
            raise EvidenceUnavailable('medium header differs from registration')

    def occupied_slots(self, capacity):
        count, last = self.db.execute(
            'SELECT COUNT(*), COALESCE(MAX(slot), -1) FROM medium_rows'
        ).fetchone()
        if count > capacity or last != count - 1:
            raise EvidenceUnavailable('invalid physical slot layout')
        return count

    def append_rows(self, rows):
        self.db.executemany(
            '''INSERT INTO medium_rows (slot, attempt_id, job_id, ordinal, raw, calibrated)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                (row.slot, row.attempt_id, row.job_id, row.ordinal,
                 encode_reading(row.raw), encode_reading(row.calibrated))
                for row in rows
            ),
        )

    def read_rows(self, attempt_id=None):
        query = 'SELECT slot, attempt_id, job_id, ordinal, raw, calibrated FROM medium_rows'
        args = ()
        if attempt_id is not None:
            query += ' WHERE attempt_id = ?'
            args = (attempt_id,)
        return tuple(
            MediumRow(slot, attempt, job, ordinal, decode_reading(raw), decode_reading(value))
            for slot, attempt, job, ordinal, raw, value in self.db.execute(query + ' ORDER BY slot', args)
        )
