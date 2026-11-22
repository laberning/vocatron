"""Stage 2: real ffmpeg and libass draw what the layout predicted (ADR-0009).

A public-domain song is laid out with the real font, rendered frame by frame, and compared with
the boxes and wipe positions of the scene and with golden images in ``golden/``. Run with
``VOCATRON_UPDATE_GOLDEN=1`` to write the golden images (a deliberate act, then look at them).
The end-to-end tests make a short video with the real encoders.
"""

import dataclasses
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from fakes.scenes import builtin_profile
from videoreal import (
    BOX_TOLERANCE,
    MEASURER,
    RESOURCES,
    SAME,
    colour_columns,
    difference,
    entchen_scene,
    ink,
    look_scene,
    render_frame,
    rows_scene,
    turn_scene,
    visible_lines,
)
from vocatron.core.ass.write import POP_RISE, write_ass
from vocatron.core.errors import StageError
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.sample import timed_song
from vocatron.core.mp4_tags import read_tags
from vocatron.core.presets import PRESETS, AudioEncoder, AudioSettings
from vocatron.core.profiles.model import MAX_POP_SCALE, BackgroundMotion, Glow, Pop
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    ProgressElement,
    Rect,
    Scene,
    TimerElement,
)
from vocatron.core.song import MediaTags
from vocatron.engines.protocols import RenderRequest
from vocatron.engines.render import FfmpegRenderer

GOLDEN = Path(__file__).resolve().parent / "golden"
UPDATE = os.environ.get("VOCATRON_UPDATE_GOLDEN") == "1"
WIPE_TOLERANCE = 0.15  # of the font size: the sweep cuts a glyph and the outline is soft
EPS = 1e-3

pytestmark = [
    pytest.mark.skipif(not RESOURCES.font_file().is_file(), reason="the bundled font is missing"),
    pytest.mark.timeout(600),
]


def golden_check(frame: np.ndarray, name: str) -> None:
    path = GOLDEN / f"{name}.png"
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        Image.fromarray(frame).save(path, optimize=True)
        return
    assert path.is_file(), (
        f"{path.name} is missing: run with VOCATRON_UPDATE_GOLDEN=1 and look at it"
    )
    share = difference(frame, np.asarray(Image.open(path).convert("RGB")))
    assert share <= SAME, f"{name}: {share:.4%} of the pixels differ from the golden image"


def times(scene_lines: list[float]) -> list[float]:
    return [round(t, 3) for t in scene_lines]


def test_the_text_libass_draws_lies_inside_the_boxes_the_layout_predicted(tmp_path: Path) -> None:
    scene = entchen_scene()
    checked = 0
    for line in scene.lines():
        moment = line.sing_start + 0.2
        frame = render_frame(scene, moment, tmp_path)
        for shown in visible_lines(scene, moment):
            found = ink(frame, scene.slots[shown.slot])
            assert found is not None, f"slot {shown.slot} is empty at {moment}"
            left, top, right, bottom = found
            box = shown.box
            assert left >= box.x - BOX_TOLERANCE, "the ink starts left of the box"
            assert right <= box.right + BOX_TOLERANCE, "the ink ends right of the box"
            assert top >= box.y - BOX_TOLERANCE, "the ink starts above the box"
            assert bottom <= box.bottom + BOX_TOLERANCE, "the ink ends below the box"
            predicted = shown.spans[-1].x1
            assert (
                0.9 * predicted <= right - left <= predicted + 2 * (shown.edge + shown.shadow) + 4
            )
            checked += 1
    assert checked >= 5


def test_the_wipe_stands_where_the_scene_says(tmp_path: Path) -> None:
    scene = entchen_scene()
    line = scene.lines()[0]
    for number in (1, 3, len(line.spans) - 2):
        span = line.spans[number]
        moment = (span.start + span.end) / 2
        frame = render_frame(scene, moment, tmp_path)
        columns = colour_columns(frame, scene.slots[line.slot], line.colours.sung)
        assert columns.size, f"nothing is sung-coloured at {moment}"
        measured = columns.max() - line.text_x
        predicted = line.wipe_front(moment, scene.look)
        assert abs(measured - predicted) <= WIPE_TOLERANCE * line.size, (
            f"syllable {number}: {measured} against {predicted}"
        )


