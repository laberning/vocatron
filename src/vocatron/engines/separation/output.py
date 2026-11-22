"""Writing the stems: 24-bit FLAC at 44.1 kHz, none above full scale (ADR-0002)."""

from pathlib import Path

import soundfile as sf

from vocatron.core.separation.file import STEM_NAMES, stem_path
from vocatron.core.separation.job import StemGains
from vocatron.core.separation.rules import SAMPLE_RATE, Audio, apply_headroom, mix_stems


def write_flac(path: Path, audio: Audio) -> None:
    """Write (channels, samples) audio as 24-bit FLAC; the file appears complete or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    sf.write(partial, audio.T, SAMPLE_RATE, format="FLAC", subtype="PCM_24")
    partial.replace(path)


def write_stems(
    work_dir: Path, lead: Audio, backing: Audio, instrumental: Audio, *, keep_backing: bool
) -> StemGains:
    """Write the four stems of a song below ``work_dir`` and return the headroom gains.

    The karaoke mix is the instrumental plus the backing vocals, or the instrumental alone without
    ``keep_backing``; it is scaled after mixing. A stem above full scale is scaled down to
    -0.1 dBFS, and the gain is returned so that it is on record.
    """
    karaoke = mix_stems(instrumental, backing) if keep_backing else instrumental
    stems = dict(zip(STEM_NAMES, (lead, backing, instrumental, karaoke), strict=True))
    gains: dict[str, float] = {}
    for name, audio in stems.items():
        scaled, gains[name] = apply_headroom(audio)
        write_flac(work_dir / stem_path(name), scaled)
    return StemGains(**gains)
