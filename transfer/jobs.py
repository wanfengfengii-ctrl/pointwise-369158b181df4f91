from intake.records import decode_reading, encode_reading
from intake.storage import BatchStore
from transfer.manifest import JobManifest, ManifestRow, freeze_manifest
from workspace import UnknownBatch, UnknownJob


_MAX_ROW_ID = (1 << 63) - 1


def initialize_jobs(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(batch_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS manifest_rows (
            job_id INTEGER NOT NULL REFERENCES jobs(job_id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            raw TEXT,
            calibrated TEXT,
            CHECK ((raw IS NULL) = (calibrated IS NULL)),
            PRIMARY KEY (job_id, ordinal)
        )
    ''')


def freeze_job(workspace, batch_id):
    with workspace.operation(), workspace.center(write=True) as db:
        batch = BatchStore(db).load(batch_id)
        if batch is None:
            raise UnknownBatch(batch_id)
        job_id = db.execute('INSERT INTO jobs (batch_id) VALUES (?)', (batch_id,)).lastrowid
        manifest = freeze_manifest(job_id, batch)
        db.executemany(
            '''INSERT INTO manifest_rows (job_id, ordinal, raw, calibrated)
               VALUES (?, ?, ?, ?)''',
            (
                (job_id, row.ordinal, encode_reading(row.raw), encode_reading(row.calibrated))
                for row in manifest.rows
            ),
        )
    return manifest


def load_job(db, job_id):
    if type(job_id) is not int or not 1 <= job_id <= _MAX_ROW_ID:
        raise UnknownJob(job_id)
    header = db.execute('SELECT batch_id FROM jobs WHERE job_id = ?', (job_id,)).fetchone()
    if header is None:
        raise UnknownJob(job_id)
    records = db.execute(
        '''SELECT ordinal, raw, calibrated FROM manifest_rows
           WHERE job_id = ? ORDER BY ordinal''',
        (job_id,),
    )
    rows = tuple(
        ManifestRow(ordinal, decode_reading(raw), decode_reading(calibrated))
        for ordinal, raw, calibrated in records
    )
    return JobManifest(job_id, header[0], rows)