def test_nothing_is_sung_coloured_before_the_wipe_and_all_of_it_after(tmp_path: Path) -> None:
    scene = entchen_scene()
    line = scene.lines()[0]
    before = render_frame(scene, line.sing_start - 0.5, tmp_path)
    assert colour_columns(before, scene.slots[line.slot], line.colours.sung).size == 0
    after = render_frame(scene, line.sing_end + 0.5, tmp_path)
    columns = colour_columns(after, scene.slots[line.slot], line.colours.sung)
    assert abs((columns.max() - line.text_x) - line.spans[-1].x1) <= WIPE_TOLERANCE * line.size


def test_a_turn_inside_a_line_wipes_in_the_colour_of_the_second_singer(tmp_path: Path) -> None:
    scene = turn_scene()
    line = next(item for item in scene.lines() if item.text == "Stock und Hut")
    (turn,) = line.turns
    boundary = line.text_x + line.spans[turn.span].x0  # where "Hut" starts
    frame = render_frame(scene, line.sing_end + 0.2, tmp_path)
    region = scene.slots[line.slot]
    first = colour_columns(frame, region, line.colours.sung)
    second = colour_columns(frame, region, turn.colours.sung)
    assert first.size and second.size, "both singers' colours are drawn"
    tolerance = WIPE_TOLERANCE * line.size
    assert first.max() <= boundary + tolerance, "the first singer's colour reaches into the turn"
    assert second.min() >= boundary - tolerance, "the second singer's colour starts before the turn"
    assert second.max() - line.text_x >= line.spans[-1].x1 - tolerance, (
        "the turn is wiped to the end"
    )


@pytest.mark.parametrize("preset", ["16x9-720", "16x9-1080"])
def test_the_same_layout_fits_other_frames(tmp_path: Path, preset: str) -> None:
    scene = entchen_scene(PRESETS[preset])
    line = scene.lines()[1]
    moment = line.sing_start + 0.3
    frame = render_frame(scene, moment, tmp_path, PRESETS[preset])
    assert frame.shape[:2] == (PRESETS[preset].height, PRESETS[preset].width)
    for shown in visible_lines(scene, moment):
        found = ink(frame, scene.slots[shown.slot])
        assert found is not None
        assert found[0] >= shown.box.x - BOX_TOLERANCE
        assert found[2] <= shown.box.right + BOX_TOLERANCE


def test_the_frames_of_the_folk_song_match_the_golden_images(tmp_path: Path) -> None:
    scene = entchen_scene()
    first = scene.lines()[0]
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    breaks = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break")
    end = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "end")
    moments = {
        "title": 2.0,
        "countdown": (countdown.start + countdown.end) / 2 + 0.2,
        "first-line-wipe": first.sing_start + 0.6,
        "two-lines": scene.lines()[2].sing_start + 0.4,
        "break": (breaks.start + breaks.end) / 2,
        "end": (end.start + end.end) / 2,
    }
    for name, moment in moments.items():
        golden_check(render_frame(scene, moment, tmp_path), name)


LOOKS = ("four-line-stack", "full-page", "blue-page", "one-line-preview", "tall-page", "three-line")


def look_moments(scene: Scene, look: str) -> dict[str, float]:
    """The moments of a look that are compared with golden images: the wipe, the countdown
    before the first line, and the break screen if the look has a progress bar or a timer."""
    lines = scene.lines()
    wiped = lines[1] if look == "one-line-preview" else lines[2]  # a preview or a full page
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    moments = {
        "wipe": wiped.sing_start + 0.6,
        "countdown": (countdown.start + countdown.end) / 2,
    }
    bars = [e for e in scene.elements if isinstance(e, ProgressElement | TimerElement)]
    if bars:  # the other looks show the break notice of two-line-turns
        moments["break"] = (bars[0].start + bars[0].end) / 2
        if isinstance(bars[0], TimerElement):  # the middle of a second, not where a number changes
            moments["break"] = bars[0].end - bars[0].total // 2 + 0.5
    return moments


