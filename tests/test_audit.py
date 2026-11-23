import json

from audit.issue import issue
from audit.receipts import get_receipt
from catalog.progress import progress
from catalog.retirement import retire
from intake.batches import load_batch
from media.mount import mount
from media.reader import read_mounted_rows
from tests import ArchiveCase
from transfer.jobs import load_job
from transfer.sender import ship
from workspace import IncompleteJob


class TestAudit(ArchiveCase):
    def test_incomplete_job_cannot_issue(self):
        job = self.job('partial', [10, 10, 20])
        mount(self.ws, 'A', 2)
        self.assertEqual(ship(self.ws, job.job_id, 'A').confirmed_count, 2)
        with self.assertRaises(IncompleteJob):
            issue(self.ws, job.job_id)
        self.assertIsNone(self.receipt_for_job(job.job_id))
        self.assertIsNone(get_receipt(self.ws, 1))

    def test_pending_evidence_cannot_issue(self):
        job = self.job('physically-complete', [3, 9])
        mount(self.ws, 'A', 2)
        self.block_catalog()
        self.assertEqual(ship(self.ws, job.job_id, 'A').status, 'unconfirmed')
        self.assertEqual([row.calibrated for row in read_mounted_rows(self.ws, 'A')], [3, 9])
        with self.assertRaises(IncompleteJob):
            issue(self.ws, job.job_id)
        self.assertIsNone(self.receipt_for_job(job.job_id))

    def test_receipt_survives_reopen(self):
        job = self.job('rollover', [5, 5, 10], 2)
        mount(self.ws, 'A', 2)
        self.assertEqual(ship(self.ws, job.job_id, 'A').confirmed_count, 2)
        self.assertTrue(retire(self.ws, 'A'))
        mount(self.ws, 'B', 2)
        self.assertEqual(ship(self.ws, job.job_id, 'B').confirmed_count, 3)
        issued = issue(self.ws, job.job_id)
        self.assertTrue(retire(self.ws, 'B'))
        self.ws.volume_file('A').unlink()
        self.ws.volume_file('B').unlink()
        self.reopen()
        receipt = get_receipt(self.ws, issued.receipt_id)
        self.assertEqual(receipt, issued)
        self.assertEqual(issue(self.ws, job.job_id), issued)
        self.assertEqual((receipt.row_count, receipt.total), (3, 40))
        self.assertEqual([(line.raw, line.calibrated) for line in receipt.lines], [(5, 10), (5, 10), (10, 20)])
        self.assert_locations(receipt.lines, [(0, 'A', 0), (1, 'A', 1), (2, 'B', 0)])

    def test_same_slot_in_two_volumes_is_preserved(self):
        job = self.job('two-zero-slots', [6, 9])
        mount(self.ws, 'A', 1)
        ship(self.ws, job.job_id, 'A')
        self.assertTrue(retire(self.ws, 'A'))
        mount(self.ws, 'B', 1)
        ship(self.ws, job.job_id, 'B')
        issued = issue(self.ws, job.job_id)
        self.assert_locations(issued.lines, [(0, 'A', 0), (1, 'B', 0)])
        self.ws.volume_file('A').unlink()
        self.reopen()
        loaded = get_receipt(self.ws, issued.receipt_id)
        self.assertEqual(loaded, issued)
        self.assertEqual((loaded.row_count, loaded.total), (2, 15))
        self.assert_locations(loaded.lines, [(0, 'A', 0), (1, 'B', 0)])

    def test_exact_total_includes_valid_zero_and_preserves_missing(self):
        large = 1 << 70
        raw = [large + 1, None, -large, 0]
        job = self.job('exact-sum', raw, 2)
        mount(self.ws, 'A', 4)
        self.assertEqual(ship(self.ws, job.job_id, 'A').confirmed_count, 4)
        issued = issue(self.ws, job.job_id)
        self.reopen()
        loaded = get_receipt(self.ws, issued.receipt_id)
        expected = [(1 << 71) + 2, None, -(1 << 71), 0]
        actual = [line.calibrated for line in loaded.lines]
        downstream = {'rows': loaded.row_count, 'total': loaded.total}
        self.assertEqual(actual, expected)
        self.assertEqual(downstream, {'rows': 4, 'total': 2})
        self.assertEqual([line.raw for line in loaded.lines], raw)
        self.assert_locations(loaded.lines, [(0, 'A', 0), (1, 'A', 1), (2, 'A', 2), (3, 'A', 3)])
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v8.exact_total', 'input': {'readings': raw, 'multiplier': 2},
            'expected': expected, 'actual': actual,
            'downstream_expected': {'rows': 4, 'total': 2}, 'downstream_actual': downstream,
            'code_paths': ['intake/calibration.py', 'media/records.py', 'audit/totals.py', 'audit/receipts.py'],
            'oracle': '正负两项的 2^71 相消，剩余 2。缺测和有效零均占卷位。',
        }, ensure_ascii=False))

    def test_all_missing_still_has_count_and_locations(self):
        job = self.job('all-missing', [None, None], 99)
        mount(self.ws, 'A', 2)
        ship(self.ws, job.job_id, 'A')
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total), (2, 0))
        self.assertEqual([(line.raw, line.calibrated) for line in receipt.lines], [(None, None), (None, None)])
        self.assert_locations(receipt.lines, [(0, 'A', 0), (1, 'A', 1)])

    def test_empty_task_issues_zero_row_receipt(self):
        job = self.job('empty', [], 0)
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total, receipt.lines), (0, 0, ()))

    def test_unknown_receipt_returns_none(self):
        self.assertIsNone(get_receipt(self.ws, 42))
        self.assertIsNone(get_receipt(self.ws, 1 << 70))
        self.assertIsNone(get_receipt(self.ws, True))

    def test_repeat_initialize_preserves_user_data(self):
        first = self.job('signed', [10])
        mount(self.ws, 'A', 4)
        ship(self.ws, first.job_id, 'A')
        receipt = issue(self.ws, first.job_id)
        user = self.job('user-import', [-3, None], -2)
        ship(self.ws, user.job_id, 'A')
        saved_batch = load_batch(self.ws, 'user-import')
        saved_physical = read_mounted_rows(self.ws, 'A')
        self.ws.initialize()
        self.ws.initialize()
        self.reopen()
        self.assertEqual(load_batch(self.ws, 'user-import'), saved_batch)
        self.assertEqual([row.calibrated for row in saved_batch.rows], [6, None])
        with self.ws.center() as db:
            self.assertEqual(load_job(db, user.job_id), user)
        self.assertEqual(read_mounted_rows(self.ws, 'A'), saved_physical)
        self.assert_locations(progress(self.ws, user.job_id).locations, [(0, 'A', 1), (1, 'A', 2)])
        self.assertEqual(get_receipt(self.ws, receipt.receipt_id), receipt)
