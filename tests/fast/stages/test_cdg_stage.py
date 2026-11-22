"""Stage 1: the cdg stage on fakes: when it runs, what it writes and what it leaves alone."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import JsonValue

from fakes.songs import FakeWorld
from vocatron.core.cdg import decode, parse_packets
from vocatron.core.cdg.file import CdgFile
from vocatron.core.errors import StageError
from vocatron.core.id3 import id3_tag
from vocatron.core.layout.file import LayoutFile
from vocatron.core.render import RenderFile
from vocatron.core.song import Tags
from vocatron.core.stage_file import make_fingerprint
from vocatron.core.status import SongStatus
from vocatron.stages.batch import run_song
from vocatron.stages.cdg import CdgStage
from vocatron.stages.config import Config
from vocatron.stages.layout import LayoutStage

AUDIO = Path("/music/Artist - Title.mp3")
OUT = Path("/music/karaoke")
WORK = OUT / "Artist - Title"
TWO_LINE = "two-line-turns"  # the look the timing numbers below are written for
BOTH = Config(outputs=["mp4", "cdg"], profile=TWO_LINE)


def run(world: FakeWorld, config: Config | None = None) -> SongStatus:
    cfg = config or Config(profile=TWO_LINE)
    return run_song(world.song(AUDIO, cfg), cfg, world.engines, force=False)


def actions(status: SongStatus) -> dict[str, str]:
    return {outcome.stage: outcome.action for outcome in status.stages}


def cdg_file(world: FakeWorld) -> CdgFile:
    return CdgFile.model_validate_json(world.store.read_text(WORK / "cdg.json") or "")


def test_by_default_no_cdg_work_is_done_and_no_file_is_made(one: FakeWorld) -> None:
    status = run(one)
    assert status.state == "ok"
    assert one.store.size(OUT / "Artist - Title.cdg") is None
    assert one.store.size(OUT / "Artist - Title.mp3") is None
    assert one.mp3.requests == [] and one.rasteriser.requests == []
    stored = cdg_file(one)
    assert (stored.enabled, stored.files, stored.packets) == (False, [], 0)


def test_with_cdg_in_the_outputs_the_mp3_and_the_cdg_file_are_written_next_to_the_video(
    one: FakeWorld,
) -> None:
    status = run(one, BOTH)
    assert status.state == "ok"
    for name in ("mp4", "mp3", "cdg"):
        assert one.store.size(OUT / f"Artist - Title.{name}") is not None, name
    stored = cdg_file(one)
    assert stored.enabled and stored.files == ["Artist - Title.mp3", "Artist - Title.cdg"]
    assert stored.profile == "two-line-turns"
    assert len(stored.palette) == 16 and all(len(c) == 7 for c in stored.palette)
    data = one.store.files[OUT / "Artist - Title.cdg"]
    assert len(data) == stored.packets * 24
    assert stored.drawing_packets == len(list(parse_packets(data))) > 100


def test_the_mp3_is_the_karaoke_stem_with_the_silent_intro(one: FakeWorld) -> None:
    run(one, BOTH)
    (request,) = one.mp3.requests
    layout = LayoutFile.model_validate_json(one.store.read_text(WORK / "layout.json") or "")
    assert request.source == WORK / "stems" / "karaoke.flac"
    assert request.target == OUT / "Artist - Title.mp3"
    assert request.lead == layout.scene.lead == 7.0
    assert request.duration == 180.0 + request.lead


def test_the_file_covers_the_song_and_the_intro_and_the_log_says_what_was_made(
    one: FakeWorld,
) -> None:
    run(one, BOTH)
    stored = cdg_file(one)
    assert stored.packets == round((180.0 + 7.0) * 300)
    log = "\n".join(one.store.log_lines(WORK / "log.txt"))
    assert f"cdg: {stored.packets} packets" in log
    assert "worst lag" in log and "Artist - Title.cdg" in log


def test_the_file_header_is_the_palette_the_stage_file_names(one: FakeWorld) -> None:
    run(one, BOTH)
    stored = cdg_file(one)
    events = decode(one.store.files[OUT / "Artist - Title.cdg"]).events
    loads = [e.colours for e in events if e.op.name == "PALETTE"]

    def hexes(colours: tuple[tuple[int, int, int], ...]) -> list[str]:
        return ["#" + "".join(f"{v * 17:02x}" for v in c) for c in colours]

    # the start screen's palette comes first, the song's replaces it when the screen ends
    assert len(loads) == 4
    assert hexes(loads[2] + loads[3]) == stored.palette
    assert hexes(loads[0] + loads[1]) != stored.palette


def test_the_lags_are_recorded_and_stay_inside_the_lead_in(one: FakeWorld) -> None:
    run(one, BOTH)
    stored = cdg_file(one)
    assert 0 < stored.draw_lag < 1.0
    assert 0 <= stored.wipe_lag <= 0.05


def test_turning_cdg_on_makes_it_without_rendering_the_video_again(one: FakeWorld) -> None:
    run(one)
    assert len(one.renderer.requests) == 1
    status = run(one, BOTH)
    assert actions(status)["render"] == "skipped" and actions(status)["layout"] == "skipped"
    assert actions(status)["cdg"] == "ran"
    assert len(one.renderer.requests) == 1
    assert one.store.size(OUT / "Artist - Title.cdg") is not None


def test_turning_cdg_off_again_runs_only_the_cdg_stage_and_keeps_the_files(
    one: FakeWorld,
) -> None:
    run(one, BOTH)
    status = run(one)
    assert actions(status)["cdg"] == "ran" and actions(status)["render"] == "skipped"
    assert len(one.renderer.requests) == 1
    assert cdg_file(one).files == []
    assert one.store.size(OUT / "Artist - Title.cdg") is not None  # never deleted behind the back


def test_a_second_run_skips_the_stage(one: FakeWorld) -> None:
    run(one, BOTH)
    status = run(one, BOTH)
    assert actions(status)["cdg"] == "skipped"
    assert len(one.mp3.requests) == 1


def test_a_missing_mp3_or_cdg_file_makes_the_stage_run_again_and_only_it(one: FakeWorld) -> None:
    run(one, BOTH)
    for name in ("mp3", "cdg"):
        one.store.delete(OUT / f"Artist - Title.{name}")
        status = run(one, BOTH)
        assert actions(status)["cdg"] == "ran", name
        assert actions(status)["render"] == "skipped", name
        assert one.store.size(OUT / f"Artist - Title.{name}") is not None
    log = "\n".join(one.store.log_lines(WORK / "log.txt"))
    assert "cdg: Artist - Title.mp3 missing" in log
    assert len(one.renderer.requests) == 1


def test_a_changed_profile_runs_the_stage_only_while_cdg_is_on(one: FakeWorld) -> None:
    run(one, Config(profile=TWO_LINE))
    off = run(one, Config(profile="four-line-stack"))
    assert actions(off)["cdg"] == "skipped"  # the profile does not count while it is off
    run(one, BOTH)
    other = run(one, Config(outputs=["mp4", "cdg"], profile="four-line-stack"))
    assert actions(other)["cdg"] == "ran"
    assert cdg_file(one).profile == "four-line-stack"


def test_a_new_layout_version_makes_the_cdg_files_again_while_cdg_is_on(
    one: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(one)
    monkeypatch.setattr(LayoutStage, "version", LayoutStage.version + 1)
    assert actions(run(one))["cdg"] == "skipped"  # off: nothing to make again
    run(one, BOTH)
    monkeypatch.setattr(LayoutStage, "version", LayoutStage.version + 1)
    status = run(one, BOTH)
    assert actions(status)["layout"] == "ran" and actions(status)["cdg"] == "ran"
    assert len(one.mp3.requests) == 2


def test_the_stage_refuses_to_write_over_the_song(one: FakeWorld) -> None:
    ctx = one.context(AUDIO)
    # the output folder is the folder of the song, so Artist - Title.mp3 is the song itself
    refused = replace(ctx, song=replace(ctx.song, output_dir=AUDIO.parent))
    stage = CdgStage()
    settings = stage.settings_from(BOTH)
    with pytest.raises(StageError, match=r"Artist - Title\.mp3") as error:
        stage.run(refused, settings, make_fingerprint({}, settings, stage.version))
    assert error.value.kind == "output-collision"
    assert one.mp3.requests == []
    assert one.store.files[AUDIO] == AUDIO.name.encode()  # the song is untouched


QUICK = (  # an LRC whose lines follow each other at once
    "[00:01.00] Alle meine Entchen\n[00:04.00] schwimmen auf dem See\n"
    "[00:07.00] schwimmen auf dem See\n[00:10.00] Köpfchen in das Wasser\n"
    "[00:13.00] Schwänzchen in die Höh\n"
)
CHOIR = (  # an LRC with every singer and the group
    "[00:01.00] {1} Hänschen klein\n[00:04.00] {2} ging allein\n"
    "[00:07.00] {3} in die weite Welt hinein\n[00:10.00] {4} Stock und Hut\n"
    "[00:13.00] {5} steht ihm gut\n[00:16.00] {all} macht sich auf den Weg\n"
)


def test_a_look_with_too_many_colours_fails_with_cdg_palette_and_names_them(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), CHOIR.encode())
    unsung = {f"singer{n}": {"unsung": f"#{n}{n}eeee"} for n in range(1, 6)}
    status = run(world, Config(outputs=["mp4", "cdg"], profile_overrides={"colours": unsung}))
    assert status.state == "failed" and status.error is not None
    assert (status.error.stage, status.error.kind) == ("cdg", "cdg-palette")
    assert "#11eeee" in status.error.message  # the colours are named
    assert world.store.size(OUT / "Artist - Title.mp4") is not None  # the video is safe
    assert world.store.size(OUT / "Artist - Title.cdg") is None


def test_the_same_choir_with_one_unsung_colour_fits_the_palette(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), CHOIR.encode())
    assert run(world, BOTH).state in {"ok", "review"}
    assert len(cdg_file(world).palette) == 16


def test_a_failing_mp3_encoder_fails_the_stage_with_its_error(one: FakeWorld) -> None:
    one.mp3.fail_with = StageError("missing-tool", "this ffmpeg has no MP3 encoder")
    status = run(one, BOTH)
    assert status.state == "failed" and status.error is not None
    assert (status.error.stage, status.error.kind) == ("cdg", "missing-tool")
    assert one.store.size(OUT / "Artist - Title.mp4") is not None  # the video is safe


def test_what_the_layout_could_not_do_on_the_cdg_screen_goes_to_the_song_log(
    one: FakeWorld,
) -> None:
    overrides = {
        "cdg": {"font_px": 76, "min_font_px": 76},
        "lead_in": {"min": 1, "target": 1, "max": 1},
    }
    status = run(one, Config(outputs=["mp4", "cdg"], profile_overrides=overrides))
    assert status.state in {"ok", "review"}
    log = "\n".join(one.store.log_lines(WORK / "log.txt"))
    assert "cdg: shortfall (" in log
    assert "cdg: rule " in log  # the layout rules run on the CD+G scene too


def test_the_stage_lists_nothing_for_a_stage_file_of_another_stage(one: FakeWorld) -> None:
    run(one)
    other = one.store.read_text(WORK / "render.json") or ""
    assert CdgStage().products(one.context(AUDIO), RenderFile.model_validate_json(other)) == ()


def test_the_mp3_gets_the_same_tags_as_the_video(one: FakeWorld) -> None:
    run(one, BOTH)
    (request,) = one.mp3.requests
    assert request.tags == one.renderer.requests[0].tags
    assert dict(request.tags)["artist"] == "Artist"


def test_a_song_with_two_singers_gets_the_word_duet_in_the_tags_of_the_mp3(
    one: FakeWorld,
) -> None:
    path = Path("/music/Pair.mp3")
    one.add_song(path, lyrics="{1} Hänschen klein\n{2} ging allein\n")
    one.run(path, BOTH)
    (request,) = one.mp3.requests
    assert request.tags[-1] == ("tag", "Duet")
    assert one.renderer.requests[-1].tags == request.tags


def test_a_song_without_an_artist_gets_no_artist_tag_in_the_mp3(one: FakeWorld) -> None:
    path = Path("/music/Solo.mp3")
    one.add_song(path, tags=Tags(None, "Solo", 180.0))
    one.run(path, BOTH)
    (request,) = one.mp3.requests
    assert [key for key, _ in request.tags] == ["title", "genre", "comment"]


@pytest.mark.parametrize(
    ("override", "what"),
    [
        ({"cdg": None}, "has no cdg section"),
        ({"cdg": {"made_for_cdg": False}}, "made_for_cdg: false"),
    ],
    ids=["no-section", "marker-off"],
)
def test_a_look_that_is_not_made_for_cdg_fails_the_stage_and_the_video_is_made(
    one: FakeWorld, override: dict[str, JsonValue], what: str
) -> None:
    status = run(one, Config(outputs=["mp4", "cdg"], profile=TWO_LINE, profile_overrides=override))
    assert status.state == "failed" and status.error is not None
    assert (status.error.stage, status.error.kind) == ("cdg", "cdg-not-made-for-cdg")
    assert "'two-line-turns'" in status.error.message and what in status.error.message
    assert "made_for_cdg: true" in status.error.message  # the missing marker is named
    assert one.store.size(OUT / "Artist - Title.mp4") is not None
    assert one.store.size(OUT / "Artist - Title.cdg") is None and one.mp3.requests == []


def test_the_marker_is_not_needed_while_cdg_is_off(one: FakeWorld) -> None:
    status = run(one, Config(profile_overrides={"cdg": None}))
    assert status.state == "ok" and cdg_file(one).files == []


STUCK: dict[str, JsonValue] = {
    "clear": {"hold": 0, "replace_after": 9.0},
    "lead_in": {"min": 0.05, "target": 1.0, "max": 2.0},
}
"""Lines come only at the lead-in minimum, so the look as declared draws them too late."""


def test_a_song_that_misses_the_timing_takes_a_fallback_step_and_cdg_json_says_so(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), QUICK.encode())
    run(world, Config(outputs=["mp4", "cdg"], profile=TWO_LINE, profile_overrides=STUCK))
    stored = cdg_file(world)
    assert stored.step == 1 and stored.step_name == "lines earlier (lead-in target)"
    assert stored.in_time and stored.late_lines == 0
    assert stored.values is not None and stored.values.lead_in_min == 1.0
    assert (stored.values.slots, stored.values.font_px) == (2, 24)
    log = "\n".join(world.store.log_lines(WORK / "log.txt"))
    assert "cdg: fallback step 1 of 3: lines earlier (lead-in target)" in log
    assert "warning" not in log


def test_a_song_that_no_step_brings_in_time_is_written_all_the_same_with_a_warning(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), QUICK.encode())
    hopeless: dict[str, JsonValue] = {
        **STUCK,
        "lead_in": {"min": 0.05, "target": 0.05, "max": 0.05},
    }
    status = run(world, Config(outputs=["mp4", "cdg"], profile_overrides=hopeless))
    stored = cdg_file(world)
    assert not stored.in_time and stored.late_lines > 0
    # the file is written all the same, but the song needs a look (ADR-0041)
    assert status.state == "review"
    reason = (
        f"CD+G not in time: {stored.late_lines} lines drawn late, "
        f"wipe {stored.wipe_lag * 1000:.0f} ms behind"
    )
    assert stored.reasons == [reason]
    assert f"cdg: {reason}" in status.reasons
    assert (stored.step, stored.step_name) == (1, "coarser wipe")
    assert stored.values is not None and stored.values.wipe_columns == 6
    assert world.store.size(OUT / "Artist - Title.cdg") is not None
    log = "\n".join(world.store.log_lines(WORK / "log.txt"))
    assert "cdg: warning: not in time even with coarser wipe" in log


def test_a_song_in_time_records_step_zero_and_the_values_of_the_look(one: FakeWorld) -> None:
    run(one, BOTH)
    stored = cdg_file(one)
    assert (stored.step, stored.step_name, stored.in_time, stored.late_lines) == (
        0,
        "as declared",
        True,
        0,
    )
    assert stored.reasons == []
    assert stored.values is not None
    assert stored.values.model_dump() == {
        "slots": 2,
        "font_px": 24,
        "min_font_px": 18,
        "edge_px": 1,
        "wipe_columns": 3,
        "lead_in_min": 1.0,
    }
    assert not stored.zipped


def test_the_look_s_cdg_values_decide_the_file_and_changing_them_makes_it_again(
    one: FakeWorld,
) -> None:
    run(one, BOTH)
    first = one.store.files[OUT / "Artist - Title.cdg"]
    coarse = Config(outputs=["mp4", "cdg"], profile_overrides={"cdg": {"wipe_columns": 6}})
    status = run(one, coarse)
    assert actions(status)["cdg"] == "ran"
    assert one.store.files[OUT / "Artist - Title.cdg"] != first
    values = cdg_file(one).values
    assert values is not None and values.wipe_columns == 6


ZIPPED = Config(outputs=["mp4", "cdg"], cdg_zip=True, profile=TWO_LINE)


def test_with_cdg_zip_the_pair_is_packed_and_not_written_loose(one: FakeWorld) -> None:
    status = run(one, ZIPPED)
    assert status.state == "ok"
    assert one.store.size(OUT / "Artist - Title.zip") is not None
    assert one.store.size(OUT / "Artist - Title.mp3") is None
    assert one.store.size(OUT / "Artist - Title.cdg") is None
    (request,) = one.packer.requests
    assert request.target == OUT / "Artist - Title.zip"
    assert [m.name for m in request.members] == ["Artist - Title.mp3", "Artist - Title.cdg"]
    assert request.time == (1980, 1, 1, 0, 0, 0)
    stored = cdg_file(one)
    assert stored.zipped and stored.files == ["Artist - Title.zip"]
    cdg_member = request.members[1].content
    assert isinstance(cdg_member, bytes) and len(cdg_member) == stored.packets * 24


def test_the_zip_holds_the_tagged_mp3_as_it_is(one: FakeWorld) -> None:
    run(one, ZIPPED)
    (encoded,) = one.mp3.requests
    assert encoded.target == WORK / "Artist - Title.mp3"  # made in the work folder, then packed
    assert encoded.tags == one.renderer.requests[0].tags
    assert one.packer.packed["Artist - Title.mp3"] == one.store.files[encoded.target]
    assert one.packer.packed["Artist - Title.mp3"].startswith(id3_tag(encoded.tags))


def test_a_missing_zip_runs_the_stage_again_and_only_it(one: FakeWorld) -> None:
    run(one, ZIPPED)
    one.store.delete(OUT / "Artist - Title.zip")
    status = run(one, ZIPPED)
    assert actions(status)["cdg"] == "ran" and actions(status)["render"] == "skipped"
    assert one.store.size(OUT / "Artist - Title.zip") is not None
    assert "cdg: Artist - Title.zip missing" in "\n".join(one.store.log_lines(WORK / "log.txt"))


def test_switching_the_zip_on_or_off_runs_only_the_cdg_stage(one: FakeWorld) -> None:
    run(one, BOTH)
    on = run(one, ZIPPED)
    assert actions(on)["cdg"] == "ran"
    assert all(a == "skipped" for stage, a in actions(on).items() if stage != "cdg")
    assert len(one.renderer.requests) == 1
    off = run(one, BOTH)
    assert actions(off)["cdg"] == "ran" and cdg_file(one).files[0].endswith(".mp3")
    assert run(one, BOTH).stages[-1].action == "skipped"


def test_the_zip_setting_means_nothing_while_cdg_is_off(one: FakeWorld) -> None:
    run(one)
    status = run(one, Config(cdg_zip=True))
    assert actions(status)["cdg"] == "skipped"
    assert one.packer.requests == []