@pytest.mark.parametrize("look", LOOKS)
def test_each_look_matches_its_golden_frames(tmp_path: Path, look: str) -> None:
    scene = look_scene(look)
    for what, moment in look_moments(scene, look).items():
        frame = render_frame(scene, moment, tmp_path)
        background = np.array([int(scene.background[i : i + 2], 16) for i in (1, 3, 5)])
        drawn = np.abs(frame.astype(int) - background).astype(np.uint8)  # the look's background
        for line in visible_lines(scene, moment):  # the text lies inside the predicted box
            found = ink(drawn, scene.slots[line.slot])
            assert found is not None, f"{look}: slot {line.slot} is empty at {moment}"
            assert found[0] >= line.box.x - BOX_TOLERANCE
            assert found[2] <= line.box.right + BOX_TOLERANCE
        golden_check(frame, f"look-{look}-{what}")


@pytest.mark.parametrize("look", ["one-line-preview", "tall-page"])
def test_a_line_of_two_rows_matches_its_golden_frames(tmp_path: Path, look: str) -> None:
    # one-line-preview wraps the rows inside one slot, tall-page over two neighbouring slots
    scene = rows_scene(look)
    top, bottom, second = scene.lines()[:3]
    below = top.slot + (look == "tall-page")
    assert (bottom.slot, top.row, bottom.row) == (below, 0, 1)
    assert top.start == bottom.start  # one block: two rows that appear together
    moments = {  # the wipe in the first row, in the second row, and the line after it
        "rows-first": top.sing_start + 0.6,
        "rows-second": bottom.sing_start + 0.6,
        "rows-next": second.sing_start + 0.4,
    }
    for what, moment in moments.items():
        frame = render_frame(scene, moment, tmp_path)
        background = np.array([int(scene.background[i : i + 2], 16) for i in (1, 3, 5)])
        drawn = np.abs(frame.astype(int) - background).astype(np.uint8)
        for line in visible_lines(scene, moment):  # each row's text lies inside its box
            found = ink(drawn, line.box)
            assert found is not None, f"row at {moment} is empty"
            assert found[0] >= line.box.x - BOX_TOLERANCE
            assert found[2] <= line.box.right + BOX_TOLERANCE
        golden_check(frame, f"look-{look}-{what}")


MODERN = ("neon", "lyric-video")


def modern_moments(scene: Scene) -> dict[str, float]:
    """The moments of a video-only look that are compared with golden images: the title screen,
    a word being sung, a line that has just come in (in the middle of its transition) and the
    countdown."""
    lines = scene.lines()
    title = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title")
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    return {
        "title": (title.start + title.end) / 2,
        "wipe": lines[1].sing_start + 0.6,
        "change": lines[2].start + lines[2].enter / 2,
        "countdown": (countdown.start + countdown.end) / 2,
    }


@pytest.mark.parametrize("look", MODERN)
def test_each_modern_look_matches_its_golden_frames(tmp_path: Path, look: str) -> None:
    scene = look_scene(look)
    for what, moment in modern_moments(scene).items():
        golden_check(render_frame(scene, moment, tmp_path), f"look-{look}-{what}")


def scroll_moments(scene: Scene) -> dict[str, float]:
    """The moments of the scrolling look compared with golden images: a line being sung, the
    middle of a glide, the break screen standing alone, the column coming back in from below after
    it, and the countdown."""
    row = scene.lines()[1]
    glide = next(
        (a, b)
        for a, b in zip(row.path, row.path[1:], strict=False)
        if a.y > b.y and a.time >= row.sing_end
    )
    notice = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break")
    back = next(x for x in scene.lines() if x.start >= notice.end - 1e-6)  # glides in from below
    coming = (back.path[0].time + back.path[1].time) / 2
    countdown = max(
        (e for e in scene.elements if isinstance(e, CountdownElement)), key=lambda e: e.start
    )
    return {
        "wipe": row.sing_start + 0.6,
        "glide": (glide[0].time + glide[1].time) / 2,
        "break": (notice.start + notice.end) / 2,
        "break-return": coming,
        "countdown": (countdown.start + countdown.end) / 2,
    }


