"""Stage 1: the command lines of ffmpeg and fdkaac are pure functions, pinned as golden files."""

from pathlib import PurePosixPath

import pytest
from syrupy.assertion import SnapshotAssertion

from vocatron.core.ffmpeg_cmd import (
    GRADIENT_RATE,
    audio_job,
    delay_args,
    filter_value,
    flac_export_command,
    frame_command,
    gif_command,
    mp3_command,
    subtitles_filter,
    video_command,
)
from vocatron.core.presets import PRESETS, AudioEncoder, AudioSettings
from vocatron.core.scene import BackgroundMotion

ASS = PurePosixPath("/work/Artist - Title/lyrics.ass")
FONTS = PurePosixPath("/pkg/vocatron/fonts")
FLAC = PurePosixPath("/work/Artist - Title/stems/karaoke.flac")
M4A = PurePosixPath("/work/Artist - Title/audio.m4a")
MP4 = PurePosixPath("/out/Artist - Title.part.mp4")


def shown(command: tuple[str, ...]) -> str:
    return " ".join(command)


@pytest.mark.parametrize("preset", list(PRESETS))
def test_the_video_command_of_every_preset_is_golden(
    preset: str, snapshot: SnapshotAssertion
) -> None:
    command = video_command(PRESETS[preset], "#000000", ASS, FONTS, M4A, MP4)
    assert shown(command) == snapshot


@pytest.mark.parametrize("encoder", ["fdkaac", "ffmpeg-aac"])
def test_the_audio_commands_of_both_encoders_are_golden(
    encoder: AudioEncoder, snapshot: SnapshotAssertion
) -> None:
    job = audio_job(AudioSettings(encoder=encoder), PRESETS["4x3-720"], FLAC, M4A)
    assert [shown(command) for command in job.commands] == snapshot


def test_the_audio_is_copied_into_the_video_not_encoded_again() -> None:
    command = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4)
    assert command[command.index("-c:a") + 1] == "copy"
    assert "-shortest" in command
    inputs = [command[i + 1] for i, part in enumerate(command) if part == "-i"]
    assert len(inputs) == 2  # the background source and the encoded audio, nothing else
    assert inputs[1] == str(M4A)


def test_fdkaac_reads_a_wav_from_ffmpeg_and_the_bitrate_is_in_bits_per_second() -> None:
    decode, encode = audio_job(AudioSettings(bitrate=160), PRESETS["4x3-720"], FLAC, M4A).commands
    assert decode[0] == "ffmpeg"
    assert decode[-3:] == ("-f", "wav", "-")
    assert encode[0] == "fdkaac"
    assert encode[encode.index("-b") + 1] == "160000"
    assert encode[-1] == "-"


def test_the_ffmpeg_audio_encoder_is_one_command_at_256_kbit() -> None:
    (command,) = audio_job(
        AudioSettings(encoder="ffmpeg-aac"), PRESETS["4x3-720"], FLAC, M4A
    ).commands
    assert command[command.index("-b:a") + 1] == "256k"
    assert command[-1] == str(M4A)


def test_the_filter_value_survives_both_levels_of_escaping() -> None:
    assert filter_value("/a/b.ass") == "/a/b.ass"
    assert filter_value("/a b/c:d.ass") == "/a b/c\\\\:d.ass"
    assert filter_value("it's,[x];y") == "it\\\\\\'s\\,\\[x\\]\\;y"
    assert filter_value("a\\b") == "a\\\\\\\\b"


def test_libass_is_pointed_at_the_font_folder() -> None:
    assert subtitles_filter(ASS, FONTS) == (
        "subtitles=filename=/work/Artist - Title/lyrics.ass:fontsdir=/pkg/vocatron/fonts"
    )


def test_the_background_colour_comes_from_the_profile() -> None:
    command = video_command(PRESETS["4x3-720"], "#0a1b2c", ASS, FONTS, M4A, MP4)
    assert "color=c=0x0a1b2c:s=960x720:r=30" in command


def test_a_frame_is_one_image_at_a_time(snapshot: SnapshotAssertion) -> None:
    command = frame_command(
        PRESETS["4x3-720"], "#000000", ASS, FONTS, 12.5, PurePosixPath("/t/f.png")
    )
    assert shown(command) == snapshot
    assert command[command.index("-ss") + 1] == "12.500"


