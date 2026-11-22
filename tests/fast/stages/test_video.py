"""Stage 1: the layout and render stages on fakes (ADR-0009)."""

from dataclasses import replace
from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.ass.parse import parse_ass
from vocatron.core.layout.file import LayoutFile
from vocatron.core.presets import AudioSettings
from vocatron.core.render import RenderFile
from vocatron.core.song import (
    SongInfo,  # noqa: F401  # documents what the stages read
    Tags,
)
from vocatron.core.stage_file import Fingerprint
from vocatron.core.status import SongStatus
from vocatron.core.syllables import SyllablesFile
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.render import delete_stale_exports

AUDIO = Path("/music/Artist - Title.mp3")
OUT = Path("/music/karaoke")
WORK = OUT / "Artist - Title"
PROFILE_FILE = Path("/music/mine.yaml")


def run(
    world: FakeWorld,
    config: Config | None = None,
    *,
    until: str | None = None,
    only: tuple[str, ...] | None = None,
) -> SongStatus:
    cfg = config or Config()
    return run_song(world.song(AUDIO, cfg), cfg, world.engines, force=False, until=until, only=only)


def actions(status: SongStatus) -> dict[str, str]:
    return {outcome.stage: outcome.action for outcome in status.stages}


def own_profile(world: FakeWorld, **changes: str) -> None:
    """Put a copy of the built-in profile at ``PROFILE_FILE`` with ``name: value`` lines changed."""
    text = world.resources.builtin_profile("two-line-turns") or ""
    for key, value in changes.items():
        text = "\n".join(
            f"{key}: {value}" if line.startswith(f"{key}:") else line for line in text.splitlines()
        )
    world.store.add(PROFILE_FILE, text.encode())


def test_the_layout_stage_writes_the_scene_and_the_ass_file(one: FakeWorld) -> None:
    status = run(one)
    assert status.state == "ok"
    layout = LayoutFile.model_validate_json(one.store.read_text(WORK / "layout.json") or "")
    assert layout.profile == "four-line-stack"
    assert (layout.scene.width, layout.scene.height) == (960, 720)
    assert len(layout.scene.lines()) >= 5  # the folk song has five lines; long ones are split
    script = parse_ass(one.store.read_text(WORK / "lyrics.ass") or "")
    assert (script.width, script.height) == (960, 720)
    assert len([e for e in script.events if e.sweeps]) == len(layout.scene.lines())


def test_the_voices_of_the_syllables_file_reach_the_scene_and_the_lrc(one: FakeWorld) -> None:
    run(one)
    path = WORK / "syllables.json"
    syllables = SyllablesFile.model_validate_json(one.store.read_text(path) or "")
    voices = [2 if number == 1 else 1 for number in range(5)]  # found in the audio
    one.store.write_text(path, syllables.model_copy(update={"voices": voices}).model_dump_json())
    assert run(one).state == "ok"
    scene = layout_of(one).scene
    assert sorted({line.voice for line in scene.lines()}) == [1, 2]
    (second,) = [line for line in scene.lines() if line.voice == 2]
    assert second.colours.sung != scene.lines()[0].colours.sung  # the colour of singer 2
    assert second.singers == "1"  # no singer mark: nobody sings it but the second voice
    lrc = one.store.read_text(OUT / "Artist - Title.lrc") or ""
    assert len([row for row in lrc.splitlines() if "{&}" in row]) == 1


def test_the_render_stage_hands_the_renderer_what_it_needs(one: FakeWorld) -> None:
    run(one)
    (request,) = one.renderer.requests
    assert request.ass == WORK / "lyrics.ass"
    assert request.audio == WORK / "stems" / "karaoke.flac"
    assert (request.output_dir, request.name) == (OUT, "Artist - Title")
    assert request.preset.name == "4x3-720"
    assert request.audio_settings == AudioSettings()
    assert request.background == "#000000"
    lead = layout_of(one).scene.lead
    assert lead == 7.0  # the folk song's first word is sung at 1 s, a solo song needs 8 s
    assert (request.lead, request.duration) == (lead, 180.0 + lead)


def test_the_finished_track_is_named_after_artist_and_title_in_the_output_folder(
    one: FakeWorld,
) -> None:
    run(one)
    for name in ("mp4", "lrc"):
        assert one.store.size(OUT / f"Artist - Title.{name}") is not None, name
    assert one.store.size(OUT / "Artist - Title.m4a") is None
    render = RenderFile.model_validate_json(one.store.read_text(WORK / "render.json") or "")
    assert render.files == ["Artist - Title.mp4", "Artist - Title.lrc"]
    assert render.preset == "4x3-720"
    assert render.fonts == ["NotoSans-Bold"]