def test_the_scrolling_look_matches_its_golden_frames(tmp_path: Path) -> None:
    scene = look_scene("lyric-scroll")
    for what, moment in scroll_moments(scene).items():
        golden_check(render_frame(scene, moment, tmp_path), f"look-lyric-scroll-{what}")


def test_the_line_being_sung_in_the_scrolling_look_stands_at_the_current_height(
    tmp_path: Path,
) -> None:
    scene = look_scene("lyric-scroll")
    assert scene.scroll is not None
    row = scene.lines()[1]
    moment = scroll_moments(scene)["wipe"]
    frame = render_frame(scene, moment, tmp_path)
    found = ink(frame, Rect(x=0, y=row.box.y, w=scene.width, h=row.box.h))
    assert found is not None
    middle = (found[1] + found[3]) / 2
    assert abs(middle - scene.scroll.current) <= row.size / 2  # the letters sit around the middle
    # the lines before and after are dimmed: the brightest pixel of the line below is dimmer
    below = scene.lines()[2]
    shown = ink(frame, below.box_at(moment))
    assert shown is not None
    bright = int(frame[int(row.box.y) : int(row.box.bottom)].max())
    dim = int(frame[int(below.box_at(moment).y) : int(below.box_at(moment).bottom)].max())
    assert bright >= 230 and dim <= 0.7 * bright


def test_the_text_of_the_scrolling_look_is_where_its_path_says_during_a_glide(
    tmp_path: Path,
) -> None:
    scene = look_scene("lyric-scroll")
    row = scene.lines()[1]
    glide = next(
        (a.time, b.time)
        for a, b in zip(row.path, row.path[1:], strict=False)
        if a.y > b.y and a.time >= row.sing_end
    )
    tops = []
    for share in (0.15, 0.5, 0.85):
        moment = glide[0] + share * (glide[1] - glide[0])
        expected = row.box_at(moment)
        frame = render_frame(scene, moment, tmp_path)
        found = ink(frame, expected)  # the box where the path has the line: the letters are in it
        assert found is not None
        assert found[3] - found[1] >= 0.5 * row.size
        assert found[1] <= expected.y + 0.4 * expected.h <= found[3]
        tops.append(found[1])
    assert tops[0] > tops[1] > tops[2]  # the line moves up


def test_the_moving_background_of_neon_moves_and_stays_dark(tmp_path: Path) -> None:
    scene = look_scene("neon")
    assert scene.background_motion is not None
    early, late = (render_frame(scene, seconds, tmp_path).astype(int) for seconds in (0.5, 8.0))
    corner = (slice(0, 20), slice(0, 20))
    assert np.abs(early[corner] - late[corner]).max() > 10  # the gradient has turned
    assert early[corner].max() < 80 and late[corner].max() < 80  # and is still dark


def test_the_lines_that_come_up_in_lyric_video_are_dimmed(tmp_path: Path) -> None:
    scene = look_scene("lyric-video")
    now, next_up = scene.lines()[:2]
    assert next_up.start <= now.sing_start  # both on screen while the first is being sung
    frame = render_frame(scene, now.sing_start + 0.3, tmp_path)
    bright, dim = (int(frame[int(x.box.y) : int(x.box.bottom), :].max()) for x in (now, next_up))
    assert bright >= 230
    assert dim <= 0.6 * bright  # at half opacity over a dark background


