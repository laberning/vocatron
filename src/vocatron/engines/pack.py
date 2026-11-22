"""The zip writer: the MP3+G pair in one file with the same bytes every time (ADR-0030)."""

import os
import zipfile
from pathlib import Path

from vocatron.engines.protocols import PackRequest

UNIX = 3
"""The ``create_system`` of every member, so the bytes do not depend on the platform."""
FILE_MODE = 0o644
LEVEL = 9


class ZipPacker:
    """Writes a zip of the members in order, each deflated, with a fixed time stamp."""

    def pack(self, request: PackRequest) -> None:
        """Write the zip to a temporary file next to the target and rename it into place.

        Raises:
            OSError: If a member cannot be read or the zip cannot be written.
        """
        partial = request.target.with_name(f"{request.target.name}.part")
        try:
            with zipfile.ZipFile(
                partial, "w", zipfile.ZIP_DEFLATED, compresslevel=LEVEL
            ) as archive:
                for member in request.members:
                    info = zipfile.ZipInfo(member.name, request.time)
                    info.create_system = UNIX
                    info.external_attr = FILE_MODE << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    content = member.content
                    data = content if isinstance(content, bytes) else Path(content).read_bytes()
                    archive.writestr(info, data, zipfile.ZIP_DEFLATED, LEVEL)
            self._sync(partial)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(request.target)

    @staticmethod
    def _sync(path: Path) -> None:
        """Flush the written zip to disk before it is renamed."""
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
