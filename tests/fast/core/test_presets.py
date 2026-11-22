"""Stage 1: output presets and the audio settings (ADR-0009)."""

import pytest
from pydantic import ValidationError

from vocatron.core.presets import (
    DEFAULT_BITRATES,
    DEFAULT_PRESET,
    PRESETS,
    AudioSettings,
    audio_bitrate,
)


def test_the_default_preset_is_classic_four_by_three() -> None:
    preset = PRESETS[DEFAULT_PRESET]
    assert (preset.width, preset.height, preset.fps, preset.codec) == (960, 720, 30, "libx264")
    assert preset.quality == 18


def test_the_presets_of_the_adr_exist() -> None:
    assert {"4x3-720", "16x9-720", "16x9-1080", "av1-720", "4x3-720-nvenc"} == set(PRESETS)
    assert (PRESETS["16x9-1080"].width, PRESETS["16x9-1080"].height) == (1920, 1080)
    assert PRESETS["av1-720"].codec == "libsvtav1"
    assert PRESETS["4x3-720-nvenc"].codec == "h264_nvenc"


def test_every_preset_is_named_by_its_key_and_has_an_even_size() -> None:
    for name, preset in PRESETS.items():
        assert preset.name == name
        assert preset.width % 2 == 0 and preset.height % 2 == 0  # yuv420p needs even sizes


def test_the_audio_defaults_are_fdkaac_at_192_and_no_export() -> None:
    audio = AudioSettings()
    assert (audio.encoder, audio.bitrate, audio.export) == ("fdkaac", None, "none")
    assert audio_bitrate(audio, PRESETS[DEFAULT_PRESET]) == 192


def test_the_ffmpeg_encoder_defaults_to_256() -> None:
    assert audio_bitrate(AudioSettings(encoder="ffmpeg-aac"), PRESETS[DEFAULT_PRESET]) == 256
    assert DEFAULT_BITRATES == {"fdkaac": 192, "ffmpeg-aac": 256}


def test_the_setting_beats_the_preset_and_the_preset_beats_the_encoder() -> None:
    asking = PRESETS[DEFAULT_PRESET].model_copy(update={"audio_bitrate": 128})
    assert audio_bitrate(AudioSettings(), asking) == 128
    assert audio_bitrate(AudioSettings(bitrate=320), asking) == 320


@pytest.mark.parametrize(
    "settings", [{"encoder": "lame"}, {"export": "ogg"}, {"bitrate": 0}, {"x": 1}]
)
def test_wrong_audio_settings_are_refused(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AudioSettings.model_validate(settings)