def test_a_line_of_lyric_video_slides_up_while_it_comes_in(tmp_path: Path) -> None:
    scene = look_scene("lyric-video")
    third = scene.lines()[2]
    assert third.enter > 0

    def top_of_ink(seconds: float) -> int:
        frame = render_frame(scene, seconds, tmp_path).astype(int)
        background = np.array([int(scene.background[i : i + 2], 16) for i in (1, 3, 5)])
        region = frame[int(third.box.y - 40) : int(third.box.bottom + 40)]
        rows = np.nonzero((np.abs(region - background) > 12).any(axis=2).any(axis=1))[0]
        return int(rows.min())

    assert top_of_ink(third.start + 0.1) > top_of_ink(third.start + third.enter + 0.05)


@pytest.mark.parametrize("align", ["center", "right"])
def test_a_popping_word_keeps_its_line_inside_the_box(tmp_path: Path, align: str) -> None:
    # neon with a pop at the largest growth, without glow and gradient so the ink is the text
    look = builtin_profile("neon").model_copy(
        update={
            "align": align,
            "pop": Pop(scale=MAX_POP_SCALE, time=0.25),
            "glow": Glow(),
            "background_motion": BackgroundMotion(),
        }
    )
    song = timed_song("Wasserschwimmende Entlein\n", start=9.0)  # a long first word
    preset = PRESETS["4x3-720"]
    scene = layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Titel", None, 30.0, {}),
        look,
        (preset.width, preset.height),
        MEASURER,
    )
    first = scene.lines()[0]
    band = Rect(x=0, y=first.box.y, w=preset.width, h=first.box.h)
    rest = ink(render_frame(scene, first.sing_start - 0.1, tmp_path), band)
    peak = ink(render_frame(scene, first.sing_start + POP_RISE * 0.25, tmp_path), band)
    assert rest is not None and peak is not None
    assert peak[2] > rest[2] + 20  # the word has grown and pushed the rest of the line
    assert first.box.x - BOX_TOLERANCE <= peak[0]
    assert peak[2] <= first.box.right + BOX_TOLERANCE
    assert first.box.right <= scene.safe.right + EPS


def test_a_real_video_with_a_moving_background_has_a_gradient_that_changes(tmp_path: Path) -> None:
    scene = look_scene("neon")
    asked = dataclasses.replace(
        request(tmp_path, "4x3-720", AudioSettings(encoder="ffmpeg-aac", export="none")),
        background=scene.background,
        motion=scene.background_motion,
    )
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(asked)
    video = tmp_path / "out" / result.files[0]
    corners = []
    for second in ("0.2", "2.8"):
        target = tmp_path / f"corner-{second}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", second, "-i", str(video), "-frames:v", "1",
             str(target)],
            check=True, capture_output=True, timeout=60,
        )  # fmt: skip
        corners.append(np.asarray(Image.open(target).convert("RGB")).astype(int)[:20, :20])
    assert np.abs(corners[0] - corners[1]).max() > 5


def test_a_work_folder_with_odd_characters_does_not_break_the_filter(tmp_path: Path) -> None:
    odd = tmp_path / "Artist's Song: [live], part 1; (2)"
    frame = render_frame(entchen_scene(), 2.0, odd)
    assert ink(frame, entchen_scene().safe) is not None


def synthetic_song(folder: Path, seconds: float = 3.0) -> Path:
    rate = 44100
    wave = 0.2 * np.sin(2 * np.pi * 440 * np.arange(int(rate * seconds)) / rate)
    path = folder / "karaoke.flac"
    sf.write(path, np.stack([wave, wave], axis=1), rate, subtype="PCM_24")
    return path


def probe(path: Path) -> dict[str, object]:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, check=True, timeout=30,
    )  # fmt: skip
    return json.loads(done.stdout)


def streams(path: Path, kind: str) -> list[dict[str, object]]:
    found = probe(path)["streams"]
    assert isinstance(found, list)
    return [s for s in found if s["codec_type"] == kind]


def audio_md5(path: Path) -> str:
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-c", "copy", "-f", "data", "-"],
        capture_output=True, check=True, timeout=60,
    )  # fmt: skip
    return hashlib.md5(done.stdout, usedforsecurity=False).hexdigest()


