from tempfile import TemporaryDirectory
from unittest import TestCase

from audit.receipts import ReceiptStore
from intake.batches import import_batch
from transfer.jobs import freeze_job
from workspace import Workspace


class ArchiveCase(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='inspection-tests-'))
        self.root = directory
        self.ws = Workspace(directory)

    def reopen(self):
        self.ws = Workspace(self.root)

    def job(self, batch_id, readings, multiplier=1):
        import_batch(self.ws, batch_id, multiplier, readings)
        return freeze_job(self.ws, batch_id)

    def block_catalog(self):
        with self.ws.center(write=True) as db:
            db.execute('''
                CREATE TRIGGER block_catalog_settlement
                BEFORE UPDATE OF pending ON transfer_attempts
                WHEN OLD.pending = 1 AND NEW.pending = 0
                BEGIN
                    SELECT RAISE(ABORT, 'directory settlement unavailable');
                END
            ''')

    def unblock_catalog(self):
        with self.ws.center(write=True) as db:
            db.execute('DROP TRIGGER block_catalog_settlement')

    def receipt_for_job(self, job_id):
        with self.ws.center() as db:
            return ReceiptStore(db).for_job(job_id)

    def assert_locations(self, locations, expected, message=None):
        self.assertEqual([(location.ordinal, location.volume_id, location.slot) for location in locations],
                         expected, message)
