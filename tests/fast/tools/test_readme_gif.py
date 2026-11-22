"""Stage 1: the README animation is current and made of two cuts (ADR-0045, ADR-0050)."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

import readme_gif
from fakes.picture_song import made_up_song
from picture_song import committed_song
from vocatron.core.font_check import BUNDLED_FACE
from vocatron.core.schemas import render_manifest
from vocatron.core.syllables import SyllableWord
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
MEASURER = PillowMeasurer(RESOURCES.font_file())


def test_the_committed_gif_is_current() -> None:
    problems = readme_gif.stale(readme_gif.ASSETS, RESOURCES, MEASURER)
    assert problems == [], f"{problems}: run `make readme-gif`"


def _total() -> float:
    return sum(length for _, length in readme_gif.gif_inputs(RESOURCES, MEASURER).windows)


def test_the_committed_gif_loops_about_twenty_four_seconds_at_640_by_480_and_is_small() -> None:
    path = readme_gif.ASSETS / readme_gif.TARGET
    with Image.open(path) as gif:
        assert gif.size == readme_gif.SIZE == (640, 480)
        assert gif.info.get("loop") == 0  # for ever
        assert getattr(gif, "n_frames", 1) == round(_total() * readme_gif.FPS)
        assert 20 <= _total() <= 28
    assert path.stat().st_size <= readme_gif.MAX_BYTES


def _word(line: int, start: float, end: float) -> SyllableWord:
    return SyllableWord(line=line, text="la", start=start, end=end, estimated=False, syllables=[])


def _lines(spans: list[tuple[float, float]]) -> list[SyllableWord]:
    """Return one word per line, sung from the start to the end of its span."""
    return [_word(i, start, end) for i, (start, end) in enumerate(spans)]


def test_the_cuts_are_the_title_then_the_singing_up_to_the_first_pause_after_ten_seconds() -> None:
    # sung from 20 s; the pause after the second line comes too early (7 s sung), the one after
    # the fourth line (ending at 33 s, 13 s sung) is the stop
    words = _lines([(20, 24), (24.5, 27), (31, 31.8), (32, 33), (37, 39)])
    title, sung = readme_gif.cuts(words)
    assert title == (0.0, readme_gif.TITLE_SECONDS)
    assert sung[0] == 20 - readme_gif.LEAD_IN
    assert sung[0] + sung[1] == pytest.approx(33 + readme_gif.TAIL)


def test_without_a_pause_the_cut_runs_to_the_last_line_and_not_past_the_song() -> None:
    words = _lines([(5, 9), (9.5, 14), (14.5, 18)])
    title, sung = readme_gif.cuts(words, duration=18.5)
    assert sung[0] == readme_gif.TITLE_SECONDS  # singing early: the cut starts after the title
    assert sung[0] + sung[1] == pytest.approx(18.5)
    assert readme_gif.cuts(words)[1][0] + readme_gif.cuts(words)[1][1] == pytest.approx(19)
    assert title[0] + title[1] <= sung[0]


def test_a_word_inside_a_line_does_not_end_it() -> None:
    words = [_word(0, 10, 12), _word(0, 12.5, 21), _word(1, 30, 31)]
    assert readme_gif.cuts(words)[1] == (7.0, 15.0)


def test_a_short_line_sung_inside_a_longer_one_is_no_place_to_stop() -> None:
    # two voices: the second line (12-13 s) lies inside the first (10-25 s), so no pause follows it
    words = _lines([(10, 25), (12, 13), (17, 24), (30, 31)])
    assert readme_gif.cuts(words)[1] == (7.0, 19.0)


def test_ten_seconds_sung_and_a_three_second_pause_are_just_enough() -> None:
    words = _lines([(10, 20), (23, 24)])
    assert readme_gif.cuts(words)[1] == (7.0, 14.0)
    assert readme_gif.cuts(_lines([(10, 19.9), (22.9, 24)]))[1] == (7.0, 18.0)
    assert readme_gif.cuts(_lines([(10, 20), (22.9, 24)]))[1] == (7.0, 18.0)


def test_the_cuts_of_the_demo_song_lie_inside_it_in_order_without_overlap() -> None:
    song = committed_song()
    windows = readme_gif.gif_inputs(RESOURCES, MEASURER).windows
    assert len(windows) == 2
    ends = [0.0] + [start + length for start, length in windows]
    for (start, length), before in zip(windows, ends, strict=False):
        assert start >= before and start + length <= (song.duration or 0)
    first = min(word.start for word in song.words)
    assert windows[1][0] < first < windows[1][0] + windows[1][1] - readme_gif.MIN_SUNG


def test_the_digest_follows_the_song_and_is_stable() -> None:
    first = readme_gif.gif_inputs(RESOURCES, MEASURER)
    assert first.digest == readme_gif.gif_inputs(RESOURCES, MEASURER).digest
    other = readme_gif.gif_inputs(RESOURCES, MEASURER, made_up_song())
    assert other.digest != first.digest


def test_a_missing_gif_a_missing_line_and_an_old_digest_are_each_reported(tmp_path: Path) -> None:
    def problems() -> list[str]:
        return readme_gif.stale(tmp_path, RESOURCES, MEASURER)

    assert problems() == [f"{readme_gif.TARGET} is missing"]
    Image.new("P", (1, 1)).save(tmp_path / readme_gif.TARGET)
    assert problems() == [f"{readme_gif.TARGET} is not in {readme_gif.MANIFEST}"]
    manifest = tmp_path / readme_gif.MANIFEST
    manifest.write_text(render_manifest({readme_gif.TARGET: "0" * 64}), encoding="utf-8")
    assert problems() == [f"{readme_gif.TARGET} was made from an older look, layout, song or cuts"]
    digest = readme_gif.gif_inputs(RESOURCES, MEASURER).digest
    manifest.write_text(render_manifest({readme_gif.TARGET: digest}), encoding="utf-8")
    assert problems() == []


def test_an_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert readme_gif.main(["x"]) == 2
    assert "no arguments" in capsys.readouterr().err


def test_a_look_with_a_moving_background_gets_it_in_the_gif(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, b"", f"fontselect: (x) -> {BUNDLED_FACE}".encode()
        )

    monkeypatch.setattr(readme_gif, "DEFAULT_PROFILE", "neon")
    monkeypatch.setattr(readme_gif.subprocess, "run", run)
    inputs = readme_gif.make_gif(RESOURCES, MEASURER, tmp_path / "clip.gif")
    assert inputs.motion is not None
    (command,) = commands
    assert command[command.index("-i") + 1].startswith("gradients=")


@pytest.mark.parametrize(
    ("page", "src"), [("README.md", "docs/assets/"), ("docs/index.md", "assets/")]
)
def test_the_front_pages_open_with_the_pitch_the_description_and_the_smaller_gif(
    page: str, src: str
) -> None:
    text = (readme_gif.ASSETS.parent.parent / page).read_text(encoding="utf-8")
    skipped = ("---", "#", "[![")  # front matter, headings (the wordmark is one), badges
    paragraphs = [p for p in text.split("\n\n") if p.strip() and not p.startswith(skipped)]
    pitch, description, image = paragraphs[:3]
    assert pitch.startswith("**Turn your CD collection") and pitch.endswith("collection.**")
    assert description.startswith("Vocatron turns a song and its lyrics into a karaoke track")
    assert image.startswith(f'<img src="{src}{readme_gif.TARGET}" width="480" alt="')
    assert readme_gif.SIZE[0] > 480  # shown smaller than drawn, so it stays sharp