def request(tmp_path: Path, preset: str, audio: AudioSettings, lead: float = 0.0) -> RenderRequest:
    work, output = tmp_path / "work", tmp_path / "out"
    (work / "stems").mkdir(parents=True)
    output.mkdir()
    scene = entchen_scene()
    (work / "lyrics.ass").write_text(write_ass(scene), encoding="utf-8")
    return RenderRequest(
        ass=work / "lyrics.ass",
        audio=synthetic_song(work / "stems"),
        work_dir=work,
        output_dir=output,
        name="Volkslied - Alle meine Entchen",
        preset=PRESETS[preset],
        audio_settings=audio,
        background=scene.background,
        duration=3.0 + lead,
        log=lambda message: None,
        lead=lead,
    )


@pytest.mark.parametrize("encoder", ["fdkaac", "ffmpeg-aac"])
def test_the_real_renderer_makes_a_video_with_the_audio_encoded_once(
    tmp_path: Path, encoder: AudioEncoder
) -> None:
    audio = AudioSettings(encoder=encoder, export="m4a")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, "4x3-720", audio))
    video, m4a = (tmp_path / "out" / name for name in result.files)
    assert (video.suffix, m4a.suffix) == (".mp4", ".m4a")
    (picture,) = streams(video, "video")
    (sound,) = streams(video, "audio")
    assert (picture["codec_name"], picture["width"], picture["height"]) == ("h264", 960, 720)
    assert picture["r_frame_rate"] == "30/1"
    assert sound["codec_name"] == "aac"
    rate = int(str(sound["bit_rate"]))
    if encoder == "fdkaac":
        assert abs(rate - 192_000) < 0.15 * 192_000  # constant bitrate
    else:
        assert 0.3 * 256_000 < rate <= 1.1 * 256_000  # ffmpeg's encoder is not constant
    assert audio_md5(video) == audio_md5(m4a), "the audio in the video is not the exported audio"
    assert result.fonts == ("NotoSans-Bold",)
    container = probe(video)["format"]
    assert isinstance(container, dict)
    assert float(str(container["duration"])) == pytest.approx(3.0, abs=0.25)


@pytest.mark.parametrize("preset", ["16x9-720", "16x9-1080"])
def test_every_h264_preset_makes_a_video_of_its_size(tmp_path: Path, preset: str) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="none")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, preset, audio))
    (picture,) = streams(tmp_path / "out" / result.files[0], "video")
    assert (picture["width"], picture["height"]) == (PRESETS[preset].width, PRESETS[preset].height)


@pytest.mark.parametrize("preset", ["4x3-720", "16x9-1080", "av1-720"])
def test_the_video_is_tagged_bt709_with_limited_range(tmp_path: Path, preset: str) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="none")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, preset, audio))
    (picture,) = streams(tmp_path / "out" / result.files[0], "video")
    assert picture["pix_fmt"] == "yuv420p"
    assert picture["color_range"] == "tv"
    assert picture["color_space"] == "bt709"
    assert picture["color_primaries"] == "bt709"
    assert picture["color_transfer"] == "bt709"


def decoded_corner(video: Path, matrix: str) -> tuple[int, int, int]:
    """The top left pixel of the first frame, decoded with the colour matrix ``matrix``."""
    convert = f"scale=in_color_matrix={matrix}:in_range=tv:out_range=pc,format=rgb24"
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-vf", convert,
         "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=60,
    )  # fmt: skip
    red, green, blue = done.stdout[:3]
    return red, green, blue


def test_the_background_comes_out_in_its_colour_when_decoded_as_tagged(tmp_path: Path) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="none")
    job = dataclasses.replace(request(tmp_path, "16x9-720", audio), background="#ff3300")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(job)
    video = tmp_path / "out" / result.files[0]
    tagged = decoded_corner(video, "bt709")
    assert all(abs(a - b) <= 5 for a, b in zip(tagged, (0xFF, 0x33, 0x00), strict=True)), tagged
    wrong = decoded_corner(video, "bt601")  # the matrix matters: as BT.601 it is clearly off
    assert max(abs(a - b) for a, b in zip(wrong, tagged, strict=True)) > 10, wrong


