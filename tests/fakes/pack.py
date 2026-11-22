"""A packer that records its requests and writes a small canned file into the in-memory store."""

from fakes.files import InMemoryFileStore
from vocatron.engines.protocols import PackRequest


class FakePacker:
    """Writes the member names and sizes as the "zip"; never compresses anything."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.requests: list[PackRequest] = []
        self.packed: dict[str, bytes] = {}  # what the members held, by name, of the last request

    def pack(self, request: PackRequest) -> None:
        self.requests.append(request)
        self.packed = {
            member.name: member.content
            if isinstance(member.content, bytes)
            else self.store.files[member.content]
            for member in request.members
        }
        listing = ", ".join(f"{name} {len(data)}" for name, data in self.packed.items())
        self.store.add(request.target, f"zip {listing}".encode())
