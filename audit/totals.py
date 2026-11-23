from dataclasses import dataclass

from audit.reconcile import ReconciledLine


@dataclass(frozen=True)
class AuditTotals:
    row_count: int
    total: int


def calculate_totals(lines: tuple[ReconciledLine, ...]) -> AuditTotals:
    return AuditTotals(len(lines), sum(line.calibrated for line in lines if line.calibrated is not None))
