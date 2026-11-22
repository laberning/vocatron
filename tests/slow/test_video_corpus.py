"""Stage 2: the real song "Denkmal" laid out and rendered with the real tools (ADR-0009).

The work folder of the benchmark (``.corpus/bench/work``) already has the syllable times, so no AI
stage runs here and no GPU is used (the lyrics stage runs again on the CPU, to make ``lyrics.json``
in the current schema). The frames of a real song show its lyrics, which are
copyrighted: the golden frames live in ``.corpus/reference/denkmal/golden`` and the contact sheet
in ``reports/``, both git-ignored. The tests report numbers and verdicts only, never a line of
the lyrics (AGENTS.md), so every assertion message here is free of text.
"""

import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conformance.scene_rules import check_scene
from realworld import corpus_path, corpus_song, real_config
from videoreal import (
    BOX_TOLERANCE,
    SAME,
    contact_sheet,
    difference,
    frame_at,
    ink,
    visible_lines,
)
from vocatron.cli.app import real_engines
from vocatron.core.ass.parse import parse_ass
from vocatron.core.layout.file import LayoutFile
from vocatron.core.profiles.model import DEFAULT_PROFILE, parse_profile
from vocatron.core.render import RenderFile
from vocatron.core.scene import CardElement, CountdownElement, Scene
from vocatron.core.status import SongStatus
from vocatron.stages.batch import run_song
from vocatron.stages.songs import discover
from vocatron.stages.stage import Song

SONG = "Wir sind Helden - Denkmal"
REPORTS = Path(__file__).resolve().parents[2] / "reports"
UPDATE = os.environ.get("VOCATRON_UPDATE_GOLDEN") == "1"
VIDEO_STAGES = ("probe", "lyrics", "tempo", "layout", "render")

pytestmark = [pytest.mark.timeout(1200)]


def make_song(output: Path) -> tuple[Song, SongStatus, float]:
    """Make Denkmal from the benchmark's syllables in ``output``: song, status and seconds taken."""
    config = real_config(output, use_lrc_times=False)
    engines = real_engines()
    # the benchmark's work folder is made from the song in .corpus/songs, so the audio is that one
    (song,) = discover(corpus_song(SONG), config, engines)
    song.work_dir.mkdir(parents=True)
    # lyrics.json is made again by the lyrics stage (CPU, from the lyrics file next to the song),
    # so a change of its schema needs no new run of the benchmark
    for name in ("syllables.json", "song.json"):
        shutil.copy(corpus_path("bench", "work", SONG, name), song.work_dir / name)
    stems = corpus_path("bench", "work", SONG, "stems")
    (song.work_dir / "stems").symlink_to(stems, target_is_directory=True)
    started = time.monotonic()
    status = run_song(song, config, engines, force=False, only=VIDEO_STAGES)
    return song, status, time.monotonic() - started


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[Song, SongStatus, float]:
    """Denkmal made once for the tests that only look at the result."""
    return make_song(tmp_path_factory.mktemp("denkmal-video"))


def layout_of(song: Song) -> LayoutFile:
    return LayoutFile.model_validate_json((song.work_dir / "layout.json").read_text("utf-8"))


def numbers_only(check: Callable[..., object], *args: object) -> None:
    """Run a check and re-raise a failure with its message only (no locals, no lyrics)."""
    try:
        check(*args)
    except AssertionError as error:
        raise AssertionError(str(error)) from None


