from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.issue import issue
from audit.receipts import get_receipt
from catalog.progress import progress
from catalog.retirement import retire
from intake.batches import import_batch
from media.mount import mount
from media.reader import read_mounted_rows
from transfer.jobs import freeze_job
from transfer.sender import ship
from workspace import Workspace


def main():
    sample = Path(__file__).resolve().parent / 'samples' / 'day_shift.json'
    data = json.loads(sample.read_text(encoding='utf-8'))
    expected_prefix = [[0, 'A', 1], [1, 'A', 2]]
    expected = [[0, 'A', 1], [1, 'A', 2], [2, 'B', 0]]
    expected_totals = {'rows': 3, 'total': 40}

    with TemporaryDirectory(prefix='inspection-archive-') as root:
        ws = Workspace(root)
        old = mount(ws, **data['old_volume'])
        seed = import_batch(ws, **data['preceding'])
        previous = freeze_job(ws, seed.batch_id)
        if ship(ws, previous.job_id, old.volume_id).confirmed_count != 1:
            raise AssertionError('preceding task did not occupy one slot')

        batch = import_batch(ws, **data['inspection'])
        job = freeze_job(ws, batch.batch_id)
        ship(ws, job.job_id, old.volume_id)  # The caller loses the reply.
        old_rows = [
            [row.ordinal, row.calibrated, row.slot] for row in read_mounted_rows(ws, old.volume_id)
            if row.job_id == job.job_id
        ]
        if old_rows != [[0, 10, 1], [1, 10, 2]] or not retire(ws, old.volume_id):
            raise AssertionError('old volume did not retain the two original rows')
        ws.volume_file(old.volume_id).unlink()

        ws = Workspace(root)
        prefix = [[loc.ordinal, loc.volume_id, loc.slot] for loc in progress(ws, job.job_id).locations]
        if prefix != expected_prefix:
            raise AssertionError('ARCHIVE_PREFIX_MISMATCH: retired volume prefix')
        new = mount(ws, **data['next_volume'])
        shipped = ship(ws, job.job_id, new.volume_id)
        actual = [[loc.ordinal, loc.volume_id, loc.slot] for loc in shipped.locations]
        new_rows = [(row.ordinal, row.calibrated) for row in read_mounted_rows(ws, new.volume_id)]
        if shipped.confirmed_count != 3 or actual != expected or new_rows != [(2, 20)]:
            raise AssertionError('ARCHIVE_PREFIX_MISMATCH: rollover locations')
        issued = issue(ws, job.job_id)
        receipt = get_receipt(Workspace(root), issued.receipt_id)
        downstream = {'rows': receipt.row_count, 'total': receipt.total}
        receipt_locations = [[line.ordinal, line.volume_id, line.slot] for line in receipt.lines]
        if (receipt != issued or downstream != expected_totals or receipt_locations != expected
            or [line.calibrated for line in receipt.lines] != [10, 10, 20]):
            raise AssertionError('receipt does not reconstruct the shift')

        print(json.dumps(asdict(receipt), ensure_ascii=False))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v5.reopen_rollover',
            'input': data,
            'expected': expected,
            'actual': actual,
            'downstream_expected': expected_totals,
            'downstream_actual': downstream,
            'code_paths': ['intake/batches.py', 'transfer/sender.py', 'media/writer.py',
                           'catalog/retirement.py', 'catalog/progress.py', 'audit/issue.py'],
            'oracle': 'A 的零位已占用。A 的一、二位各收一条 10，B 的零位收 20，合计 40。',
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
