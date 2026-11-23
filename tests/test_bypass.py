from audit.issue import issue
from audit.receipts import get_receipt
from catalog.progress import progress
from catalog.retirement import retire
from intake.records import encode_reading
from media.mount import mount
from media.reader import read_mounted_rows
from tests import ArchiveCase
from transfer.sender import settle_volume, ship, ship_bypass
from workspace import IncompleteJob, InvalidVolume, UnknownJob


class TestBypass(ArchiveCase):
    def prepare_pair(self, batch_id='night-shift', readings=(7, 7, 13),
                     primary_capacity=3, bypass_capacity=1):
        job = self.job(batch_id, list(readings))
        mount(self.ws, 'A', primary_capacity)
        mount(self.ws, 'B', bypass_capacity)
        self.block_catalog()
        self.assertEqual(ship(self.ws, job.job_id, 'A').status, 'unconfirmed')
        self.unblock_catalog()
        return job

    def park(self, volume_id):
        path = self.ws.volume_file(volume_id)
        parked = path.with_suffix('.away')
        path.rename(parked)
        self.reopen()
        return parked

    def restore(self, volume_id, parked):
        parked.rename(self.ws.volume_file(volume_id))
        self.reopen()

    def tamper_raw(self, volume_id, ordinal, raw):
        with self.ws.medium(volume_id, write=True) as db:
            db.execute(
                'UPDATE medium_rows SET raw = ?, calibrated = ? WHERE ordinal = ?',
                (encode_reading(raw), encode_reading(raw), ordinal),
            )

    def test_bypass_confirms_first_then_original_returns(self):
        job = self.prepare_pair()
        parked = self.park('A')
        shipped = ship_bypass(self.ws, job.job_id, 'B')
        self.assertEqual((shipped.status, shipped.confirmed_count), ('partial', 1))
        self.assert_locations(shipped.locations, [(0, 'B', 0)])
        during = progress(self.ws, job.job_id)
        self.assertEqual(during.confirmed_count, 1)
        self.assert_locations(during.locations, [(0, 'B', 0)])
        with self.assertRaises(IncompleteJob):
            issue(self.ws, job.job_id)
        self.assertTrue(retire(self.ws, 'B'))

        self.restore('A', parked)
        self.assertTrue(settle_volume(self.ws, job.job_id, 'A'))
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total), (3, 27))
        self.assert_locations(receipt.lines, [(0, 'B', 0), (1, 'A', 1), (2, 'A', 2)])
        # The duplicate A:0 slot is redundant but still checked on retirement.
        self.assertTrue(retire(self.ws, 'A'))

    def test_original_settles_first_then_bypass_slot_is_redundant(self):
        job = self.prepare_pair()
        parked = self.park('A')
        self.block_catalog()
        self.assertEqual(ship_bypass(self.ws, job.job_id, 'B').status, 'unconfirmed')
        self.unblock_catalog()
        self.assertEqual(
            [(row.ordinal, row.slot) for row in read_mounted_rows(self.ws, 'B')], [(0, 0)])

        self.restore('A', parked)
        self.assertTrue(settle_volume(self.ws, job.job_id, 'A'))
        receipt = issue(self.ws, job.job_id)
        self.assertEqual((receipt.row_count, receipt.total), (3, 27))
        self.assert_locations(receipt.lines, [(0, 'A', 0), (1, 'A', 1), (2, 'A', 2)])
        self.assertFalse(retire(self.ws, 'B'))
        self.assertTrue(settle_volume(self.ws, job.job_id, 'B'))
        self.assertTrue(retire(self.ws, 'B'))
        self.assertTrue(retire(self.ws, 'A'))

        self.ws.volume_file('A').unlink()
        self.ws.volume_file('B').unlink()
        self.reopen()
        self.assertEqual(get_receipt(self.ws, receipt.receipt_id), receipt)
        self.assertEqual(issue(self.ws, job.job_id), receipt)

    def test_ship_bypass_registration_rejections(self):
        job = self.job('plain', [5])
        mount(self.ws, 'A', 1)
        mount(self.ws, 'B', 1)
        with self.assertRaises(ValueError):
            ship_bypass(self.ws, job.job_id, 'B')  # no pending original volume
        self.block_catalog()
        ship(self.ws, job.job_id, 'A')
        self.unblock_catalog()
        with self.assertRaises(ValueError):
            ship_bypass(self.ws, job.job_id, 'A')  # same as the pending original
        with self.assertRaises(ValueError):
            ship_bypass(self.ws, job.job_id, 'B')  # original is still readable
        with self.assertRaises(InvalidVolume):
            ship_bypass(self.ws, job.job_id, 'C')  # not mounted
        with self.assertRaises(InvalidVolume):
            ship_bypass(self.ws, job.job_id, 'bad id!')
        with self.assertRaises(UnknownJob):
            ship_bypass(self.ws, 999, 'B')

    def test_ship_bypass_rebinding_and_settled_replay(self):
        job = self.prepare_pair()
        mount(self.ws, 'C', 3)
        parked = self.park('A')
        ship_bypass(self.ws, job.job_id, 'B')
        with self.assertRaises(ValueError):
            ship_bypass(self.ws, job.job_id, 'C')
        replay = ship_bypass(self.ws, job.job_id, 'B')
        self.assertEqual((replay.status, replay.confirmed_count), ('partial', 1))
        self.assert_locations(replay.locations, [(0, 'B', 0)])
        self.assertEqual([(row.ordinal, row.slot) for row in read_mounted_rows(self.ws, 'B')],
                         [(0, 0)])

    def test_ship_bypass_reopen_keeps_original_slots(self):
        job = self.prepare_pair()
        parked = self.park('A')
        self.block_catalog()
        self.assertEqual(ship_bypass(self.ws, job.job_id, 'B').status, 'unconfirmed')
        self.unblock_catalog()
        self.reopen()
        before = read_mounted_rows(self.ws, 'B')
        continued = ship_bypass(self.ws, job.job_id, 'B')
        self.assertEqual((continued.status, continued.confirmed_count), ('partial', 1))
        self.assert_locations(continued.locations, [(0, 'B', 0)])
        self.assertEqual(read_mounted_rows(self.ws, 'B'), before)

    def test_settle_volume_rejections_and_recheck(self):
        job = self.job('unpaired', [5])
        mount(self.ws, 'Z', 1)
        with self.assertRaises(ValueError):
            settle_volume(self.ws, job.job_id, 'Z')  # no bypass registered
        with self.assertRaises(UnknownJob):
            settle_volume(self.ws, 999, 'Z')
        with self.assertRaises(InvalidVolume):
            settle_volume(self.ws, job.job_id, 'bad id!')

        paired = self.prepare_pair(batch_id='paired')
        mount(self.ws, 'C', 1)
        parked = self.park('A')
        ship_bypass(self.ws, paired.job_id, 'B')
        self.restore('A', parked)
        with self.assertRaises(ValueError):
            settle_volume(self.ws, paired.job_id, 'C')  # outside the pair
        self.assertTrue(settle_volume(self.ws, paired.job_id, 'A'))
        self.assertTrue(settle_volume(self.ws, paired.job_id, 'A'))
        self.assertTrue(retire(self.ws, 'A'))
        self.ws.volume_file('A').unlink()
        self.reopen()
        # A settled attempt rechecks by its binding even after retiring.
        self.assertTrue(settle_volume(self.ws, paired.job_id, 'A'))

    def test_settle_volume_missing_and_mismatched_medium(self):
        job = self.prepare_pair()
        parked = self.park('A')
        ship_bypass(self.ws, job.job_id, 'B')
        self.assertFalse(settle_volume(self.ws, job.job_id, 'A'))  # medium still away
        self.assert_locations(progress(self.ws, job.job_id).locations, [(0, 'B', 0)])

        self.restore('A', parked)
        self.tamper_raw('A', 1, 9)
        self.assertFalse(settle_volume(self.ws, job.job_id, 'A'))
        self.assert_locations(progress(self.ws, job.job_id).locations, [(0, 'B', 0)])
        with self.assertRaises(IncompleteJob):
            issue(self.ws, job.job_id)

        self.tamper_raw('A', 1, 7)
        self.assertTrue(settle_volume(self.ws, job.job_id, 'A'))
        receipt = issue(self.ws, job.job_id)
        self.assertEqual(receipt.total, 27)
        self.assert_locations(receipt.lines, [(0, 'B', 0), (1, 'A', 1), (2, 'A', 2)])

    def test_tail_ships_normally_after_both_settle(self):
        job = self.prepare_pair(primary_capacity=2)
        parked = self.park('A')
        self.assertEqual(ship_bypass(self.ws, job.job_id, 'B').confirmed_count, 1)
        self.restore('A', parked)
        self.assertTrue(settle_volume(self.ws, job.job_id, 'A'))
        mount(self.ws, 'C', 1)
        tail = ship(self.ws, job.job_id, 'C')
        self.assertEqual(tail.status, 'complete')
        self.assert_locations(tail.locations, [(0, 'B', 0), (1, 'A', 1), (2, 'C', 0)])
        receipt = issue(self.ws, job.job_id)
        self.assertEqual(receipt.total, 27)
        self.assertTrue(retire(self.ws, 'A'))
        self.assertTrue(retire(self.ws, 'B'))
        self.assertTrue(retire(self.ws, 'C'))

    def test_no_third_shipment_while_pair_pending(self):
        job = self.prepare_pair()
        parked = self.park('A')
        self.block_catalog()
        self.assertEqual(ship_bypass(self.ws, job.job_id, 'B').status, 'unconfirmed')
        self.unblock_catalog()
        mount(self.ws, 'C', 3)
        result = ship(self.ws, job.job_id, 'C')
        self.assertEqual(result.status, 'unconfirmed')
        self.assertEqual(read_mounted_rows(self.ws, 'C'), ())

    def test_zero_capacity_bypass_settles_empty(self):
        job = self.prepare_pair(bypass_capacity=0)
        parked = self.park('A')
        shipped = ship_bypass(self.ws, job.job_id, 'B')
        self.assertEqual((shipped.status, shipped.confirmed_count), ('partial', 0))
        self.assertTrue(settle_volume(self.ws, job.job_id, 'B'))
        self.restore('A', parked)
        self.assertTrue(settle_volume(self.ws, job.job_id, 'A'))
        receipt = issue(self.ws, job.job_id)
        self.assert_locations(receipt.lines, [(0, 'A', 0), (1, 'A', 1), (2, 'A', 2)])
