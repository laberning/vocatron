"""Stage 1: the CD+G stream of every classic look on the folk songs, decoded back (ADR-0023).

The writer's output goes through our own decoder (the model of the screen): at the ticks the
scheduler reports as settled the decoded frame is exactly the target frame, every line is drawn
before its first syllable, the wipe is never more than a tile column or 50 ms behind the scene's
``wipe_front``, and nothing is drawn outside the safe area.
"""

import math
from itertools import product

import numpy as np
import pytest

from fakes.resources import FakeResources
from vocatron.core.cdg import PACKET_SIZE, PACKETS_PER_SECOND, CdgOp, CdgScreen, decode
from vocatron.core.cdg.fit import MAX_WIPE_LAG, fit_stream
from vocatron.core.cdg.packet import parse_packets
from vocatron.core.cdg.palette import Palette, build_title_palette
from vocatron.core.cdg.stream import BORDER_REPEATS, MEMORY_REPEATS, CdgStream
from vocatron.core.layout import sample
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.profiles.model import CLASSIC_PROFILES, parse_profile
from vocatron.core.scene import LineElement, Scene
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser

TILE = (CdgOp.TILE, CdgOp.TILE_XOR)
MAX_LAG_PIXELS = 6
MAX_LAG_SECONDS = MAX_WIPE_LAG


RESOURCES = FakeResources()
FONT = RESOURCES.font_file()
SONGS = {
    "entchen": sample.entchen_piece,
    "duet": sample.duet_piece,
    "turns": lambda: sample.duet_piece(sample.DUET_TURNS),
}


@pytest.fixture(
    scope="module", params=[f"{look}-{song}" for look, song in product(CLASSIC_PROFILES, SONGS)]
)
def written(request: pytest.FixtureRequest) -> tuple[Scene, CdgStream]:
    """A look and a song written for CD+G through the one shared path (the real font)."""
    look, song = request.param.rsplit("-", 1)
    timed, text = SONGS[song]()
    profile = parse_profile(look, RESOURCES.builtin_profile(look) or "")
    phrases = phrases_from(timed.words, timed.lines, profile.font.case)
    fit = fit_stream(phrases, text, profile, PillowMeasurer(FONT), PillowRasteriser(FONT))
    assert fit.step.number == 0, "the folk songs need no fallback step"
    return fit.scene, fit.written


def test_the_file_is_whole_packets_and_covers_the_scene(written: tuple[Scene, CdgStream]) -> None:
    scene, result = written
    assert len(result.stream) % PACKET_SIZE == 0
    assert result.packets == math.ceil(scene.duration * PACKETS_PER_SECOND)
    assert result.scheduled.drawing_packets == len(list(parse_packets(result.stream)))
    assert (
        result.scheduled.drawing_packets <= result.packets
    )  # one packet per slot, by construction


def test_the_stream_starts_with_the_colour_table_and_the_presets(
    written: tuple[Scene, CdgStream],
) -> None:
    scene, result = written
    events = decode(result.stream).events
    head = [e.op for e in events[: 2 + MEMORY_REPEATS + BORDER_REPEATS]]
    # the repeats of the memory preset are ignored by the decoder: they leave no event
    assert head[:2] == [CdgOp.PALETTE, CdgOp.PALETTE]
    assert CdgOp.MEMORY_PRESET in head and CdgOp.BORDER_PRESET in head
    raw = list(parse_packets(result.stream))
    memory = [p for p in raw[: 2 + MEMORY_REPEATS + BORDER_REPEATS] if p.instruction == 1]
    assert [p.data[1] for p in memory] == list(range(MEMORY_REPEATS))
    screen = CdgScreen()
    for packet in raw[:2]:
        screen.apply(packet)
    # a start screen with the wordmark has its own palette first (ADR-0056)
    first = build_title_palette(scene) or result.palette
    assert screen.palette == list(first.entries)


def test_the_stream_draws_only_inside_the_safe_area(written: tuple[Scene, CdgStream]) -> None:
    _, result = written
    tiles = [e for e in decode(result.stream).events if e.op in TILE]
    assert tiles
    assert {e.row for e in tiles} <= set(range(1, 17))  # the border ring is rows 0 and 17
    assert {e.column for e in tiles} <= set(range(1, 49))  # and columns 0 and 49
    final = decode(result.stream, [1e6]).frames[0]
    assert (final[:12] == 0).all() and (final[-12:] == 0).all()
    assert (final[:, :6] == 0).all() and (final[:, -6:] == 0).all()


def test_the_decoded_frames_are_exactly_the_target_frames_where_the_scheduler_has_settled(
    written: tuple[Scene, CdgStream],
) -> None:
    _, result = written
    settled = result.scheduled.settled
    assert len(settled) > 0.8 * result.targets.ticks  # the queue is empty most of the time
    chosen = settled[:: max(1, len(settled) // 120)]
    decoded = decode(result.stream, [(k + 1) / 100 - 1 / 600 for k in chosen])
    wrong = [
        k
        for k, shown in zip(chosen, decoded.frames, strict=True)
        if not np.array_equal(shown, result.targets.frame(k))
    ]
    assert wrong == []


def test_every_line_is_fully_drawn_before_its_first_syllable_starts(
    written: tuple[Scene, CdgStream],
) -> None:
    scene, result = written
    for index, line in enumerate(scene.lines()):
        moment = line.sing_start - 1 / PACKETS_PER_SECOND
        shown = decode(result.stream, [moment]).frames[0]
        wanted = result.targets.frame(int(line.sing_start * 100) - 1)
        top, bottom = int(line.box.y) - 2, int(line.box.bottom) + 2
        assert np.array_equal(shown[top:bottom], wanted[top:bottom]), f"line {index}"


def sung_columns(frame: np.ndarray, line: LineElement, palette: Palette) -> set[int]:
    """Return the columns of the line's rows that hold sung ink or shade, in any of its colours."""
    sung = {
        index
        for colour in (line.colours.sung, *(turn.colours.sung for turn in line.turns))
        for index in palette.ink(colour)
    }
    rows = frame[int(line.box.y) : int(line.box.bottom) + 1]
    return {int(c) for c in np.nonzero(np.isin(rows, list(sung)).any(axis=0))[0]}


def test_the_wipe_is_never_more_than_a_tile_column_or_50_ms_behind_the_scene(
    written: tuple[Scene, CdgStream],
) -> None:
    """Every ink column the wipe passed 6 px ago, or 50 ms ago, is sung (whichever is less)."""
    scene, result = written
    for line in scene.lines():
        final = decode(result.stream, [line.sing_end + 0.5]).frames[0]
        ink = sorted(sung_columns(final, line, result.palette))
        origin = round(line.text_x)
        times = [float(t) for t in np.arange(line.sing_start, line.sing_end, 0.025)]
        for time, frame in zip(times, decode(result.stream, times).frames, strict=True):
            sung = sung_columns(frame, line, result.palette)
            front = origin + line.wipe_front(time, scene.look)
            earlier = origin + line.wipe_front(time - MAX_LAG_SECONDS, scene.look)
            due = min(front - MAX_LAG_PIXELS, earlier)
            assert [c for c in ink if c < due and c not in sung] == [], f"{time:.3f}"


def test_the_stage_file_numbers_are_the_measured_lags(written: tuple[Scene, CdgStream]) -> None:
    _, result = written
    scheduled = result.scheduled
    assert scheduled.wipe_lag <= MAX_LAG_SECONDS
    assert 0 < scheduled.draw_lag < 2.0  # about a second of drawing, far inside the lead-ins