def test_the_enhanced_lrc_has_word_times(one: FakeWorld) -> None:
    run(one)
    text = one.store.read_text(OUT / "Artist - Title.lrc") or ""
    assert text.startswith("[ti: Title]\n[ar: Artist]\n")
    assert "<00:" in text


def test_the_lrc_is_shifted_by_the_lead_like_the_video(one: FakeWorld) -> None:
    run(one)
    lead = layout_of(one).scene.lead
    text = one.store.read_text(OUT / "Artist - Title.lrc") or ""
    whole = round(180.0 + lead)
    assert f"[length: {whole // 60}:{whole % 60:02d}]" in text
    first = min(line.sing_start for line in layout_of(one).scene.lines())
    assert f"[{int(first) // 60:02d}:{first % 60:05.2f}]" in text  # the first line, shifted


def test_a_second_run_skips_the_video_stages(one: FakeWorld) -> None:
    run(one)
    status = run(one)
    assert actions(status)["layout"] == actions(status)["render"] == "skipped"
    assert len(one.renderer.requests) == 1


def test_a_deleted_video_is_rendered_again_without_a_new_layout(one: FakeWorld) -> None:
    run(one)
    one.store.delete(OUT / "Artist - Title.mp4")
    status = run(one)
    assert (actions(status)["layout"], actions(status)["render"]) == ("skipped", "ran")
    assert len(one.renderer.requests) == 2
    log = "\n".join(one.store.log_lines(WORK / "log.txt"))
    assert "render: Artist - Title.mp4 missing" in log


def test_a_new_profile_runs_only_the_layout_and_the_render(one: FakeWorld) -> None:
    run(one)
    own_profile(one, slots="3")
    status = run(one, Config(profile=str(PROFILE_FILE)))
    assert [(s, a) for s, a in actions(status).items()][-5:] == [
        ("alignment", "skipped"),
        ("syllables", "skipped"),
        ("layout", "ran"),
        ("render", "ran"),
        ("cdg", "skipped"),  # CD+G is off, so the profile does not count
    ]
    assert len(one.acoustic.requests) == 1
    assert len(one.separator.requests) == 1
    assert max(line.slot for line in layout_of(one).scene.lines()) == 2


def layout_of(world: FakeWorld) -> LayoutFile:
    return LayoutFile.model_validate_json(world.store.read_text(WORK / "layout.json") or "")


def test_an_edited_profile_file_runs_the_layout_again(one: FakeWorld) -> None:
    own_profile(one)
    config = Config(profile=str(PROFILE_FILE))
    run(one, config)
    assert actions(run(one, config))["layout"] == "skipped"
    own_profile(one, background='"#101010"')
    status = run(one, config)
    assert (actions(status)["layout"], actions(status)["render"]) == ("ran", "ran")
    assert layout_of(one).scene.background == "#101010"


def test_profile_overrides_change_single_values(one: FakeWorld) -> None:
    run(one)
    status = run(one, Config(profile_overrides={"font": {"size": 0.09}}))
    assert actions(status)["layout"] == "ran"
    scene = layout_of(one).scene
    assert max(line.size for line in scene.lines()) == pytest.approx(0.09 * scene.safe.h, abs=0.01)


def test_another_preset_changes_the_frame_and_runs_the_video_stages(one: FakeWorld) -> None:
    run(one)
    status = run(one, Config(preset="16x9-720"))
    assert (actions(status)["layout"], actions(status)["render"]) == ("ran", "ran")
    assert (layout_of(one).scene.width, layout_of(one).scene.height) == (1280, 720)
    assert one.renderer.requests[-1].preset.name == "16x9-720"


def test_the_audio_settings_run_only_the_render(one: FakeWorld) -> None:
    run(one)
    status = run(one, Config(audio=AudioSettings(encoder="ffmpeg-aac", export="flac")))
    assert (actions(status)["layout"], actions(status)["render"]) == ("skipped", "ran")
    assert one.renderer.requests[-1].audio_settings.encoder == "ffmpeg-aac"
    assert one.store.size(OUT / "Artist - Title.flac") is not None


