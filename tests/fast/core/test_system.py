"""Stage 1: the pure judgements about ffmpeg, encoders, PyTorch and the GPU."""

from collections.abc import Callable
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.system import GOOD_ENCODERS, GOOD_FFMPEG, GOOD_TORCH
from vocatron.core.system import (
    GIB,
    Check,
    TorchInfo,
    encoder_names,
    encoder_problems,
    fdkaac_check,
    ffmpeg_checks,
    ffmpeg_problems,
    ffmpeg_version_text,
    models_check,
    output_check,
    torch_checks,
    torch_problems,
)

OLD = GOOD_FFMPEG.replace("version 8.0.1", "version 6.1.1")
NO_LIBASS = GOOD_FFMPEG.replace("--enable-libass ", "")


def test_good_ffmpeg_has_no_problems() -> None:
    assert ffmpeg_problems(GOOD_FFMPEG) == []


def test_release_tag_style_version_is_read() -> None:
    assert ffmpeg_problems(GOOD_FFMPEG.replace("version 8.0.1", "version n8.1")) == []


def test_git_master_build_counts_as_new_enough() -> None:
    git_build = GOOD_FFMPEG.replace("version 8.0.1-3ubuntu2", "version N-121234-g0123abcd")
    assert ffmpeg_problems(git_build) == []


def test_missing_ffmpeg_is_reported() -> None:
    problems = ffmpeg_problems(None)
    assert len(problems) == 1
    assert "not installed" in problems[0]


def test_old_ffmpeg_is_reported() -> None:
    problems = ffmpeg_problems(OLD)
    assert len(problems) == 1
    assert "too old" in problems[0]
    assert "6" in problems[0]


def test_ffmpeg_without_libass_is_reported() -> None:
    problems = ffmpeg_problems(NO_LIBASS)
    assert len(problems) == 1
    assert "libass" in problems[0]


def test_unreadable_version_is_reported() -> None:
    problems = ffmpeg_problems("something else\n--enable-libass")
    assert len(problems) == 1
    assert "Could not read" in problems[0]


def test_old_and_without_libass_reports_both() -> None:
    assert len(ffmpeg_problems(OLD.replace("--enable-libass ", ""))) == 2


def test_version_text_is_the_version_token() -> None:
    assert ffmpeg_version_text(GOOD_FFMPEG) == "8.0.1-3ubuntu2"
    assert ffmpeg_version_text("nothing") == "unknown"


def test_encoder_names_are_read_from_the_listing() -> None:
    assert {"libx264", "aac"} <= encoder_names(GOOD_ENCODERS)


def test_good_encoders_have_no_problems() -> None:
    assert encoder_problems(GOOD_ENCODERS) == []


def test_the_encoder_of_the_preset_is_the_one_that_is_needed() -> None:
    listing = GOOD_ENCODERS.replace("libx264", "h264_nvenc")
    assert encoder_problems(listing, "h264_nvenc") == []
    assert "libx264" in encoder_problems(listing)[0]  # the default preset wants libx264


def test_aac_is_needed_only_for_the_ffmpeg_audio_encoder() -> None:
    listing = " V....D libx264   H.264\n"
    assert encoder_problems(listing) == []
    problems = encoder_problems(listing, needs_aac=True)
    assert len(problems) == 1
    assert "aac" in problems[0]


def test_missing_video_encoder_and_aac_are_both_reported() -> None:
    problems = encoder_problems(" V....D mpeg4   MPEG-4\n", needs_aac=True)
    assert len(problems) == 2
    assert "libx264" in problems[0]
    assert "aac" in problems[1]


def test_fdkaac_is_needed_only_for_the_fdkaac_encoder() -> None:
    assert fdkaac_check("fdkaac 1.0.0", "fdkaac").ok
    missing = fdkaac_check(None, "fdkaac")
    assert not missing.ok
    assert "ffmpeg-aac" in str(missing.fix)
    assert fdkaac_check(None, "ffmpeg-aac").ok