def test_a_gif_is_a_thinned_cut_of_the_video_scaled_with_a_palette_of_its_own(
    snapshot: SnapshotAssertion,
) -> None:
    command = gif_command(
        PRESETS["4x3-720"], "#000000", ASS, FONTS, [(0.0, 2.0), (91.0, 4.0), (120.0, 3.0)],
        PurePosixPath("/t/c.gif"), fps=12, size=(640, 480),
    )  # fmt: skip
    assert shown(command) == snapshot
    graph = command[command.index("-filter_complex") + 1]
    assert graph.startswith("fps=12,split=3[s0][s1][s2];[s0]trim=start=0.000:duration=2.000,")
    assert "[s1]trim=start=91.000:duration=4.000,subtitles=" in graph  # cut first, cheap
    assert "[c0][c1][c2]concat=n=3:v=1:a=0," in graph
    assert (
        graph.index("subtitles=")
        < graph.index("setpts=PTS-STARTPTS")
        < graph.index("concat=")
        < graph.index("scale=640:480")
    )
    assert "palettegen" in graph and "paletteuse" in graph
    assert command[command.index("-t") + 1] == "9.000"  # the length of the clip, not its end


def test_a_gif_needs_a_window() -> None:
    with pytest.raises(ValueError, match=r"^a GIF needs at least one window$"):
        gif_command(
            PRESETS["4x3-720"], "#000000", ASS, FONTS, [], PurePosixPath("/t/c.gif"),
            fps=12, size=(640, 480),
        )  # fmt: skip


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_video_is_converted_to_bt709_and_tagged_limited_range(preset: str) -> None:
    command = video_command(PRESETS[preset], "#000000", ASS, FONTS, M4A, MP4)
    graph = command[command.index("-vf") + 1]
    assert graph.startswith(subtitles_filter(ASS, FONTS) + ",")  # libass draws first
    assert graph.endswith(
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )
    assert "in_color_matrix=bt601" in graph and "out_color_matrix=bt709" in graph
    assert "out_range=tv" in graph
    for option, value in (
        ("-colorspace", "bt709"),
        ("-color_primaries", "bt709"),
        ("-color_trc", "bt709"),
        ("-color_range", "tv"),
    ):
        assert command[command.index(option) + 1] == value


def test_a_frame_image_is_not_converted() -> None:
    command = frame_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, 12.0, MP4)
    assert command[command.index("-vf") + 1] == subtitles_filter(ASS, FONTS)
    assert "-colorspace" not in command


@pytest.mark.parametrize("encoder", ["fdkaac", "ffmpeg-aac"])
def test_a_song_without_an_intro_keeps_its_audio_commands(encoder: AudioEncoder) -> None:
    plain = audio_job(AudioSettings(encoder=encoder), PRESETS["4x3-720"], FLAC, M4A)
    zero = audio_job(AudioSettings(encoder=encoder), PRESETS["4x3-720"], FLAC, M4A, 0.0)
    assert plain == zero
    assert not any("adelay" in part for command in plain.commands for part in command)


@pytest.mark.parametrize("encoder", ["fdkaac", "ffmpeg-aac"])
def test_the_lead_is_a_delay_in_milliseconds_in_the_decoding_step(
    encoder: AudioEncoder, snapshot: SnapshotAssertion
) -> None:
    job = audio_job(AudioSettings(encoder=encoder), PRESETS["4x3-720"], FLAC, M4A, 4.5)
    assert [shown(command) for command in job.commands] == snapshot
    first = job.commands[0]
    assert first[first.index("-af") + 1] == "adelay=4500:all=1"
    assert first.index("-af") < len(first) - 2  # the delay stands before the output arguments


def test_the_delay_is_whole_milliseconds_for_every_channel() -> None:
    assert delay_args(0.0) == ()
    assert delay_args(1.2346) == ("-af", "adelay=1235:all=1")
    assert delay_args(0.25) == ("-af", "adelay=250:all=1")  # less than a second is a delay too
    assert delay_args(6.0) == ("-af", "adelay=6000:all=1")


def test_the_flac_export_is_written_again_with_the_delay(snapshot: SnapshotAssertion) -> None:
    command = flac_export_command(FLAC, PurePosixPath("/out/Artist - Title.flac"), 4.5)
    assert shown(command) == snapshot
    assert command[command.index("-c:a") + 1] == "flac"
    assert command[command.index("-af") + 1] == "adelay=4500:all=1"


