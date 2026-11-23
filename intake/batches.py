from intake.records import make_intake_rows
from intake.storage import BatchSnapshot, BatchStore
from intake.validation import InvalidBatch, validate_batch_input


def import_batch(workspace, batch_id, multiplier, readings):
    raw = validate_batch_input(batch_id, multiplier, readings)
    batch = BatchSnapshot(batch_id, multiplier, make_intake_rows(raw, multiplier))
    with workspace.operation(), workspace.center(write=True) as db:
        store = BatchStore(db)
        if store.load(batch_id) is not None:
            raise InvalidBatch(f'batch already registered: {batch_id}')
        store.save(batch)
    return batch


def load_batch(workspace, batch_id):
    with workspace.center() as db:
        return BatchStore(db).load(batch_id)
