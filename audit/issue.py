from audit.receipts import ReceiptStore
from audit.reconcile import reconcile_job
from audit.totals import calculate_totals
from transfer.jobs import load_job


def issue(workspace, job_id):
    with workspace.operation(), workspace.center(write=True) as db:
        manifest = load_job(db, job_id)
        receipts = ReceiptStore(db)
        existing = receipts.for_job(job_id)
        if existing is not None:
            return existing
        lines = reconcile_job(db, manifest)
        return receipts.save(manifest, calculate_totals(lines), lines)
