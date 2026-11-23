from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


class UnknownBatch(KeyError):
    pass


class UnknownJob(KeyError):
    pass


class InvalidVolume(ValueError):
    pass


class EvidenceUnavailable(RuntimeError):
    pass


class IncompleteJob(RuntimeError):
    pass


@contextmanager
def _transaction(path, mode, *, immediate=False):
    uri = f'{path.as_uri()}?mode={mode}'
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as db:
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.center_path = self.root / 'center.sqlite3'
        self.initialize()

    def initialize(self):
        from audit.receipts import ReceiptStore
        from catalog.locations import LocationStore
        from catalog.volumes import VolumeRegistry
        from intake.storage import BatchStore
        from transfer.attempts import AttemptStore
        from transfer.jobs import initialize_jobs

        (self.root / 'volumes').mkdir(parents=True, exist_ok=True)
        with self.operation():
            with _transaction(self.center_path, 'rwc', immediate=True) as db:
                BatchStore(db).initialize()
                initialize_jobs(db)
                VolumeRegistry(db).initialize()
                AttemptStore(db).initialize()
                LocationStore(db).initialize()
                ReceiptStore(db).initialize()

    def operation(self):
        # A separate lock remains held across independent center and medium commits.
        return _transaction(self.root / 'operations.sqlite3', 'rwc', immediate=True)

    def center(self, *, write=False):
        return _transaction(self.center_path, 'rw' if write else 'ro', immediate=write)

    def volume_file(self, volume_id):
        from media.capacity import validate_volume_id

        validate_volume_id(volume_id)
        # Encoding also keeps IDs distinct on case-insensitive file systems.
        name = volume_id.encode('ascii').hex() + '.sqlite3'
        return self.root / 'volumes' / name

    def medium(self, volume_id, *, write=False, create=False):
        mode = 'rwc' if create else 'rw' if write else 'ro'
        return _transaction(self.volume_file(volume_id), mode, immediate=write or create)