def test_a_profile_that_does_not_load_fails_the_song_with_file_line_and_column(
    one: FakeWorld,
) -> None:
    one.store.add(PROFILE_FILE, b"name: broken\nslots: 9\n")
    status = run(one, Config(profile=str(PROFILE_FILE)))
    assert status.state == "failed"
    assert status.error is not None
    assert status.error.stage == "layout"
    assert status.error.kind == "invalid-profile"
    assert "/music/mine.yaml:2:1: slots:" in status.error.message
    assert one.renderer.requests == []


def test_a_profile_file_that_cannot_be_read_fails_the_layout_with_its_own_message(
    one: FakeWorld,
) -> None:
    one.store.add(PROFILE_FILE, b"\xff not utf-8")
    status = run(one, Config(profile=str(PROFILE_FILE)))
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("layout", "invalid-profile")
    assert "cannot read" in status.error.message


def test_an_unknown_profile_is_a_clear_error(one: FakeWorld) -> None:
    status = run(one, Config(profile="no-such-profile"))
    assert status.error is not None
    assert status.error.kind == "invalid-profile"
    assert "no-such-profile" in status.error.message


def test_a_profile_override_error_names_the_override(one: FakeWorld) -> None:
    status = run(one, Config(profile_overrides={"slots": 9}))
    assert status.error is not None
    assert status.error.message.startswith("profile_overrides.slots:")


def test_a_failing_renderer_fails_the_song_and_writes_no_lrc(one: FakeWorld) -> None:
    from vocatron.core.errors import StageError  # noqa: PLC0415

    one.renderer.fail_with = StageError("render-failed", "ffmpeg failed: boom")
    status = run(one)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("render", "render-failed")
    assert one.store.size(OUT / "Artist - Title.lrc") is None
    assert actions(status)["layout"] == "ran"  # the layout stays, so the next run only renders


def test_the_output_folder_cannot_be_the_folder_of_the_song(one: FakeWorld) -> None:
    config = Config.model_validate({"output": {"folder": "/music"}})
    status = run(one, config)
    assert status.error is not None
    assert status.error.kind == "output-collision"
    assert one.renderer.requests == []
    assert one.store.read_text(Path("/music/Artist - Title.txt")) is not None  # the lyrics are safe


def test_only_the_video_stages_can_be_run_alone(one: FakeWorld) -> None:
    run(one)
    own_profile(one, background='"#202020"')
    config = Config(profile=str(PROFILE_FILE))
    status = run(one, config, only=("probe", "layout", "render"))
    assert [s.stage for s in status.stages] == [
        "probe", "lyrics", "separation", "tempo", "alignment", "syllables", "layout", "render",
        "cdg",
    ]  # fmt: skip
    # the stages that did not run keep what the last run recorded; these two ran again
    assert (actions(status)["layout"], actions(status)["render"]) == ("ran", "ran")
    assert len(one.separator.requests) == 1
    assert len(one.acoustic.requests) == 1


def test_an_only_run_without_the_earlier_stages_says_what_to_do(world: FakeWorld) -> None:
    world.add_song(AUDIO)
    status = run(world, only=("probe", "layout", "render"))
    assert status.error is not None
    assert status.error.kind == "missing-input"
    assert "vocatron make" in status.error.message


def test_a_profile_with_colours_that_are_hard_to_read_makes_the_song_a_review_case(
    one: FakeWorld,
) -> None:
    text = (one.resources.builtin_profile("two-line-turns") or "").replace(
        'singer1: {unsung: "#ffffff", sung: "#3399ff"',
        'singer1: {unsung: "#ffffff", sung: "#101010"',
    )
    one.store.add(PROFILE_FILE, text.encode())
    status = run(one, Config(profile=str(PROFILE_FILE)))
    assert status.state == "review"
    assert any(reason.startswith("layout: colours: singer1.sung") for reason in status.reasons)
    assert one.store.size(OUT / "Artist - Title.mp4") is not None  # reviewed, not refused


DUET = (  # an LRC, so the singers have names
    "[singer1: Anna]\n[singer2: Ben]\n"
    "[00:01.00] {1} Hänschen klein\n[00:04.00] {2} ging allein\n"
    "[00:07.00] {all} in die weite Welt hinein\n"
)


@pytest.mark.parametrize(("language", "word"), [("de", "Beide"), ("en", "Both")])
def test_the_title_lists_lines_sung_together_in_the_song_s_language(
    world: FakeWorld, language: str, word: str
) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), DUET.encode())
    run(world, Config(lyrics=LyricsSettings(language=language)))
    (title,) = [e for e in layout_of(world).scene.elements if e.kind == "title"]
    assert [line.text for line in title.lines][-3:] == ["Anna", "Ben", word]