def test_the_video_command_does_not_change_with_an_intro() -> None:
    command = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4)
    assert "adelay" not in shown(command)  # the audio in the M4A already has the lead
    assert "-shortest" in command


def test_the_mp3_is_lame_at_192_kbit_44100_hz_stereo(snapshot: SnapshotAssertion) -> None:
    command = mp3_command(FLAC, PurePosixPath("/out/Artist - Title.part.mp3"), 0.0)
    assert shown(command) == snapshot
    assert command[command.index("-c:a") + 1] == "libmp3lame"
    assert command[command.index("-b:a") + 1] == "192k"
    assert command[command.index("-ar") + 1] == "44100"
    assert command[command.index("-ac") + 1] == "2"
    assert "-af" not in command  # no intro, no filter


def test_the_mp3_has_the_silent_intro_in_front_like_the_other_audio() -> None:
    command = mp3_command(FLAC, PurePosixPath("/out/x.mp3"), 4.5)
    assert command[command.index("-af") + 1] == "adelay=4500:all=1"
    assert command.index("-af") < command.index("-c:a")


def test_ffmpeg_writes_no_tag_into_the_video_and_copies_nothing() -> None:
    command = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4)
    assert command[-3:] == ("-map_metadata", "-1", str(MP4))
    assert command.count("-map_metadata") == 1
    assert "-metadata" not in command  # Vocatron writes the tags itself (ADR-0047)


def test_ffmpeg_writes_no_tag_into_the_mp3_and_copies_nothing() -> None:
    command = mp3_command(FLAC, PurePosixPath("/out/x.mp3"), 0.0)
    assert command[-1] == "/out/x.mp3"
    assert command[-3:-1] == ("-id3v2_version", "0")
    assert command[command.index("-map_metadata") + 1] == "-1"
    assert "-metadata" not in command  # Vocatron writes the tag itself (ADR-0035)


MOTION = BackgroundMotion(colours=["#04050c", "#150a30", "#061a2e"], speed=0.02)


def test_a_moving_background_is_the_gradients_source_of_the_colours() -> None:
    command = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4, motion=MOTION)
    source = command[command.index("-i") + 1]
    assert source == (
        "gradients=s=480x360:r=10:c0=0x04050c:c1=0x150a30:c2=0x061a2e:nb_colors=3:speed=0.02"
        ":x0=0:y0=0:x1=480:y1=360:seed=1,scale=960:720,fps=30"
    )
    assert command[command.index("-i") - 2 : command.index("-i")] == ("-f", "lavfi")


@pytest.mark.parametrize("preset", list(PRESETS))
def test_a_moving_background_has_the_size_and_frame_rate_of_every_preset(preset: str) -> None:
    chosen = PRESETS[preset]
    command = video_command(chosen, "#000000", ASS, FONTS, M4A, MP4, motion=MOTION)
    source = command[command.index("-i") + 1]
    assert f"gradients=s={chosen.width // 2}x{chosen.height // 2}:r={GRADIENT_RATE}:" in source
    assert f":x1={chosen.width // 2}:y1={chosen.height // 2}:" in source
    assert source.endswith(f",scale={chosen.width}:{chosen.height},fps={chosen.fps}")


def test_a_moving_background_changes_only_the_background_input() -> None:
    plain = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4)
    moving = video_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, M4A, MP4, motion=MOTION)
    differing = [i for i, (a, b) in enumerate(zip(plain, moving, strict=True)) if a != b]
    assert differing == [plain.index("-i") + 1]


def test_the_frame_command_draws_the_moving_background_too() -> None:
    command = frame_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, 12.0, MP4, motion=MOTION)
    assert command[command.index("-i") + 1].startswith("gradients=")
    plain = frame_command(PRESETS["4x3-720"], "#000000", ASS, FONTS, 12.0, MP4)
    assert plain[plain.index("-i") + 1].startswith("color=")


def test_the_gif_command_draws_the_moving_background_too() -> None:
    def gif(motion: BackgroundMotion | None) -> tuple[str, ...]:
        return gif_command(
            PRESETS["4x3-720"], "#000000", ASS, FONTS, [(1.0, 2.0)], PurePosixPath("/t/c.gif"),
            fps=12, size=(640, 480), motion=motion,
        )  # fmt: skip

    assert gif(MOTION)[gif(MOTION).index("-i") + 1].startswith("gradients=")
    assert gif(None)[gif(None).index("-i") + 1].startswith("color=")
