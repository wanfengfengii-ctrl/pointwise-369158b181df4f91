from dataclasses import dataclass

from catalog.locations import ArchiveLocation
from catalog.progress import CatalogProgress
from workspace import EvidenceUnavailable


@dataclass(frozen=True)
class ShippingProgress:
    job_id: int
    status: str
    confirmed_count: int | None
    locations: tuple[ArchiveLocation, ...]


def resume_offset(confirmed: CatalogProgress) -> int:
    if confirmed.confirmed_count is None:
        raise EvidenceUnavailable('no confirmed resume offset')
    return confirmed.confirmed_count


def shipping_result(confirmed: CatalogProgress) -> ShippingProgress:
    count = confirmed.confirmed_count
    if count is None:
        status = 'unconfirmed'
    elif count == confirmed.total_rows:
        status = 'complete'
    else:
        status = 'partial'
    return ShippingProgress(confirmed.job_id, status, count, confirmed.locations)
