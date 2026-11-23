from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.issue import issue
from audit.receipts import get_receipt
from catalog.progress import progress
from catalog.retirement import retire
from intake.batches import import_batch
from intake.records import encode_reading
from media.mount import mount
from media.reader import read_mounted_rows
from transfer.jobs import freeze_job
from transfer.sender import settle_volume, ship, ship_bypass
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


def check_v2(ws):
    """The bypass volume settles first; the returning original fills the rest."""
    case = load_case()
    job_id = prepare(ws, case)
    primary = case["primary"]["volume_id"]
    bypass = case["bypass"]["volume_id"]
    with reject_confirmation(ws):
        ship(ws, job_id, primary)
    with volume_away(ws, primary):
        ws = Workspace(ws.root)
        shipped = ship_bypass(ws, job_id, bypass)
        during = progress(ws, job_id)
        if (shipped.status, during.confirmed_count) != ("partial", 1) or locations(
            during.locations
        ) != [[0, bypass, 0]]:
            raise AssertionError("bypass volume did not confirm ordinal 0 while the original was away")
        try:
            issue(ws, job_id)
        except IncompleteJob:
            pass
        else:
            raise AssertionError("issued while the original volume was still pending")
        if not retire(ws, bypass):
            raise AssertionError("bypass volume did not retire on its own slots")

    ws = Workspace(ws.root)
    if not settle_volume(ws, job_id, primary):
        raise AssertionError("returning original volume did not settle")
    receipt = issue(ws, job_id)
    expected = [[0, bypass, 0], [1, primary, 1], [2, primary, 2]]
    if (receipt.row_count, receipt.total, locations(receipt.lines)) != (3, 27, expected):
        raise AssertionError("bypass-first receipt does not match B:0, A:1, A:2")
    if not retire(ws, primary):
        raise AssertionError("original volume did not retire with its redundant slot")
    return {
        "settled_order": [bypass, primary],
        "receipt_locations": locations(receipt.lines),
        "receipt_total": receipt.total,
    }


def check_v3(ws):
    """The original settles first; the late bypass slot is only redundant."""
    case = load_case()
    job_id = prepare(ws, case)
    primary = case["primary"]["volume_id"]
    bypass = case["bypass"]["volume_id"]
    with reject_confirmation(ws):
        ship(ws, job_id, primary)
    with volume_away(ws, primary):
        ws = Workspace(ws.root)
        with reject_confirmation(ws):
            shipped = ship_bypass(ws, job_id, bypass)
        if shipped.status != "unconfirmed":
            raise AssertionError("blocked bypass confirmation did not report unconfirmed")
        if [(row.ordinal, row.slot) for row in read_mounted_rows(ws, bypass)] != [(0, 0)]:
            raise AssertionError("bypass row missing after the failed confirmation")

    ws = Workspace(ws.root)
    if not settle_volume(ws, job_id, primary):
        raise AssertionError("original volume did not settle first")
    receipt = issue(ws, job_id)
    expected = [[0, primary, 0], [1, primary, 1], [2, primary, 2]]
    if (receipt.row_count, receipt.total, locations(receipt.lines)) != (3, 27, expected):
        raise AssertionError("original-first receipt does not match A:0, A:1, A:2")
    if retire(ws, bypass):
        raise AssertionError("pending bypass volume retired before settling")
    if not settle_volume(ws, job_id, bypass):
        raise AssertionError("reopened bypass settlement did not keep B:0")
    if not retire(ws, bypass) or not retire(ws, primary):
        raise AssertionError("settled volumes did not retire")
    ws.volume_file(primary).unlink()
    ws.volume_file(bypass).unlink()
    ws = Workspace(ws.root)
    if get_receipt(ws, receipt.receipt_id) != receipt:
        raise AssertionError("original receipt changed on reopening")
    return {
        "settled_order": [primary, bypass],
        "receipt_locations": locations(receipt.lines),
        "receipt_total": receipt.total,
        "reopened_receipt": receipt.receipt_id,
    }


def check_v4(ws):
    """Both volumes short-write, the tail ships normally, and a mismatched
    returning volume stays pending without touching confirmed results."""
    mount(ws, "A", 2)
    mount(ws, "B", 1)
    mount(ws, "C", 1)
    batch = import_batch(ws, "bypass-tail", 1, [7, 7, 13])
    job_id = freeze_job(ws, batch.batch_id).job_id
    with reject_confirmation(ws):
        ship(ws, job_id, "A")
    with volume_away(ws, "A"):
        ws = Workspace(ws.root)
        if ship_bypass(ws, job_id, "B").confirmed_count != 1:
            raise AssertionError("bypass volume did not confirm its short write")
    ws = Workspace(ws.root)
    if not settle_volume(ws, job_id, "A"):
        raise AssertionError("short-written original volume did not settle")
    tail = ship(ws, job_id, "C")
    expected = [[0, "B", 0], [1, "A", 1], [2, "C", 0]]
    if tail.status != "complete" or locations(tail.locations) != expected:
        raise AssertionError("ordinary tail shipment did not close the job")
    receipt = issue(ws, job_id)
    if (receipt.row_count, receipt.total, locations(receipt.lines)) != (3, 27, expected):
        raise AssertionError("tail receipt mismatch")
    if not (retire(ws, "A") and retire(ws, "B") and retire(ws, "C")):
        raise AssertionError("settled volumes did not retire after the tail shipment")

    batch2 = import_batch(ws, "bypass-mismatch", 1, [7, 7, 13])
    job2 = freeze_job(ws, batch2.batch_id).job_id
    mount(ws, "D", 3)
    mount(ws, "E", 1)
    with reject_confirmation(ws):
        ship(ws, job2, "D")
    with ws.medium("D", write=True) as db:
        db.execute(
            "UPDATE medium_rows SET raw = ?, calibrated = ? WHERE ordinal = 1",
            (encode_reading(9), encode_reading(9)),
        )
    with volume_away(ws, "D"):
        ws = Workspace(ws.root)
        if ship_bypass(ws, job2, "E").confirmed_count != 1:
            raise AssertionError("second bypass volume did not confirm")
    ws = Workspace(ws.root)
    if settle_volume(ws, job2, "D"):
        raise AssertionError("mismatched original volume settled")
    if locations(progress(ws, job2).locations) != [[0, "E", 0]]:
        raise AssertionError("confirmed bypass row changed after the mismatch")
    try:
        issue(ws, job2)
    except IncompleteJob:
        pass
    else:
        raise AssertionError("issued with a mismatched volume still pending")
    if get_receipt(ws, receipt.receipt_id) != receipt:
        raise AssertionError("earlier receipt changed after the mismatch")
    return {
        "tail_locations": locations(receipt.lines),
        "tail_total": receipt.total,
        "mismatch_kept_pending": True,
    }


def main():
    results = {}
    for name, check in (("v1", check_v1), ("v2", check_v2), ("v3", check_v3), ("v4", check_v4)):
        with TemporaryDirectory(prefix="inspection-bypass-fixture-") as root:
            results[name] = check(Workspace(root))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
