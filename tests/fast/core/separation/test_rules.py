"""Stage 1: chunking, overlap-add, mixing, headroom, device and timeout rules of the separation."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from numpy.typing import NDArray

from vocatron.core.errors import StageError
from vocatron.core.separation.rules import (
    CEILING_DB,
    GIB,
    KARAOKE_INPUT_PEAK,
    MIN_FREE_VRAM,
    TIMEOUT_BASE,
    Audio,
    ChunkPlan,
    apply_headroom,
    choose_device,
    combine_estimates,
    fade_window,
    mix_stems,
    normalise_peak,
    overlap_add,
    peak,
    plan_chunks,
    timeout_seconds,
)

CEILING = 10 ** (CEILING_DB / 20)


def audio_of(values: NDArray[np.float64]) -> Audio:
    return values.astype(np.float32)


def noise(channels: int, samples: int, seed: int = 0, scale: float = 1.0) -> Audio:
    rng = np.random.default_rng(seed)
    return audio_of(rng.uniform(-scale, scale, (channels, samples)))


def song_cover(plan: ChunkPlan) -> set[int]:
    """Return the distinct numbers of chunks that the samples of the song lie in."""
    cover = np.zeros(plan.padded, dtype=int)
    for start in plan.starts:
        cover[start : start + plan.chunk] += 1
    return set(cover[plan.border : plan.border + plan.samples].tolist())


def test_the_plan_pads_both_ends_and_steps_by_a_fraction_of_the_chunk() -> None:
    plan = plan_chunks(samples=100, chunk=40, num_overlap=4)
    assert (plan.step, plan.border, plan.padded) == (10, 30, 100 + 60 + 40)
    assert plan.starts[:3] == (0, 10, 20)
    assert plan.starts[-1] + plan.chunk == plan.padded
    assert set(np.diff(plan.starts)) == {10}


def test_every_sample_of_the_song_lies_in_num_overlap_chunks() -> None:
    plan = plan_chunks(samples=95, chunk=40, num_overlap=4)
    assert song_cover(plan) == {4}


def test_an_overlap_equal_to_the_chunk_steps_by_one_sample() -> None:
    plan = plan_chunks(samples=10, chunk=4, num_overlap=4)
    assert (plan.step, plan.border) == (1, 3)
    assert song_cover(plan) == {4}


def test_the_real_model_sizes_give_the_trial_chunk_count() -> None:
    plan = plan_chunks(samples=198 * 44100, chunk=352800, num_overlap=4)
    assert plan.step == 88200
    assert len(plan.starts) == (plan.padded - plan.chunk) // plan.step + 1


@pytest.mark.parametrize(
    ("samples", "chunk", "overlap"), [(-1, 10, 2), (10, 0, 2), (10, 10, 1), (10, 4, 5)]
)
def test_a_plan_with_nonsense_sizes_is_refused(samples: int, chunk: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="invalid chunk plan"):
        plan_chunks(samples, chunk, overlap)


def test_the_window_fades_linearly_over_a_tenth_at_both_ends() -> None:
    window = fade_window(100)
    assert window[0] == 0.0
    assert window[9] == 1.0
    assert np.allclose(window[:10], np.linspace(0, 1, 10))
    assert np.allclose(window[-10:], np.linspace(1, 0, 10))
    assert set(window[10:-10]) == {1.0}


def test_a_tiny_chunk_still_has_a_window() -> None:
    assert fade_window(3).shape == (3,)


@given(
    samples=st.integers(0, 600),
    chunk=st.integers(20, 120),
    overlap=st.integers(2, 6),
    channels=st.integers(1, 2),
    seed=st.integers(0, 10),
)
def test_an_identity_model_returns_the_input(
    samples: int, chunk: int, overlap: int, channels: int, seed: int
) -> None:
    audio = noise(channels, samples, seed)
    plan = plan_chunks(samples, chunk, overlap)
    result = overlap_add(audio, plan, lambda piece: piece.copy())
    assert result.shape == audio.shape
    assert np.allclose(result, audio, atol=1e-5)


def test_the_model_sees_chunks_of_the_chunk_size_and_the_result_is_blended() -> None:
    audio = noise(2, 300, seed=3)
    plan = plan_chunks(300, 64, 4)
    seen: list[tuple[int, ...]] = []

    def halve(piece: Audio) -> Audio:
        seen.append(piece.shape)
        return piece * np.float32(0.5)

    result = overlap_add(audio, plan, halve)
    assert set(seen) == {(2, 64)}
    assert len(seen) == len(plan.starts)
    assert np.allclose(result, audio * 0.5, atol=1e-5)


def test_progress_is_reported_after_every_chunk() -> None:
    plan = plan_chunks(50, 20, 2)
    calls: list[tuple[int, int]] = []
    overlap_add(
        noise(1, 50), plan, lambda piece: piece, lambda done, total: calls.append((done, total))
    )
    total = len(plan.starts)
    assert calls == [(i, total) for i in range(1, total + 1)]


def test_audio_of_another_length_than_the_plan_is_refused() -> None:
    with pytest.raises(ValueError, match="the plan is for 50 samples"):
        overlap_add(noise(1, 40), plan_chunks(50, 20, 2), lambda piece: piece)


def test_a_model_that_returns_the_wrong_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="came back as"):
        overlap_add(noise(2, 40), plan_chunks(40, 20, 2), lambda piece: piece[:1])


def test_mixing_adds_the_stems() -> None:
    first, second = noise(2, 10, 1), noise(2, 10, 2)
    assert np.allclose(mix_stems(first, second), first + second)
    with pytest.raises(ValueError, match="cannot mix"):
        mix_stems(first, noise(2, 11))


def test_a_stem_within_full_scale_is_left_alone() -> None:
    stem = noise(2, 100, scale=1.0)
    stem[0, 0] = 1.0  # exactly full scale is not above it
    scaled, gain = apply_headroom(stem)
    assert gain == 1.0
    assert scaled is stem


def test_a_stem_above_full_scale_is_scaled_to_minus_point_one_dbfs() -> None:
    stem = noise(2, 100, scale=0.5)
    stem[1, 5] = -1.8
    scaled, gain = apply_headroom(stem)
    assert gain == pytest.approx(CEILING / 1.8)
    assert peak(scaled) == pytest.approx(CEILING, rel=1e-6)
    assert np.allclose(scaled, stem * np.float32(gain))  # linear: no limiter, no other change


@given(top=st.floats(1.0001, 50.0), seed=st.integers(0, 5))
def test_headroom_always_ends_below_full_scale(top: float, seed: int) -> None:
    stem = noise(2, 64, seed)
    stem[0, 0] = top
    scaled, gain = apply_headroom(stem)
    assert peak(scaled) <= 1.0
    assert 0 < gain < 1


def test_silence_and_empty_audio_have_no_peak_and_no_gain() -> None:
    assert apply_headroom(np.zeros((2, 5), dtype=np.float32))[1] == 1.0
    assert peak(np.zeros((2, 0), dtype=np.float32)) == 0.0


def test_the_karaoke_model_input_is_scaled_to_a_peak_of_point_nine() -> None:
    scaled, factor = normalise_peak(noise(2, 50, scale=0.3))
    assert peak(scaled) == pytest.approx(KARAOKE_INPUT_PEAK, rel=1e-6)
    assert factor > 1
    quiet, same = normalise_peak(np.zeros((2, 4), dtype=np.float32))
    assert same == 1.0
    assert not quiet.any()


@pytest.mark.parametrize(("device", "expected"), [("cuda", 2 * 600 + 120), ("cpu", 30 * 600 + 120)])
def test_the_timeout_is_a_multiple_of_the_song_plus_two_minutes(
    device: str, expected: float
) -> None:
    assert timeout_seconds(600, "cuda" if device == "cuda" else "cpu", 2, 30) == expected


def test_the_timeout_base_can_be_changed() -> None:
    assert timeout_seconds(10, "cpu", 2, 3, base=1.0) == 31.0
    assert TIMEOUT_BASE == 120.0


def test_cpu_is_always_cpu_without_a_warning() -> None:
    choice = choose_device("cpu", 8 * GIB)
    assert (choice.device, choice.warning) == ("cpu", None)


@pytest.mark.parametrize("request_", ["auto", "cuda"])
def test_a_gpu_with_enough_free_memory_is_used(request_: str) -> None:
    assert choose_device("auto" if request_ == "auto" else "cuda", MIN_FREE_VRAM).device == "cuda"


def test_auto_falls_back_to_the_cpu_with_a_warning() -> None:
    no_gpu = choose_device("auto", None)
    assert no_gpu.device == "cpu"
    assert "no usable GPU" in str(no_gpu.warning)
    assert "20x slower" in str(no_gpu.warning)
    full = choose_device("auto", MIN_FREE_VRAM - 1)
    assert full.device == "cpu"
    assert "GiB of GPU memory are free" in str(full.warning)


def test_a_forced_gpu_that_cannot_work_is_a_clear_error() -> None:
    with pytest.raises(StageError, match="no usable GPU") as none:
        choose_device("cuda", None)
    assert none.value.kind == "no-gpu"
    with pytest.raises(StageError, match=r"1\.0 GiB .* free; 2 GiB are needed") as small:
        choose_device("cuda", GIB)
    assert small.value.kind == "vram-too-small"


def test_the_device_messages_are_exact() -> None:
    assert choose_device("auto", None).warning == (
        "no usable GPU was found; separating on the CPU, which is about 20x slower"
    )
    assert choose_device("auto", GIB + GIB // 2).warning == (
        "only 1.5 GiB of GPU memory are free; separating on the CPU, which is about 20x slower"
    )
    with pytest.raises(StageError) as none:
        choose_device("cuda", None)
    assert str(none.value) == "device cuda was asked for, but no usable GPU was found"


MIX = np.linspace(-0.5, 0.5, 200, dtype=np.float32).reshape(2, 100)


def test_one_vocals_estimate_gives_itself_and_the_rest() -> None:
    estimate = MIX * np.float32(0.3)
    vocals, instrumental = combine_estimates(MIX, [(estimate, "vocals")])
    assert np.array_equal(vocals, estimate)
    assert np.array_equal(instrumental, MIX - estimate)


def test_one_instrumental_estimate_gives_itself_and_the_rest() -> None:
    estimate = MIX * np.float32(0.7)
    vocals, instrumental = combine_estimates(MIX, [(estimate, "instrumental")])
    assert np.array_equal(instrumental, estimate)
    assert np.array_equal(vocals, MIX - estimate)


def test_several_estimates_are_averaged_as_instrumentals_and_the_vocals_are_the_rest() -> None:
    from_vocals = MIX * np.float32(0.2)  # an instrumental of 0.8 MIX
    direct = MIX * np.float32(0.6)
    vocals, instrumental = combine_estimates(
        MIX, [(from_vocals, "vocals"), (direct, "instrumental")]
    )
    assert np.allclose(instrumental, MIX * 0.7)
    assert np.allclose(vocals, MIX * 0.3)
    assert np.allclose(vocals + instrumental, MIX)


def test_combining_nothing_or_estimates_of_the_wrong_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="^no estimates to combine$"):
        combine_estimates(MIX, [])
    with pytest.raises(ValueError, match="shape"):
        combine_estimates(MIX, [(MIX[:, :50], "vocals")])