def test_unlistable_encoders_are_reported() -> None:
    assert encoder_problems(None) == ["Could not list the ffmpeg encoders."]


def test_ffmpeg_checks_pass_on_a_good_build() -> None:
    checks = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS)
    assert [c.name for c in checks] == ["ffmpeg", "libass", "encoders"]
    assert all(c.ok for c in checks)


def test_ffmpeg_checks_without_ffmpeg_all_fail_with_one_fix() -> None:
    checks = ffmpeg_checks(None, None)
    assert [c.ok for c in checks] == [False, False, False]
    assert len({c.fix for c in checks}) == 1


def test_ffmpeg_checks_separate_the_findings() -> None:
    checks = ffmpeg_checks(OLD.replace("--enable-libass ", ""), " A....D aac  AAC\n")
    assert [c.ok for c in checks] == [False, False, False]
    assert "too old" in str(checks[0].fix)
    assert "libass" in str(checks[1].fix)
    assert "libx264" in str(checks[2].fix)


def test_a_healthy_gpu_has_no_problems() -> None:
    assert torch_problems(GOOD_TORCH) == []
    assert all(c.ok for c in torch_checks(GOOD_TORCH))


def test_missing_pytorch_is_reported() -> None:
    (check,) = torch_checks(None)
    assert not check.ok
    assert "make setup" in str(check.fix)


def test_a_cpu_build_finds_no_gpu() -> None:
    info = TorchInfo("2.14.1+cpu", None, None, None)
    problems = torch_problems(info)
    assert "CPU build" in problems[0]
    torch_check, gpu_check = torch_checks(info)
    assert torch_check.ok
    assert gpu_check.ok  # no GPU is no failure: the separation falls back to the CPU
    assert gpu_check.warning is not None
    assert "CPU, about 20 times slower" in gpu_check.warning


def test_a_cpu_build_is_told_how_to_get_the_cuda_build() -> None:
    problems = torch_problems(TorchInfo("2.14.1+cpu", None, None, None))
    assert "TORCH_EXTRA=cuda" in problems[1]


def test_a_cuda_build_without_a_device_is_reported() -> None:
    problems = torch_problems(TorchInfo("2.14.1", "13.0", None, None))
    assert "CPU build" not in problems[0]
    assert "NVIDIA driver" in problems[1]


def test_exactly_the_minimum_vram_is_enough() -> None:
    assert torch_problems(TorchInfo("2.14.1", "13.0", "Edge", 6 * GIB)) == []
    assert torch_problems(TorchInfo("2.14.1", "13.0", "Edge", 6 * GIB - 1)) != []


def test_too_little_vram_is_reported() -> None:
    small = TorchInfo("2.14.1", "13.0", "Tiny", 4 * GIB)
    assert "4.0 GiB" in torch_problems(small)[0]
    assert "4.0 GiB" in str(torch_checks(small)[1].warning)


def test_models_check_lists_what_is_wrong() -> None:
    check = models_check({"a": "present", "b": "missing", "c": "mismatch"})
    assert not check.ok
    assert "1 of 3 present" in check.detail
    assert "vocatron models download b c" in str(check.fix)


def test_models_check_passes_when_all_are_present() -> None:
    assert models_check({"a": "present"}).ok


def test_output_check_reports_an_unwritable_folder() -> None:
    assert output_check(Path("/x"), writable=True).ok
    bad = output_check(Path("/x"), writable=False)
    assert not bad.ok
    assert "/x" in bad.detail


def texts(checks: list[Check]) -> list[tuple[str, str, str | None, str | None]]:
    return [(c.name, c.detail, c.fix, c.warning) for c in checks]


