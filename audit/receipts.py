from dataclasses import dataclass

from audit.reconcile import ReconciledLine
from intake.records import decode_reading, encode_reading


@dataclass(frozen=True)
class Receipt:
    receipt_id: int
    job_id: int
    batch_id: str
    row_count: int
    total: int
    lines: tuple[ReconciledLine, ...]


class ReceiptStore:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS audit_receipts (
                receipt_id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
                batch_id TEXT NOT NULL,
                row_count INTEGER NOT NULL CHECK (row_count >= 0),
                total TEXT NOT NULL
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS audit_lines (
                receipt_id INTEGER NOT NULL REFERENCES audit_receipts(receipt_id),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                raw TEXT,
                calibrated TEXT,
                volume_id TEXT NOT NULL,
                slot INTEGER NOT NULL CHECK (slot >= 0),
                CHECK ((raw IS NULL) = (calibrated IS NULL)),
                PRIMARY KEY (receipt_id, ordinal),
                UNIQUE (receipt_id, volume_id, slot)
            )
        ''')

    def save(self, manifest, totals, lines):
        receipt_id = self.db.execute(
            '''INSERT INTO audit_receipts (job_id, batch_id, row_count, total)
               VALUES (?, ?, ?, ?)''',
            (manifest.job_id, manifest.batch_id, totals.row_count, encode_reading(totals.total)),
        ).lastrowid
        self.db.executemany(
            '''INSERT INTO audit_lines (receipt_id, ordinal, raw, calibrated, volume_id, slot)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                (receipt_id, line.ordinal, encode_reading(line.raw), encode_reading(line.calibrated),
                 line.volume_id, line.slot)
                for line in lines
            ),
        )
        return Receipt(receipt_id, manifest.job_id, manifest.batch_id, totals.row_count, totals.total, lines)

    def for_job(self, job_id):
        found = self.db.execute('SELECT receipt_id FROM audit_receipts WHERE job_id = ?', (job_id,)).fetchone()
        return self.load(found[0]) if found is not None else None

    def load(self, receipt_id):
        if type(receipt_id) is not int or not 1 <= receipt_id <= (1 << 63) - 1:
            return None
        header = self.db.execute(
            'SELECT job_id, batch_id, row_count, total FROM audit_receipts WHERE receipt_id = ?',
            (receipt_id,),
        ).fetchone()
        if header is None:
            return None
        rows = self.db.execute(
            '''SELECT ordinal, raw, calibrated, volume_id, slot FROM audit_lines
               WHERE receipt_id = ? ORDER BY ordinal''',
            (receipt_id,),
        )
        lines = tuple(
            ReconciledLine(ordinal, decode_reading(raw), decode_reading(value), volume, slot)
            for ordinal, raw, value, volume, slot in rows
        )
        job_id, batch_id, count, total = header
        return Receipt(receipt_id, job_id, batch_id, count, decode_reading(total), lines)


def get_receipt(workspace, receipt_id):
    with workspace.center() as db:
        return ReceiptStore(db).load(receipt_id)
