from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.issue import issue
from audit.receipts import get_receipt
from catalog.progress import progress
from intake.batches import import_batch
from media.mount import mount
from media.reader import read_mounted_rows
from transfer.jobs import freeze_job
from transfer.sender import ship
from workspace import IncompleteJob, Workspace


def load_case():
    path = Path(__file__).resolve().parent / "samples" / "bypass.json"
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(ws, case):
    mount(ws, **case["primary"])
    mount(ws, **case["bypass"])
    batch = import_batch(ws, **case["inspection"])
    return freeze_job(ws, batch.batch_id).job_id


@contextmanager
def reject_confirmation(ws):
    with ws.center(write=True) as db:
        db.execute("""
            CREATE TRIGGER bypass_fixture_stop
            BEFORE UPDATE OF pending ON transfer_attempts
            WHEN OLD.pending = 1 AND NEW.pending = 0
            BEGIN
                SELECT RAISE(ABORT, 'fixture confirmation stopped');
            END
        """)
    try:
        yield
    finally:
        with ws.center(write=True) as db:
            db.execute("DROP TRIGGER bypass_fixture_stop")


@contextmanager
def volume_away(ws, volume_id):
    path = ws.volume_file(volume_id)
    parked = path.with_suffix(".away")
    if parked.exists():
        raise AssertionError("fixture already has a parked medium")
    path.rename(parked)
    try:
        yield
    finally:
        if path.exists():
            raise AssertionError("operation created a replacement for the absent medium")
        parked.rename(path)


def locations(lines):
    return [[line.ordinal, line.volume_id, line.slot] for line in lines]


def check_v1(ws):
    case = load_case()
    job_id = prepare(ws, case)
    primary = case["primary"]["volume_id"]
    bypass = case["bypass"]["volume_id"]
    with reject_confirmation(ws):
        first = ship(ws, job_id, primary)
    physical = read_mounted_rows(ws, primary)
    if first.status != "unconfirmed" or [(r.ordinal, r.slot, r.raw) for r in physical] != [
        (0, 0, 7), (1, 1, 7), (2, 2, 13)
    ]:
        raise AssertionError("fixture did not leave three written rows pending")

    with volume_away(ws, primary):
        ws = Workspace(ws.root)
        blocked = ship(ws, job_id, bypass)
        bypass_rows = read_mounted_rows(ws, bypass)
        if blocked.status != "unconfirmed" or bypass_rows or progress(ws, job_id).locations:
            raise AssertionError("ordinary shipment advanced while the pending medium was absent")
        try:
            issue(ws, job_id)
        except IncompleteJob:
            pass
        else:
            raise AssertionError("ordinary shipment issued without confirmed evidence")

    ws = Workspace(ws.root)
    ship(ws, job_id, primary)
    receipt = issue(ws, job_id)
    expected = [[ordinal, primary, ordinal] for ordinal in range(3)]
    if (receipt.row_count, receipt.total, locations(receipt.lines)) != (3, 27, expected):
        raise AssertionError("returning medium did not restore the ordinary receipt")
    if read_mounted_rows(ws, primary) != physical:
        raise AssertionError("ordinary recovery rewrote the pending rows")
    if get_receipt(Workspace(ws.root), receipt.receipt_id) != receipt:
        raise AssertionError("ordinary receipt changed on reopening")
    return {
        "ordinary_while_away": blocked.status,
        "bypass_slots_while_away": len(bypass_rows),
        "receipt_locations": locations(receipt.lines),
        "receipt_total": receipt.total,
    }


def main():
    with TemporaryDirectory(prefix="inspection-bypass-fixture-") as root:
        print(json.dumps(check_v1(Workspace(root)), ensure_ascii=False))


if __name__ == "__main__":
    main()