def test_the_av1_preset_makes_a_video(tmp_path: Path) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="none")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, "av1-720", audio))
    (picture,) = streams(tmp_path / "out" / result.files[0], "video")
    assert picture["codec_name"] == "av1"


def test_a_missing_bundled_font_is_caught_not_replaced_silently(tmp_path: Path) -> None:
    work = request(tmp_path, "4x3-720", AudioSettings(encoder="ffmpeg-aac"))
    empty = tmp_path / "no-fonts"
    empty.mkdir()
    with pytest.raises(StageError, match="instead of the bundled font") as error:
        FfmpegRenderer(empty).render(work)
    assert error.value.kind == "wrong-font"
    assert list((tmp_path / "out").iterdir()) == []


def test_the_flac_export_is_the_lossless_audio(tmp_path: Path) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="flac")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, "4x3-720", audio))
    exported = tmp_path / "out" / result.files[1]
    assert exported.suffix == ".flac"
    assert exported.read_bytes() == (tmp_path / "work" / "stems" / "karaoke.flac").read_bytes()


LEAD = 2.5  # seconds of silent intro in the tests below
QUIET = 0.001  # the largest sample that still counts as silence


def decoded(path: Path) -> np.ndarray:
    """The audio of any file as 44.1 kHz mono floats, decoded by ffmpeg."""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-ac", "1", "-ar", "44100",
         "-f", "f32le", "-"],
        capture_output=True, check=True, timeout=60,
    )  # fmt: skip
    return np.frombuffer(done.stdout, dtype=np.float32)


@pytest.mark.parametrize("encoder", ["fdkaac", "ffmpeg-aac"])
def test_the_lead_makes_the_video_and_the_m4a_longer_and_silent_at_the_start(
    tmp_path: Path, encoder: AudioEncoder
) -> None:
    audio = AudioSettings(encoder=encoder, export="m4a")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, "4x3-720", audio, LEAD))
    video, m4a = (tmp_path / "out" / name for name in result.files)
    for path in (video, m4a):
        container = probe(path)["format"]
        assert isinstance(container, dict)
        assert float(str(container["duration"])) == pytest.approx(3.0 + LEAD, abs=0.25), path.name
        wave = decoded(path)
        silent = int(44100 * (LEAD - 0.1))  # a little margin for the encoder's priming
        assert np.abs(wave[:silent]).max() < QUIET, f"{path.name} is not silent in the lead"
        assert np.abs(wave[int(44100 * (LEAD + 0.3)) :]).max() > 0.05, f"{path.name} has no song"


def test_the_flac_export_with_a_lead_is_padded_with_silence(tmp_path: Path) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="flac")
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(request(tmp_path, "4x3-720", audio, LEAD))
    exported, rate = sf.read(tmp_path / "out" / result.files[1])
    original, _ = sf.read(tmp_path / "work" / "stems" / "karaoke.flac")
    lead = round(LEAD * rate)
    assert len(exported) == len(original) + lead
    assert np.abs(exported[:lead]).max() == 0.0
    assert np.abs(exported[lead:] - original).max() < 1e-4  # 24 bit in, 16 bit or more out


TAGS = (
    ("title", 'Alle "meine" Entchen; a=b \U0001f3a4 \u00fcber \u65e5\u672c'),
    ("artist", "Volkslied"),
    ("genre", "Karaoke"),
    ("comment", "Karaoke version made with Vocatron"),
    ("tag", "Duet"),
)


def frames(path: Path) -> tuple[int, str]:
    """Return the number of frames ffprobe counts in the video and what ffmpeg says decoding all."""
    shown = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
         "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, check=True, timeout=120,
    )  # fmt: skip
    return int(shown.stdout.strip()), decoded.stderr.strip()