# Built inside the test, not at import, so that every check runs under the test.
SCENARIOS: dict[str, Callable[[], list[Check]]] = {
    "healthy": lambda: [
        *ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS),
        *torch_checks(GOOD_TORCH),
        models_check({"a": "present", "b": "present"}),
        output_check(Path("/out"), writable=True),
    ],
    "nothing installed": lambda: [*ffmpeg_checks(None, None), *torch_checks(None)],
    "everything wrong": lambda: [
        *ffmpeg_checks(OLD.replace("--enable-libass ", ""), " V....D mpeg4   MPEG-4\n"),
        *torch_checks(TorchInfo("2.14.1", "13.0", "Tiny", 4 * GIB)),
        models_check({"a": "present", "b": "partial", "c": "mismatch"}),
        output_check(Path("/out"), writable=False),
    ],
    "unreadable": lambda: [*ffmpeg_checks("garbage", None)],
    "cpu build": lambda: torch_checks(TorchInfo("2.14.1+cpu", None, None, None)),
    "cuda without device": lambda: torch_checks(TorchInfo("2.14.1", "13.0", None, None)),
}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_texts_of_the_checks_are_golden(scenario: str, snapshot: SnapshotAssertion) -> None:
    assert texts(SCENARIOS[scenario]()) == snapshot


def test_a_gpu_without_a_memory_size_counts_as_no_gpu() -> None:
    info = TorchInfo("2.14.1", "13.0", "Odd GPU", None)
    assert torch_problems(info)[0] == "PyTorch finds no CUDA GPU."
    assert torch_checks(info)[1].detail == "none found"


def test_the_fdkaac_check_names_itself_and_says_what_it_found() -> None:
    found = fdkaac_check(" fdkaac 1.0.0 ", "fdkaac")
    assert (found.name, found.detail) == ("fdkaac", "fdkaac 1.0.0")
    skipped = fdkaac_check(None, "ffmpeg-aac")
    assert (skipped.name, skipped.detail) == ("fdkaac", "not needed (audio.encoder is ffmpeg-aac)")


def test_the_encoder_check_asks_for_the_preset_s_codec_and_aac_only_when_needed() -> None:
    nvenc = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS, "h264_nvenc")[2]
    assert not nvenc.ok
    assert "h264_nvenc" in str(nvenc.fix)
    plain = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS)[2]
    assert plain.detail == "libx264"
    with_aac = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS, needs_aac=True)[2]
    assert with_aac.detail == "libx264 and aac"
    no_aac = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS.replace("aac", "mp2"), needs_aac=True)[2]
    assert not no_aac.ok


def test_lame_is_needed_only_for_cdg() -> None:
    listing = " V....D libx264   H.264\n"
    assert encoder_problems(listing) == []
    assert encoder_problems(listing, needs_mp3=True) == [
        "ffmpeg has no libmp3lame encoder, which CD+G needs. "
        "Install an ffmpeg build with libmp3lame."
    ]
    assert encoder_problems(listing + " A....D libmp3lame  MP3\n", needs_mp3=True) == []


def test_the_encoder_check_names_lame_when_cdg_is_on() -> None:
    with_mp3 = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS, needs_mp3=True)[2]
    assert with_mp3.ok and with_mp3.detail == "libx264 and libmp3lame"
    both = ffmpeg_checks(GOOD_FFMPEG, GOOD_ENCODERS, needs_aac=True, needs_mp3=True)[2]
    assert both.detail == "libx264 and aac and libmp3lame"
    listing = GOOD_ENCODERS.replace("libmp3lame", "mp2")
    no_mp3 = ffmpeg_checks(GOOD_FFMPEG, listing, needs_mp3=True)[2]
    assert not no_mp3.ok and "libmp3lame" in str(no_mp3.fix)


def test_the_encoder_check_names_the_preset_s_video_encoder_when_it_is_there() -> None:
    listing = GOOD_ENCODERS.replace("libx264", "h264_nvenc")
    check = ffmpeg_checks(GOOD_FFMPEG, listing, "h264_nvenc", needs_mp3=True)[2]
    assert check.ok and check.detail == "h264_nvenc and libmp3lame"
