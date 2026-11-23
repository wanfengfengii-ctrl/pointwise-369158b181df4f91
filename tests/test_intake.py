import json

from intake.batches import import_batch, load_batch
from intake.validation import InvalidBatch
from tests import ArchiveCase
from transfer.jobs import freeze_job, load_job
from workspace import UnknownBatch


def readings(rows):
    return [(row.ordinal, row.raw, row.calibrated) for row in rows]


class TestIntake(ArchiveCase):
    def test_calibrate_with_missing(self):
        raw = [5, None, -2]
        expected = [(0, 5, 10), (1, None, None), (2, -2, -4)]
        batch = import_batch(self.ws, 'A17', 2, raw)
        job = freeze_job(self.ws, 'A17')
        actual = readings(batch.rows)
        downstream = readings(job.rows)
        self.assertEqual(batch.multiplier, 2)
        self.assertEqual(actual, expected)
        self.assertEqual(downstream, expected)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v1', 'input': {'multiplier': 2, 'readings': raw},
            'expected': expected, 'actual': actual,
            'downstream_expected': expected, 'downstream_actual': downstream,
            'code_paths': ['intake/calibration.py', 'intake/storage.py', 'transfer/jobs.py'],
            'oracle': '5 乘 2 是 10，缺测保留原位，负 2 乘 2 是负 4。',
        }, ensure_ascii=False))

    def test_exact_integer_survives_reopen(self):
        large = 1 << 70
        import_batch(self.ws, 'large', 2, [large + 1, None, -large])
        self.reopen()
        expected = [(0, large + 1, (1 << 71) + 2), (1, None, None), (2, -large, -(1 << 71))]
        self.assertEqual(readings(load_batch(self.ws, 'large').rows), expected)
        self.assertEqual(readings(freeze_job(self.ws, 'large').rows), expected)

    def test_frozen_snapshot_survives_other_import(self):
        first = self.job('frozen', [5, None, -2], 2)
        self.job('later', [99, 0], -3)
        self.reopen()
        with self.ws.center() as db:
            saved = load_job(db, first.job_id)
        self.assertEqual(saved, first)
        self.assertEqual(readings(saved.rows), [(0, 5, 10), (1, None, None), (2, -2, -4)])

    def test_invalid_batch_rejected(self):
        for invalid in (True, 2.0, '2'):
            with self.subTest(multiplier=invalid):
                with self.assertRaises(InvalidBatch):
                    import_batch(self.ws, 'invalid', invalid, [5])
                self.assertIsNone(load_batch(self.ws, 'invalid'))
        self.reopen()
        self.assertIsNone(load_batch(self.ws, 'invalid'))

    def test_invalid_tail_rejects_entire_batch(self):
        with self.assertRaises(InvalidBatch):
            import_batch(self.ws, 'bad-tail', 2, [5, None, True])
        self.reopen()
        self.assertIsNone(load_batch(self.ws, 'bad-tail'))
        with self.assertRaises(UnknownBatch):
            freeze_job(self.ws, 'bad-tail')
        with self.ws.center() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM intake_rows').fetchone()[0], 0)

    def test_unknown_batch_creates_no_job(self):
        with self.assertRaises(UnknownBatch):
            freeze_job(self.ws, 'missing')
        with self.ws.center() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_existing_batch_binding_is_immutable(self):
        first = import_batch(self.ws, 'registered', -2, [1, 0])
        with self.assertRaises(InvalidBatch):
            import_batch(self.ws, 'registered', 10, [4])
        self.assertEqual(load_batch(self.ws, 'registered'), first)
        self.assertEqual(readings(first.rows), [(0, 1, -2), (1, 0, 0)])
