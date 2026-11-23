import json

from audit.issue import issue
from catalog.locations import LocationStore
from catalog.progress import progress
from catalog.retirement import retire
from catalog.volumes import VolumeRegistry
from media.mount import mount
from media.reader import read_mounted_rows
from tests import ArchiveCase
from transfer.attempts import AttemptStore
from transfer.sender import ship
from workspace import EvidenceUnavailable, InvalidVolume


class TestRetirement(ArchiveCase):
    def test_catalog_failure_before_retire(self):
        job = self.job('pending', [10, 10, 20])
        mount(self.ws, 'A', 2)
        self.block_catalog()
        reply = ship(self.ws, job.job_id, 'A')
        self.assertEqual((reply.status, reply.confirmed_count), ('unconfirmed', None))
        written = read_mounted_rows(self.ws, 'A')
        physical = [(row.ordinal, row.calibrated, row.slot) for row in written]
        self.assertEqual(physical, [(0, 10, 0), (1, 10, 1)])
        self.assertIsNone(progress(self.ws, job.job_id).confirmed_count)
        rejected = retire(self.ws, 'A')
        self.assertFalse(rejected)
        with self.ws.center() as db:
            self.assertEqual(VolumeRegistry(db).find('A').state, 'mounted')
            self.assertEqual(LocationStore(db).for_job(job.job_id), ())
            pending = AttemptStore(db).pending_for_job(job.job_id)
            self.assertEqual((pending.attempt_id, pending.start, pending.stop), (written[0].attempt_id, 0, 3))

        self.unblock_catalog()
        restored = ship(self.ws, job.job_id, 'A')
        self.assertEqual(restored.confirmed_count, 2)
        self.assertEqual(read_mounted_rows(self.ws, 'A'), written)
        self.assertTrue(retire(self.ws, 'A'))
        with self.assertRaises(EvidenceUnavailable):
            read_mounted_rows(self.ws, 'A')
        self.assert_locations(progress(self.ws, job.job_id).locations, [(0, 'A', 0), (1, 'A', 1)])
        mount(self.ws, 'B', 2)
        tail = ship(self.ws, job.job_id, 'B')
        self.assert_locations(tail.locations, [(0, 'A', 0), (1, 'A', 1), (2, 'B', 0)])
        after = issue(self.ws, job.job_id)
        downstream = {'rows': after.row_count, 'total': after.total}
        self.assertEqual(downstream, {'rows': 3, 'total': 40})
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v6',
            'input': {'readings': [10, 10, 20], 'capacity': 2, 'catalog_settlement_blocked': True},
            'expected': {'physical': [[0, 10, 0], [1, 10, 1]], 'retired_before_recovery': False},
            'actual': {'physical': physical, 'retired_before_recovery': rejected},
            'downstream_expected': {'rows': 3, 'total': 40}, 'downstream_actual': downstream,
            'code_paths': ['media/writer.py', 'catalog/receiving.py', 'catalog/retirement.py',
                           'transfer/attempts.py', 'audit/issue.py'],
            'oracle': '两物理槽应已使用，目录回滚后旧卷须仍可核对，复办只需补第三行。',
        }, ensure_ascii=False))

    def test_reopen_pending_retains_old_volume(self):
        job = self.job('interrupted', [10, 10, 20])
        mount(self.ws, 'A', 2)
        self.block_catalog()
        self.assertEqual(ship(self.ws, job.job_id, 'A').status, 'unconfirmed')
        before = read_mounted_rows(self.ws, 'A')
        self.reopen()
        self.assertIsNone(progress(self.ws, job.job_id).confirmed_count)
        self.assertFalse(retire(self.ws, 'A'))
        self.assertEqual(read_mounted_rows(self.ws, 'A'), before)
        mount(self.ws, 'B', 4)
        self.assertEqual(ship(self.ws, job.job_id, 'B').status, 'unconfirmed')
        self.assertEqual(read_mounted_rows(self.ws, 'B'), ())
        self.unblock_catalog()
        result = ship(self.ws, job.job_id, 'B')
        self.assert_locations(result.locations, [(0, 'A', 0), (1, 'A', 1), (2, 'B', 0)])
        self.assertEqual(read_mounted_rows(self.ws, 'A'), before)
        self.assertEqual([(row.ordinal, row.slot) for row in read_mounted_rows(self.ws, 'B')], [(2, 0)])
        self.assertTrue(retire(self.ws, 'A'))
        with self.assertRaises(InvalidVolume):
            mount(self.ws, 'A', 2)

    def test_retry_rolls_forward_after_medium_write_rollback(self):
        job = self.job('medium-interrupted', [2, 4])
        mount(self.ws, 'A', 2)
        with self.ws.medium('A', write=True) as db:
            db.execute('''
                CREATE TRIGGER block_second_row BEFORE INSERT ON medium_rows
                WHEN NEW.slot = 1
                BEGIN
                    SELECT RAISE(ABORT, 'medium interrupted');
                END
            ''')
        self.assertEqual(ship(self.ws, job.job_id, 'A').status, 'unconfirmed')
        self.assertEqual(read_mounted_rows(self.ws, 'A'), ())
        self.assertFalse(retire(self.ws, 'A'))
        self.reopen()
        with self.ws.medium('A', write=True) as db:
            db.execute('DROP TRIGGER block_second_row')
        retry = ship(self.ws, job.job_id, 'A')
        self.assert_locations(retry.locations, [(0, 'A', 0), (1, 'A', 1)])
        self.assertEqual([(row.raw, row.slot) for row in read_mounted_rows(self.ws, 'A')], [(2, 0), (4, 1)])
        self.assertTrue(retire(self.ws, 'A'))
