from audit.issue import issue
from catalog.progress import progress
from catalog.retirement import retire
from media.mount import mount
from media.reader import read_mounted_rows
from tests import ArchiveCase
from transfer.sender import ship
from workspace import EvidenceUnavailable, InvalidVolume, UnknownJob


class TestTransfer(ArchiveCase):
    def test_normal_single_volume(self):
        job = self.job('inspection', [3, 7, -1])
        mount(self.ws, 'A', 5)
        result = ship(self.ws, job.job_id, 'A')
        self.assertEqual((result.status, result.confirmed_count), ('complete', 3))
        self.assert_locations(result.locations, [(0, 'A', 0), (1, 'A', 1), (2, 'A', 2)])
        physical = read_mounted_rows(self.ws, 'A')
        self.assertEqual([(row.ordinal, row.calibrated) for row in physical], [(0, 3), (1, 7), (2, -1)])
        self.assertEqual(ship(self.ws, job.job_id, 'A'), result)
        self.assertEqual(read_mounted_rows(self.ws, 'A'), physical)
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total), (3, 9))

    def test_mount_capacity_and_reopen_preserve_rows(self):
        for bad in (-1, True, 2.5, 1 << 63):
            with self.subTest(capacity=bad), self.assertRaises(InvalidVolume):
                mount(self.ws, 'invalid', bad)
        with self.assertRaises(EvidenceUnavailable):
            read_mounted_rows(self.ws, 'invalid')
        job = self.job('first', [3])
        mounted = mount(self.ws, 'A', 2)
        ship(self.ws, job.job_id, 'A')
        physical = read_mounted_rows(self.ws, 'A')
        self.reopen()
        self.assertEqual(mount(self.ws, 'A', 2), mounted)
        with self.assertRaises(InvalidVolume):
            mount(self.ws, 'A', 3)
        self.assertEqual(read_mounted_rows(self.ws, 'A'), physical)

    def test_equal_rows_have_distinct_physical_locations(self):
        job = self.job('equal', [10, 10, 20])
        mount(self.ws, 'A', 3)
        result = ship(self.ws, job.job_id, 'A')
        physical = read_mounted_rows(self.ws, 'A')
        self.assertEqual([(r.ordinal, r.calibrated, r.slot) for r in physical], [(0, 10, 0), (1, 10, 1), (2, 20, 2)])
        self.assert_locations(result.locations, [(0, 'A', 0), (1, 'A', 1), (2, 'A', 2)])

    def test_full_volume_reports_zero(self):
        first = self.job('first', [3, 4])
        next_job = self.job('next', [5])
        mount(self.ws, 'A', 2)
        prior = ship(self.ws, first.job_id, 'A')
        occupied = read_mounted_rows(self.ws, 'A')
        result = ship(self.ws, next_job.job_id, 'A')
        self.assertEqual((result.status, result.confirmed_count, result.locations), ('partial', 0, ()))
        self.assertEqual(read_mounted_rows(self.ws, 'A'), occupied)
        self.assertEqual([(row.slot, row.calibrated) for row in occupied], [(0, 3), (1, 4)])
        self.assertEqual(progress(self.ws, first.job_id).locations, prior.locations)
        self.assertEqual(progress(self.ws, next_job.job_id).confirmed_count, 0)

    def test_zero_capacity_volume_has_no_slots(self):
        job = self.job('no-space', [4])
        mount(self.ws, 'Zero', 0)
        self.assertEqual(ship(self.ws, job.job_id, 'Zero').confirmed_count, 0)
        self.assertEqual(read_mounted_rows(self.ws, 'Zero'), ())
        self.assertTrue(retire(self.ws, 'Zero'))

    def test_acknowledged_short_write_only_resends_tail(self):
        job = self.job('short', [10, 10, 20])
        mount(self.ws, 'A', 2)
        reply = ship(self.ws, job.job_id, 'A')
        self.assertEqual((reply.status, reply.confirmed_count), ('partial', 2), 'ARCHIVE_PREFIX_MISMATCH')
        self.assert_locations(reply.locations, [(0, 'A', 0), (1, 'A', 1)])
        mount(self.ws, 'B', 10)
        result = ship(self.ws, job.job_id, 'B')
        self.assertEqual((result.status, result.confirmed_count), ('complete', 3), 'ARCHIVE_PREFIX_MISMATCH')
        self.assertEqual([(row.ordinal, row.calibrated) for row in read_mounted_rows(self.ws, 'B')], [(2, 20)],
                         'ARCHIVE_PREFIX_MISMATCH')

    def test_short_write_lost_reply_rollover(self):
        marker = 'ARCHIVE_PREFIX_MISMATCH'
        earlier = self.job('previous', [7])
        mount(self.ws, 'A', 3)
        self.assertEqual(ship(self.ws, earlier.job_id, 'A').confirmed_count, 1)
        job = self.job('incident-shift', [5, 5, 10], 2)
        ship(self.ws, job.job_id, 'A')  # The caller loses the reply.
        old = [row for row in read_mounted_rows(self.ws, 'A') if row.job_id == job.job_id]
        self.assertEqual([(row.ordinal, row.calibrated, row.slot) for row in old], [(0, 10, 1), (1, 10, 2)], marker)
        self.assertTrue(retire(self.ws, 'A'), marker)
        with self.assertRaises(EvidenceUnavailable):
            read_mounted_rows(self.ws, 'A')
        self.ws.volume_file('A').unlink()
        self.reopen()
        offline = progress(self.ws, job.job_id)
        self.assertEqual(offline.confirmed_count, 2, marker)
        self.assert_locations(offline.locations, [(0, 'A', 1), (1, 'A', 2)], marker)
        mount(self.ws, 'B', 3)
        replay = ship(self.ws, job.job_id, 'B')
        self.assertEqual((replay.status, replay.confirmed_count), ('complete', 3), marker)
        self.assert_locations(replay.locations, [(0, 'A', 1), (1, 'A', 2), (2, 'B', 0)], marker)
        new = read_mounted_rows(self.ws, 'B')
        self.assertEqual([(row.job_id, row.ordinal, row.calibrated) for row in new], [(job.job_id, 2, 20)], marker)
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total), (3, 40), marker)
        self.assert_locations(receipt.lines, [(0, 'A', 1), (1, 'A', 2), (2, 'B', 0)], marker)

    def test_unknown_task_is_rejected(self):
        mount(self.ws, 'A', 1)
        with self.assertRaises(UnknownJob):
            ship(self.ws, 123, 'A')
        with self.assertRaises(UnknownJob):
            progress(self.ws, 123)
        self.assertEqual(read_mounted_rows(self.ws, 'A'), ())
