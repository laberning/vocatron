"""Stage 1: the tempo stage on a fake audio reader, and how the layout and the report use it."""

from pathlib import Path

import pytest

from fakes.clicks import drum_pattern
from fakes.songs import FakeWorld
from vocatron.core.errors import StageError
from vocatron.core.layout.file import LayoutFile
from vocatron.core.report import CountdownNote, ReportFile
from vocatron.core.scene import CardElement, CountdownElement
from vocatron.core.separation.file import stem_path
from vocatron.core.stage_file import hash_bytes
from vocatron.core.tempo import SAMPLE_RATE, TempoFile
from vocatron.stages.config import Config
from vocatron.stages.stage import AUDIO, LOG_FILE
from vocatron.stages.tempo import INSTRUMENTAL, TEMPO_FILE, TempoStage

MUSIC = Path("/music")
SONG = MUSIC / "Artist - Title.mp3"
WORK = MUSIC / "karaoke" / "Artist - Title"
BPM = 100.0


@pytest.fixture
def beating(one: FakeWorld) -> FakeWorld:
    """A world whose instrumental stem is a drum pattern at 100 BPM."""
    one.audio.samples = drum_pattern(BPM, seconds=30)
    return one


def tempo_of(world: FakeWorld) -> TempoFile:
    return TempoFile.model_validate_json(world.store.read_text(WORK / TEMPO_FILE) or "")


def layout_of(world: FakeWorld) -> LayoutFile:
    return LayoutFile.model_validate_json(world.store.read_text(WORK / "layout.json") or "")


def countdowns(world: FakeWorld) -> list[CountdownElement]:
    return [e for e in layout_of(world).scene.elements if isinstance(e, CountdownElement)]


def logged(world: FakeWorld, text: str) -> bool:
    """Whether the song log has a line ending with ``text`` (the lines start with the time)."""
    return any(line.endswith(text) for line in world.store.log_lines(WORK / LOG_FILE))


def actions(world: FakeWorld, config: Config | None = None) -> dict[str, str]:
    status = world.run(SONG, config)
    return {o.stage: o.action for o in status.stages}


def test_the_stage_reads_the_instrumental_stem_as_mono_22_khz(beating: FakeWorld) -> None:
    assert beating.run(SONG).state == "ok"
    assert beating.audio.requests == [(WORK / INSTRUMENTAL, SAMPLE_RATE, 1)]
    assert stem_path("instrumental") == INSTRUMENTAL


def test_it_writes_the_tempo_and_logs_it(beating: FakeWorld) -> None:
    beating.run(SONG)
    found = tempo_of(beating)
    assert found.bpm == pytest.approx(BPM, rel=0.02)
    assert found.clarity > 0.5
    assert found.reasons == []
    assert logged(beating, f"tempo: {found.bpm:.1f} BPM (clarity {found.clarity:.2f})")


def test_a_song_without_a_clear_tempo_has_none_and_is_not_a_review(one: FakeWorld) -> None:
    status = one.run(SONG)  # the fake reader hands out silence
    assert status.state == "ok"
    assert tempo_of(one).bpm is None
    assert tempo_of(one).reasons == []
    assert logged(one, "tempo: tempo unclear (clarity 0.00)")


def test_the_stem_is_the_only_input_and_the_stage_has_no_settings() -> None:
    stage = TempoStage()
    assert stage.inputs == (INSTRUMENTAL,)
    assert AUDIO not in stage.inputs
    assert stage.output == TEMPO_FILE
    assert stage.settings_from(Config()).model_dump() == {}


def test_the_fingerprint_holds_the_hash_of_the_stem_and_the_stage_version(
    beating: FakeWorld,
) -> None:
    beating.run(SONG)
    stem = beating.store.files[WORK / INSTRUMENTAL]
    fingerprint = tempo_of(beating).fingerprint
    assert fingerprint.inputs == {INSTRUMENTAL: hash_bytes(stem)}
    assert fingerprint.stage_version == TempoStage.version


def test_a_second_run_skips_it(beating: FakeWorld) -> None:
    beating.run(SONG)
    assert actions(beating)["tempo"] == "skipped"
    assert len(beating.audio.requests) == 1


def test_a_changed_stem_runs_it_again_and_the_layout_after_it(beating: FakeWorld) -> None:
    beating.run(SONG)
    beating.store.add(WORK / INSTRUMENTAL, b"another instrumental")
    ran = actions(beating)
    assert (ran["tempo"], ran["layout"]) == ("ran", "ran")
    assert ran["alignment"] == "skipped"


def test_a_changed_tempo_runs_the_layout_again(beating: FakeWorld) -> None:
    beating.run(SONG)
    beating.audio.samples = drum_pattern(140.0, seconds=30)
    beating.store.add(WORK / INSTRUMENTAL, b"a faster instrumental")
    beating.run(SONG)
    assert tempo_of(beating).bpm == pytest.approx(140.0, rel=0.02)
    beats = [c.beat for c in countdowns(beating)]
    assert beats
    assert all(beat == pytest.approx(60.0 / 140.0, abs=0.01) for beat in beats)  # 1.7 s: fits


def test_a_stem_that_cannot_be_read_fails_only_this_stage(beating: FakeWorld) -> None:
    beating.audio.fail_with = StageError("decode-failed", "ffmpeg could not decode the stem")
    status = beating.run(SONG)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("tempo", "decode-failed")
    assert (WORK / "alignment.json") not in beating.store.files


def test_the_layout_counts_beats_when_the_tempo_is_clear(beating: FakeWorld) -> None:
    beating.run(SONG)
    found = countdowns(beating)
    assert found
    bpm = tempo_of(beating).bpm
    assert bpm is not None
    assert layout_of(beating).scene.bpm == bpm  # rule 13 checks the beat of tempo.json
    assert all(c.beat == pytest.approx(0.6, abs=0.02) for c in found)  # 4 beats = 2.4 s
    # one countdown, after the title screen: it ends a beat before the line (ADR-0028) and
    # counts the whole beats that fit after the title, at most four (ADR-0026)
    scene = layout_of(beating).scene
    (countdown,) = found
    beat = countdown.beat or 0.0
    (title,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title"]
    assert countdown.end == pytest.approx(scene.lines()[0].sing_start - beat, abs=0.002)
    assert countdown.count == min(4, int((countdown.end - title.end) / beat + 1e-6))
    assert countdown.end - countdown.start == pytest.approx(countdown.count * beat, abs=0.002)
    assert logged(beating, f"layout: countdowns count beats at {bpm:.1f} BPM")


def test_the_layout_counts_seconds_when_the_tempo_is_unclear(one: FakeWorld) -> None:
    one.run(SONG)
    found = countdowns(one)
    assert found
    assert {c.beat for c in found} == {None}
    assert layout_of(one).scene.bpm is None
    assert logged(one, "layout: countdowns run over 2.4 s (tempo unclear)")


def report_of(world: FakeWorld) -> ReportFile:
    return ReportFile.model_validate_json(world.store.read_text(WORK / "report.json") or "")


def test_the_report_notes_beats_and_the_tempo(beating: FakeWorld) -> None:
    beating.run(SONG)
    note = report_of(beating).countdown
    assert note is not None
    assert note.unit == "beats"
    assert note.tempo == pytest.approx(BPM, rel=0.02)


def test_the_report_notes_seconds_without_making_the_song_a_review(one: FakeWorld) -> None:
    status = one.run(SONG)
    report = report_of(one)
    assert report.countdown == CountdownNote(tempo=None, unit="seconds")
    assert (status.state, report.status, report.reasons) == ("ok", "ok", [])
