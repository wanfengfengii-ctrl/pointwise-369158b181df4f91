from dataclasses import dataclass

from intake.records import IntakeRow, decode_reading, encode_reading


@dataclass(frozen=True)
class BatchSnapshot:
    batch_id: str
    multiplier: int
    rows: tuple[IntakeRow, ...]


class BatchStore:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY NOT NULL,
                multiplier TEXT NOT NULL
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS intake_rows (
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                raw TEXT,
                calibrated TEXT,
                CHECK ((raw IS NULL) = (calibrated IS NULL)),
                PRIMARY KEY (batch_id, ordinal)
            )
        ''')

    def save(self, batch):
        self.db.execute(
            'INSERT INTO batches (batch_id, multiplier) VALUES (?, ?)',
            (batch.batch_id, encode_reading(batch.multiplier)),
        )
        self.db.executemany(
            '''INSERT INTO intake_rows (batch_id, ordinal, raw, calibrated)
               VALUES (?, ?, ?, ?)''',
            (
                (batch.batch_id, row.ordinal, encode_reading(row.raw), encode_reading(row.calibrated))
                for row in batch.rows
            ),
        )

    def load(self, batch_id):
        header = self.db.execute(
            'SELECT multiplier FROM batches WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        if header is None:
            return None
        rows = self.db.execute(
            '''SELECT ordinal, raw, calibrated FROM intake_rows
               WHERE batch_id = ? ORDER BY ordinal''',
            (batch_id,),
        )
        return BatchSnapshot(
            batch_id,
            decode_reading(header[0]),
            tuple(IntakeRow(n, decode_reading(raw), decode_reading(value)) for n, raw, value in rows),
        )
