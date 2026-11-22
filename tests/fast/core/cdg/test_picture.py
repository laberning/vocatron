"""Stage 1: the CD+G pictures of a look: six settled moments, the song in the look, the digest."""

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from fakes.cdg import CdgBuilder, memory_preset, palette
from fakes.measure import FixedMeasurer
from fakes.picture_song import made_up_song
from fakes.raster import FakeRasteriser
from fakes.scenes import builtin_profile
from vocatron.core.cdg.fit import Fit
from vocatron.core.cdg.packet import PACKETS_PER_SECOND
from vocatron.core.cdg.picture import (
    CdgPicture,
    cdg_picture,
    cdg_picture_digest,
    rgb_frames,
    settled_after,
)
from vocatron.core.profiles.picture import picture_moments


def settled(*ticks: int) -> Fit:
    """A fit whose scheduler reports ``ticks`` as settled (all ``settled_after`` reads)."""
    return cast(
        "Fit", SimpleNamespace(written=SimpleNamespace(scheduled=SimpleNamespace(settled=ticks)))
    )


def test_a_moment_moves_to_the_end_of_the_first_settled_tick_at_or_after_it() -> None:
    last_slot = 1 / PACKETS_PER_SECOND
    fit = settled(100, 250, 251)
    assert settled_after(fit, 2.0) == pytest.approx(2.51 - last_slot)  # tick 200 is not settled
    assert settled_after(fit, 2.5) == pytest.approx(2.51 - last_slot)  # tick 250 itself
    assert settled_after(fit, 1.0) == pytest.approx(1.01 - last_slot)


def test_a_moment_after_the_last_settled_tick_stays_where_it_is() -> None:
    assert settled_after(settled(100), 3.0) == 3.0
    assert settled_after(settled(), 0.5) == 0.5


@pytest.fixture(scope="module")
def picture() -> CdgPicture:
    return cdg_picture(
        made_up_song(), builtin_profile("two-line-turns"), FixedMeasurer(), FakeRasteriser()
    )


def test_the_moments_keep_their_names_and_are_settled_thousandths(picture: CdgPicture) -> None:
    fit = picture.fit
    wanted = picture_moments(fit.scene, fit.profile)
    assert [m.name for m in picture.moments] == [m.name for m in wanted]
    for moved, moment in zip(picture.moments, wanted, strict=True):
        assert moved.seconds == round(settled_after(fit, moment.seconds), 3)
        assert moved.seconds >= moment.seconds - 1 / PACKETS_PER_SECOND
    assert [frame.shape for frame in picture.frames] == [(216, 300, 3)] * 6


def test_the_song_is_written_in_the_case_of_the_look() -> None:
    look = builtin_profile("two-line-turns", font={"case": "upper"})
    drawn = cdg_picture(made_up_song(), look, FixedMeasurer(), FakeRasteriser())
    texts = [line.text for line in drawn.fit.scene.lines()]
    assert texts and all(text == text.upper() for text in texts)


def test_every_input_of_a_cdg_picture_changes_its_digest(picture: CdgPicture) -> None:
    def digest(tool: int = 1, shown: CdgPicture = picture, font: str = "f") -> str:
        return cdg_picture_digest(tool_version=tool, picture=shown, font_sha256=font)

    fit = picture.fit
    later = [replace(m, seconds=m.seconds + 1) for m in picture.moments]
    other_step = replace(fit, step=replace(fit.step, number=fit.step.number + 1))
    other_profile = replace(fit, profile=fit.profile.model_copy(update={"name": "other"}))
    fewer_lines = replace(fit, scene=fit.scene.model_copy(update={"elements": []}))
    line = fit.scene.lines()[0]
    sung_by_other = line.model_copy(update={"singers": "3" if line.singers != "3" else "1"})
    other_singer = replace(  # the same lines and times, one sung by another singer
        fit,
        scene=fit.scene.model_copy(
            update={"elements": [sung_by_other if e is line else e for e in fit.scene.elements]}
        ),
    )
    variants = [
        digest(tool=2),
        digest(font="g"),
        digest(shown=replace(picture, moments=later)),
        digest(shown=replace(picture, fit=other_step)),
        digest(shown=replace(picture, fit=other_profile)),
        digest(shown=replace(picture, fit=fewer_lines)),
        digest(shown=replace(picture, fit=other_singer)),
    ]
    assert digest() == digest()
    assert len({digest(), *variants}) == len(variants) + 1


def test_each_frame_is_shown_in_the_palette_in_force_at_its_time() -> None:
    first = [(15, 0, 0)] * 8  # entry 1 is red, then blue
    second = [(0, 0, 15)] * 8
    stream = (
        CdgBuilder()
        .at(0.0)
        .add(palette(first), palette(first, high=True), memory_preset(1))
        .at(1.0)
        .add(palette(second), palette(second, high=True))
        .end(2.0)
    )
    early, late = rgb_frames(stream, [0.5, 1.5])
    assert early[0, 0].tolist() == [255, 0, 0]
    assert late[0, 0].tolist() == [0, 0, 255]  # the same index, the colours of the later table


def test_the_picture_of_a_look_with_the_wordmark_shows_its_start_screen_in_its_own_colours() -> (
    None
):
    shown = cdg_picture(
        made_up_song(),
        builtin_profile("two-line-turns", title={"form": "wordmark"}),
        FixedMeasurer(),
        FakeRasteriser(),
    )
    title = shown.frames[0]
    assert title[0, 0].tolist() == [0x11, 0x00, 0x11]  # the field of the start screen
    assert (title == [255, 238, 119]).all(axis=2).any()  # the top band of the letters