def test_the_tagged_video_decodes_to_the_end_with_the_frames_it_had_before_tagging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = request(tmp_path / "plain", "4x3-720", AudioSettings(encoder="ffmpeg-aac"))

    def no_tags(video: Path, tags: MediaTags) -> None:
        del video, tags

    monkeypatch.setattr(FfmpegRenderer, "_write_tags", staticmethod(no_tags))
    untagged = FfmpegRenderer(RESOURCES.fonts_dir()).render(plain)
    monkeypatch.undo()
    asked = request(tmp_path / "tagged", "4x3-720", AudioSettings(encoder="ffmpeg-aac"))
    tagged = FfmpegRenderer(RESOURCES.fonts_dir()).render(dataclasses.replace(asked, tags=TAGS))
    before, errors_before = frames(tmp_path / "plain" / "out" / untagged.files[0])
    after, errors_after = frames(tmp_path / "tagged" / "out" / tagged.files[0])
    assert (after, errors_after) == (before, errors_before) == (before, "")
    assert before > 0


def test_the_real_video_carries_exactly_the_tags_it_was_given(tmp_path: Path) -> None:
    base = request(tmp_path, "4x3-720", AudioSettings(encoder="ffmpeg-aac"))
    sound, rate = sf.read(base.audio)
    with sf.SoundFile(base.audio, "w", rate, 2, format="FLAC") as stem:
        stem.album = "Original Album"  # the input's own tag, which must not reach the video
        stem.write(sound)
    result = FfmpegRenderer(RESOURCES.fonts_dir()).render(dataclasses.replace(base, tags=TAGS))
    container = probe(tmp_path / "out" / result.files[0])["format"]
    assert isinstance(container, dict)
    tags = container["tags"]
    assert isinstance(tags, dict)
    found = {str(k).lower(): v for k, v in tags.items()}
    wanted = dict(TAGS)
    assert {k: v for k, v in found.items() if k in wanted} == wanted
    video = (tmp_path / "out" / result.files[0]).read_bytes()
    start = video.index(b"moov") - 4  # the box Vocatron's own reader finds the freeform TAG in
    end = start + int.from_bytes(video[start : start + 4], "big")
    assert read_tags(video[start:end]) == TAGS
    technical = {"major_brand", "minor_version", "compatible_brands", "encoder"}
    assert set(found) - set(wanted) <= technical, "a tag of the input was copied"


def test_the_glow_grows_with_the_sweep_through_a_long_syllable(tmp_path: Path) -> None:
    # a red glow (a colour the text, its edge and the background do not have) on a line of
    # one-syllable words, frozen in the middle of the second one
    look = builtin_profile("neon").model_copy(
        update={"glow": Glow(sung=1.0, colour="#ff0000"), "background_motion": BackgroundMotion()}
    )
    song = timed_song("Strumpf Strumpf Strumpf\n", start=9.0)
    preset = PRESETS["4x3-720"]
    scene = layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Titel", None, 30.0, {}),
        look,
        (preset.width, preset.height),
        MEASURER,
    )
    line = scene.lines()[0]
    span = line.spans[1]
    assert span.end - span.start > 0.4  # long enough to be frozen in the middle
    moment = (span.start + span.end) / 2
    frame = render_frame(scene, moment, tmp_path).astype(int)
    region = scene.slots[line.slot]
    part = frame[int(region.y) : int(region.bottom) + 1, int(region.x) : int(region.right) + 1]
    red = (part[..., 0] - np.maximum(part[..., 1], part[..., 2]) > 25).any(axis=0)
    columns = np.nonzero(red)[0] + int(region.x)
    front = line.text_x + line.wipe_front(moment, scene.look)
    margin = 0.4 * line.size  # the blur spreads the glow a little past the front
    assert (columns < front - 0.5 * line.size).any(), "no glow left of the sweep front"
    assert not (columns > front + margin).any(), "the glow runs ahead of the sweep front"
