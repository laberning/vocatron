"""Stage 1: the ``lyrics`` commands on fakes, with the console output as golden text."""

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.lyrics import ENTCHEN, ENTCHEN_MESSY, HAENSCHEN, synced_of
from fakes.songs import FakeWorld, stored_status
from fakes.stages import NeedsModelStage
from fakes.streams import CLONE, Streams
from fakes.summary import summary_line
from vocatron.cli.commands import (
    run_lyrics,
    run_lyrics_approve,
    run_lyrics_show,
    run_make,
    run_status,
)
from vocatron.core.lyrics.versions import Candidate
from vocatron.core.song import Tags
from vocatron.stages import batch
from vocatron.stages.lyrics import LyricsStage
from vocatron.stages.probe import ProbeStage

MUSIC = Path("/music")


@pytest.fixture
def mixed(world: FakeWorld) -> FakeWorld:
    world.add_song(MUSIC / "a.mp3", tags=Tags("Volkslied", "Entchen", 180), lyrics=ENTCHEN)
    world.add_song(MUSIC / "b.mp3", tags=Tags("Volkslied", "Messy", 180), lyrics=ENTCHEN_MESSY)
    world.add_song(MUSIC / "c.mp3", tags=Tags("Volkslied", "Nothing", 180), lyrics=None)
    world.add_song(MUSIC / "d.mp3", tags=Tags("Volkslied", "Found", 180), lyrics=None)
    world.lyrics.records = [
        Candidate(
            source_id=number, artist="Volkslied", title="Found", duration=180.0, plain=HAENSCHEN
        )
        for number in (1, 2)
    ]
    return world


def lyrics(world: FakeWorld, *, force: bool = False) -> tuple[int, Streams]:
    streams = Streams(world)
    code = run_lyrics(MUSIC, output=None, config_file=None, force=force, edges=streams.edges)
    return code, streams


def test_lyrics_runs_probe_and_lyrics_only_and_prints_a_line_per_song(
    mixed: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    code, streams = lyrics(mixed)
    assert code == 1  # one song has no lyrics
    assert streams.out.getvalue() == snapshot
    assert mixed.language.texts  # the language was looked at
    outside = {p for p in mixed.store.writes if MUSIC / "karaoke" not in p.parents}
    assert {p.name for p in outside if CLONE not in p.parents} == {"d.txt"}  # not the learnt speeds


def test_lyrics_and_show_warn_about_a_line_time_out_of_order(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("Volkslied", "Entchen", 180), lyrics=None)
    typo = synced_of(ENTCHEN).replace("[00:13.00]", "[02:23.00]")
    world.store.add(MUSIC / "a.lrc", ("[length: 03:01]\n" + typo).encode())
    _, streams = lyrics(world)
    note = "line 3: time 02:23.00 is out of order, skipped"
    assert f"warning: Volkslied - Entchen: {note}" in streams.out.getvalue()
    shown = Streams(world)
    run_lyrics_show(MUSIC, output=None, config_file=None, edges=shown.edges)
    assert f"warning: {note}" in shown.out.getvalue()


def test_show_prints_status_reasons_and_flagged_lines(
    mixed: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    lyrics(mixed)
    streams = Streams(mixed)
    assert run_lyrics_show(MUSIC, output=None, config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue() == snapshot


def test_show_before_any_run_says_not_run(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    assert run_lyrics_show(MUSIC, output=None, config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue().startswith("not run")
    assert world.store.writes == []


def test_approve_makes_a_song_with_doubts_ok(mixed: FakeWorld) -> None:
    lyrics(mixed)
    streams = Streams(mixed)
    only_b = MUSIC / "b.mp3"
    code = run_lyrics_approve(only_b, output=None, config_file=None, edges=streams.edges)
    assert code == 0
    assert streams.out.getvalue() == "approved Volkslied - Messy\n"
    status = Streams(mixed)
    run_status(MUSIC, output=None, config_file=None, edges=status.edges)
    assert summary_line(status.out.getvalue(), "ok", "Volkslied - Messy")


def test_approve_says_why_it_cannot(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    code = run_lyrics_approve(MUSIC, output=None, config_file=None, edges=streams.edges)
    assert code == 1
    assert "error: Artist - Title: there is no lyrics.json yet" in streams.err.getvalue()


def test_usage_errors_exit_with_two(world: FakeWorld) -> None:
    streams = Streams(world)
    assert run_lyrics_show(MUSIC / "x", output=None, config_file=None, edges=streams.edges) == 2
    assert run_lyrics_approve(MUSIC / "x", output=None, config_file=None, edges=streams.edges) == 2
    assert "does not exist" in streams.err.getvalue()


class LaterStage(NeedsModelStage):
    """A stage after the lyrics that needs no model."""

    name = "later"
    models = ()
    output = "later.json"


def test_lyrics_and_approve_keep_the_recorded_results_of_later_stages(
    mixed: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), LyricsStage(), LaterStage()))
    only_b = MUSIC / "b.mp3"
    streams = Streams(mixed)
    assert run_make(only_b, output=None, config_file=None, edges=streams.edges) == 0
    lyrics(mixed)
    assert run_lyrics_approve(only_b, output=None, config_file=None, edges=streams.edges) == 0
    status = stored_status(mixed, only_b)
    assert status is not None
    assert [(o.stage, o.action) for o in status.stages] == [
        ("probe", "skipped"),
        ("lyrics", "skipped"),
        ("later", "ran"),  # recorded by make, kept by lyrics and approve
    ]
    assert status.state == "ok"


def test_approve_takes_the_language_of_the_check_and_reports_a_failed_refresh(
    mixed: FakeWorld,
) -> None:
    only_b = MUSIC / "b.mp3"
    mixed.language.language = None  # the detection cannot tell, so the fan names the language
    code = run_lyrics(
        only_b,
        output=None,
        config_file=None,
        force=False,
        language="de",
        edges=Streams(mixed).edges,
    )
    assert code == 0
    streams = Streams(mixed)
    assert run_lyrics_approve(only_b, output=None, config_file=None, edges=streams.edges) == 1
    assert "the song failed after the approval: cannot tell the language" in streams.err.getvalue()
    streams = Streams(mixed)
    code = run_lyrics_approve(
        only_b, output=None, config_file=None, language="de", edges=streams.edges
    )
    assert (code, streams.err.getvalue()) == (0, "")
    status = stored_status(mixed, only_b)
    assert status is not None
    assert status.state == "ok"


def test_make_warns_on_the_console_about_the_time_the_alignment_skipped(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("Volkslied", "Entchen", 180), lyrics=None)
    typo = synced_of(ENTCHEN).replace("[00:13.00]", "[02:23.00]")
    world.store.add(MUSIC / "a.lrc", ("[length: 03:01]\n" + typo).encode())
    world.acoustic.jitter = {2: -130.0}  # sung where it always was
    streams = Streams(world)
    run_make(MUSIC, output=None, config_file=None, edges=streams.edges)
    note = "warning: Volkslied - Entchen: line 3: time 02:23.00 is out of order, skipped"
    assert streams.out.getvalue().count(note) == 1
