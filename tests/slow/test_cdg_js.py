"""Stage 2: the JavaScript decoder cdgraphics, run unchanged by Node, shows our frames (ADR-0025).

An optional third opinion: it needs ``node`` (20 or newer) and ``make cdg-js``; without them the
test is skipped with the reason. The library is never ported or copied (see ``THIRD_PARTY.md``).
"""

from pathlib import Path

import pytest

from cdgreal import differing, entchen_stream, js_frames, node_problem, our_frames, sample_packets

pytestmark = [
    pytest.mark.skipif(node_problem() is not None, reason=node_problem() or ""),
    pytest.mark.timeout(600),
]


def test_cdgraphics_shows_the_frames_our_decoder_shows(tmp_path: Path) -> None:
    scene, result = entchen_stream()
    file = tmp_path / "Song.cdg"
    file.write_bytes(result.stream)
    packets = sample_packets(scene, result.stream)
    ours, theirs = our_frames(result.stream, packets), js_frames(file, packets)
    differences = differing(packets, ours, theirs)
    assert differences == []  # packet and pixels that differ, if any