def moments(scene: Scene) -> dict[str, float]:
    lines = scene.lines()
    found = {
        "title": 1.0,
        "first-line": lines[0].sing_start + 0.5,
        "middle-line": lines[len(lines) // 2].sing_start + 0.5,
        "late-line": lines[(3 * len(lines)) // 4].sing_start + 0.5,
    }
    for element in scene.elements:
        if isinstance(element, CountdownElement) and "countdown" not in found:
            found["countdown"] = (element.start + element.end) / 2
        if isinstance(element, CardElement) and element.kind in {"break", "end"}:
            found.setdefault(element.kind, (element.start + element.end) / 2)
    return found


def test_the_song_is_made_without_an_ai_stage(made: tuple[Song, SongStatus, float]) -> None:
    song, status, _ = made
    assert status.error is None, "the video stages failed"
    assert status.state in {"ok", "review"}
    render = RenderFile.model_validate_json((song.work_dir / "render.json").read_text("utf-8"))
    assert render.fonts == ["NotoSans-Bold"]
    assert sorted(Path(song.output_dir / name).suffix for name in render.files) == [
        ".lrc",
        ".mp4",
    ]
    for name in render.files:
        assert (song.output_dir / name).stat().st_size > 1000


def test_the_rules_hold_on_the_real_scene_with_the_real_font(
    made: tuple[Song, SongStatus, float],
) -> None:
    song, _, _ = made
    layout = layout_of(song)
    text = (
        Path(__file__).resolve().parents[2] / f"src/vocatron/profiles/{DEFAULT_PROFILE}.yaml"
    ).read_text("utf-8")  # the song is made with the default look
    numbers_only(check_scene, layout.scene, parse_profile(DEFAULT_PROFILE, text))
    kinds: dict[str, int] = {}
    for found in layout.scene.shortfalls:
        kinds[found.kind] = kinds.get(found.kind, 0) + 1
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "denkmal-layout.json").write_text(
        json.dumps(
            {
                "lines": len(layout.scene.lines()),
                "shortfalls": kinds,
                "reasons": len(layout.reasons),
            }
        ),
        encoding="utf-8",
    )
    assert "too-wide" not in kinds
    assert "block" not in kinds


def test_the_ass_file_has_an_event_for_every_line(made: tuple[Song, SongStatus, float]) -> None:
    song, _, _ = made
    script = parse_ass((song.work_dir / "lyrics.ass").read_text("utf-8"))
    swept = [e for e in script.events if e.sweeps and e.size is not None]
    assert len(swept) == len(layout_of(song).scene.lines())


def test_the_frames_match_their_boxes_and_the_golden_frames_and_a_contact_sheet_is_written(
    made: tuple[Song, SongStatus, float], tmp_path: Path
) -> None:
    song, _, _ = made
    scene = layout_of(song).scene
    golden_dir = corpus_path("reference", "denkmal") / "golden"
    golden_dir.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    shots = {
        name: (
            moment,
            frame_at(song.work_dir / "lyrics.ass", scene, moment, tmp_path / f"{name}.png"),
        )
        for name, moment in moments(scene).items()
    }
    # the sheet first, so that a failing comparison below still leaves it for a human to look at
    contact_sheet([Image.fromarray(frame) for _, frame in shots.values()]).save(
        REPORTS / "contact-sheet-denkmal.png", optimize=True
    )
    created = 0
    for name, (moment, frame) in shots.items():
        for shown in visible_lines(scene, moment):
            found = ink(frame, scene.slots[shown.slot])
            assert found is not None, f"{name}: a slot is empty"
            assert found[0] >= shown.box.x - BOX_TOLERANCE, f"{name}: ink left of its box"
            assert found[2] <= shown.box.right + BOX_TOLERANCE, f"{name}: ink right of its box"
            assert found[1] >= shown.box.y - BOX_TOLERANCE, f"{name}: ink above its box"
            assert found[3] <= shown.box.bottom + BOX_TOLERANCE, f"{name}: ink below its box"
        golden = golden_dir / f"{name}.png"
        if UPDATE or not golden.is_file():
            Image.fromarray(frame).save(golden, optimize=True)
            created += 1
        else:
            share = difference(frame, np.asarray(Image.open(golden).convert("RGB")))
            assert share <= SAME, f"{name}: {share:.4%} of the pixels differ from the golden frame"
    assert created in {0, len(shots)}


def test_a_new_profile_value_renders_again_in_about_real_time_without_the_ai_stages(
    tmp_path: Path,
) -> None:
    song, _, first = make_song(tmp_path)  # its own song: this test changes the result
    config = real_config(tmp_path, use_lrc_times=False).model_copy(
        update={"profile_overrides": {"font": {"size": 0.1}}}
    )
    started = time.monotonic()
    status = run_song(song, config, real_engines(), force=False, only=VIDEO_STAGES)
    seconds = time.monotonic() - started
    assert status.error is None
    duration = layout_of(song).scene.duration
    log = (song.work_dir / "log.txt").read_text("utf-8")
    for stage in ("separation", "alignment", "syllables"):
        assert f"{stage}: running" not in log, f"{stage} ran"
    assert log.count("lyrics: running") == 1  # made with the song, not again for the re-render
    assert log.count("layout: running") == 2
    REPORTS.mkdir(exist_ok=True)
    timing = {
        "song_seconds": duration,
        "first_render_s": round(first, 1),
        "re_render_s": round(seconds, 1),
    }
    (REPORTS / "denkmal-timing.json").write_text(json.dumps(timing), encoding="utf-8")
    assert seconds <= duration, "the re-render took longer than the song"