def test_the_renderer_gets_the_song_tags(one: FakeWorld) -> None:
    run(one)
    (request,) = one.renderer.requests
    assert request.tags == (
        ("title", "Title"),
        ("artist", "Artist"),
        ("genre", "Karaoke"),
        ("comment", "Karaoke version made with Vocatron"),
    )


def test_a_song_with_two_singers_gets_the_word_duet_in_the_tags_of_the_video(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(AUDIO.with_suffix(".lrc"), DUET.encode())
    run(world)
    (request,) = world.renderer.requests
    assert request.tags[-1] == ("tag", "Duet")  # {all} added no third singer


def test_a_song_without_an_artist_gets_no_artist_tag_in_the_video(one: FakeWorld) -> None:
    path = Path("/music/Solo.mp3")
    one.add_song(path, tags=Tags(None, "Solo", 180.0))
    one.run(path)
    (request,) = one.renderer.requests
    assert [key for key, _ in request.tags] == ["title", "genre", "comment"]


def test_a_look_with_a_moving_background_hands_it_to_the_renderer(one: FakeWorld) -> None:
    status = run(one, Config(profile="neon"))
    assert status.state == "ok"
    (request,) = one.renderer.requests
    layout = layout_of(one)
    assert layout.profile == "neon"
    assert layout.scene.background_motion is not None
    assert request.motion == layout.scene.background_motion
    assert request.background == layout.scene.background
    script = parse_ass(one.store.read_text(WORK / "lyrics.ass") or "")
    assert any(e.fade_in_ms > 0 for e in script.events)  # the lines of neon fade
    assert layout.scene.lines()[0].enter > 0


def test_a_classic_look_asks_for_the_plain_background(one: FakeWorld) -> None:
    run(one)
    (request,) = one.renderer.requests
    assert request.motion is None


def test_a_symbol_in_the_title_is_dropped_from_the_start_screen_and_needs_review(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, tags=Tags("Artist", "Title √", 180.0))
    status = run(world)
    assert status.state == "review"
    assert status.reasons == ["layout: the title: dropped U+221A SQUARE ROOT (not in the font)"]
    work = world.song(AUDIO).work_dir
    layout = LayoutFile.model_validate_json(world.store.read_text(work / "layout.json") or "")
    (title,) = [e for e in layout.scene.elements if e.kind == "title"]
    assert "TITLE" in [line.text for line in title.lines]
    assert all("√" not in line.text for line in title.lines)
    assert "√" not in (world.store.read_text(work / "lyrics.ass") or "")


def test_a_letter_the_font_lacks_in_the_artist_fails_the_layout(world: FakeWorld) -> None:
    world.add_song(AUDIO, tags=Tags("ก", "Title", 180.0))
    status = run(world)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("layout", "undrawable-character")
    assert status.error.message.startswith("the artist: U+0E01")


def test_an_audio_export_asked_for_is_written_and_listed(one: FakeWorld) -> None:
    run(one, Config(audio=AudioSettings(export="m4a")))
    assert one.store.size(OUT / "Artist - Title.m4a") is not None
    render = RenderFile.model_validate_json(one.store.read_text(WORK / "render.json") or "")
    assert render.files == ["Artist - Title.mp4", "Artist - Title.m4a", "Artist - Title.lrc"]


def test_an_export_that_render_json_lists_is_deleted_when_the_export_is_off_now(
    one: FakeWorld,
) -> None:
    run(one, Config(audio=AudioSettings(export="m4a")))
    one.store.add(OUT / "Artist - Title.flac", b"not listed: the user's own file")
    one.store.add(OUT / "notes.m4a", b"unrelated")
    status = run(one)
    assert actions(status)["render"] == "ran"
    assert one.store.size(OUT / "Artist - Title.m4a") is None
    assert one.store.size(OUT / "Artist - Title.flac") is not None
    assert one.store.size(OUT / "notes.m4a") is not None
    assert one.store.size(OUT / "Artist - Title.mp4") is not None


def test_an_export_of_another_kind_replaces_the_old_one(one: FakeWorld) -> None:
    run(one, Config(audio=AudioSettings(export="m4a")))
    run(one, Config(audio=AudioSettings(export="flac")))
    assert one.store.size(OUT / "Artist - Title.m4a") is None
    assert one.store.size(OUT / "Artist - Title.flac") is not None


def test_a_render_json_that_does_not_load_deletes_nothing(one: FakeWorld) -> None:
    run(one, Config(audio=AudioSettings(export="m4a")))
    one.store.add(WORK / "render.json", b"not json")
    run(one)
    assert one.store.size(OUT / "Artist - Title.m4a") is not None  # unknown: left alone


def stale_render_file(world: FakeWorld, work: Path, files: list[str]) -> None:
    """Put a ``render.json`` into ``work`` that lists ``files`` as made by an earlier run."""
    fingerprint = Fingerprint(inputs={}, settings="", stage_version=6)
    earlier = RenderFile(
        fingerprint=fingerprint,
        preset="4x3-720",
        audio_encoder="fdkaac",
        files=files,
        fonts=[],
        seconds=1.0,
    )
    world.store.add(work / "render.json", earlier.model_dump_json().encode())


def test_only_plain_export_names_of_the_output_folder_are_deleted(world: FakeWorld) -> None:
    world.add_song(Path("/music/Artist - Title.mp3"))
    ctx = world.context(Path("/music/Artist - Title.mp3"))
    outside = [Path("/music/Artist - Title.m4a"), Path("/music/x.flac"), Path("/x.m4a")]
    for path in [*outside, OUT / "Artist - Title.m4a", OUT / "song.mp3", OUT / "a" / "b.m4a"]:
        world.store.add(path, b"data")
    names = ["../Artist - Title.m4a", "../x.flac", "/x.m4a", "a/b.m4a", "song.mp3"]
    stale_render_file(world, WORK, [*names, "Artist - Title.m4a"])
    delete_stale_exports(ctx, ["Artist - Title.mp4", "Artist - Title.lrc"])
    assert world.store.size(OUT / "Artist - Title.m4a") is None
    for path in [*outside, OUT / "song.mp3", OUT / "a" / "b.m4a"]:
        assert world.store.size(path) is not None, path


def test_the_song_itself_is_never_deleted_as_a_stale_export(world: FakeWorld) -> None:
    # An export written into the song folder became a song of its own and took over the name.
    song = world.add_song(Path("/music/Artist - Title.m4a"))
    config = Config.model_validate({"output": {"folder": "."}})
    ctx = world.context(song, config)
    assert (ctx.song.output_dir, ctx.song.name) == (Path("/music"), "Artist - Title")
    stale_render_file(world, ctx.song.work_dir, ["Artist - Title.mp4", "Artist - Title.m4a"])
    delete_stale_exports(ctx, ["Artist - Title.mp4", "Artist - Title.lrc"])
    assert world.store.size(song) is not None


def test_a_file_this_run_made_is_kept_whatever_the_case_of_the_old_name(
    world: FakeWorld,
) -> None:
    world.add_song(Path("/music/Artist - Title.mp3"))
    ctx = world.context(Path("/music/Artist - Title.mp3"))
    world.store.add(OUT / "artist - title.m4a", b"data")  # one file on a case-insensitive disk
    stale_render_file(world, WORK, ["artist - title.m4a"])
    delete_stale_exports(ctx, ["Artist - Title.mp4", "Artist - Title.M4A"])
    assert world.store.size(OUT / "artist - title.m4a") is not None


def test_an_export_that_cannot_be_deleted_is_logged_and_left(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.add_song(Path("/music/Artist - Title.mp3"))
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)

    ctx = replace(world.context(Path("/music/Artist - Title.mp3")), log=log)
    stale_render_file(world, WORK, ["Artist - Title.m4a"])

    def refuse(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(world.store, "delete", refuse)
    delete_stale_exports(ctx, ["Artist - Title.mp4"])
    assert lines == [
        "render: could not delete Artist - Title.m4a: [Errno 13] Permission denied: "
        "'/music/karaoke/Artist - Title.m4a'"
    ]


def test_an_export_named_like_the_song_file_is_kept_in_another_folder_too(
    world: FakeWorld,
) -> None:
    # Names, not paths, are compared: a symlink or ".." can make two paths one file.
    song = world.add_song(Path("/music/Artist - Title.m4a"))
    ctx = world.context(song)
    world.store.add(OUT / "Artist - Title.m4a", b"data")
    stale_render_file(world, WORK, ["Artist - Title.m4a"])
    delete_stale_exports(ctx, ["Artist - Title.mp4", "Artist - Title.lrc"])
    assert world.store.size(OUT / "Artist - Title.m4a") is not None
    assert world.store.size(song) is not None
