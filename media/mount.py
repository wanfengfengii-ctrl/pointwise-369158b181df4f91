import sqlite3

from catalog.volumes import VolumeRegistry
from media.capacity import validate_capacity, validate_volume_id
from media.records import MediumStore, VolumeHeader
from workspace import EvidenceUnavailable, InvalidVolume


def mount(workspace, volume_id, capacity):
    validate_volume_id(volume_id)
    validate_capacity(capacity)
    header = VolumeHeader(volume_id, capacity)
    name = workspace.volume_file(volume_id).name
    with workspace.operation():
        with workspace.center() as db:
            registered = VolumeRegistry(db).find(volume_id)
        if registered is not None and (
            registered.state != 'mounted'
            or registered.capacity != capacity
            or registered.medium_file != name
        ):
            raise InvalidVolume(f'incompatible registration for {volume_id}')

        try:
            if registered is not None:
                with workspace.medium(volume_id) as db:
                    store = MediumStore(db)
                    store.require_header(header)
                    store.occupied_slots(capacity)
                return registered

            with workspace.medium(volume_id, create=True) as db:
                store = MediumStore(db)
                store.initialize(header)
                if store.occupied_slots(capacity):
                    raise EvidenceUnavailable('unregistered medium already contains rows')
        except (EvidenceUnavailable, sqlite3.Error) as exc:
            raise InvalidVolume(f'cannot mount {volume_id}') from exc

        with workspace.center(write=True) as db:
            return VolumeRegistry(db).register_mounted(volume_id, capacity, name)
