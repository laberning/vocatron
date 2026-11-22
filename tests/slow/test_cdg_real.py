"""Stage 2: the CD+G pair made with the real tools (ADR-0023, ADR-0024, ADR-0025).

A public-domain song is laid out with the real font and written as CD+G; ffmpeg's own
``cdgraphics`` decoder must show the same pictures as ours, and the MP3 made by real ffmpeg and
LAME must have the format and the length the scene asks for. No GPU, no corpus.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from cdgreal import (
    differing,
    entchen_stream,
    ffmpeg_frames,
    our_frames,
    piece_stream,
    sample_packets,
)
from vocatron.core.ffmpeg_cmd import MP3_BITRATE, MP3_RATE
from vocatron.core.id3 import id3_tag
from vocatron.core.layout.sample import sample_piece
from vocatron.core.profiles.model import CLASSIC_PROFILES
from vocatron.engines.protocols import Mp3Request
from vocatron.engines.render import FfmpegRenderer
from vocatron.engines.resources import PackageResources

MP3_TOLERANCE = 0.05  # seconds the MP3 may differ from the scene's duration
pytestmark = [
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"),
    pytest.mark.timeout(600),
]


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_ffmpegs_cdgraphics_decoder_shows_our_frames_in_every_look(
    tmp_path: Path, look: str
) -> None:
    scene, result = entchen_stream(look=look)
    file = tmp_path / "Song.cdg"
    file.write_bytes(result.stream)
    packets = sample_packets(scene, result.stream)
    assert len(packets) > 40
    ours, theirs = our_frames(result.stream, packets), ffmpeg_frames(file, packets)
    differences = differing(packets, ours, theirs)
    assert differences == []  # packet and pixels that differ, if any


def test_ffmpegs_cdgraphics_decoder_shows_our_frames_for_a_wrapped_line_and_the_timer(
    tmp_path: Path,
) -> None:
    """The long first line of the sample song is two rows over two slots in ``tall-page``, and its
    long gap is a break with a timer in ``three-line``."""
    for look in ("tall-page", "three-line"):
        scene, result = piece_stream(sample_piece(), look)
        feature = (
            any(x.row == 1 for x in scene.lines())
            if look == "tall-page"
            else (any(e.kind == "timer" for e in scene.elements))
        )
        assert feature, f"{look} shows no wrapped line or timer"
        file = tmp_path / f"{look}.cdg"
        file.write_bytes(result.stream)
        packets = sample_packets(scene, result.stream)
        ours, theirs = our_frames(result.stream, packets), ffmpeg_frames(file, packets)
        assert differing(packets, ours, theirs) == [], look


def probe(path: Path) -> dict[str, Any]:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    return json.loads(done.stdout)


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_the_mp3_is_lame_192_kbit_44100_hz_stereo_and_as_long_as_the_scene(tmp_path: Path) -> None:
    scene, _ = entchen_stream(start=1.0)  # the first word is early: the video starts with silence
    assert scene.lead > 0
    song = tmp_path / "karaoke.flac"
    rate = 48000  # not the rate of the MP3: it is resampled
    seconds = scene.duration - scene.lead
    tone = np.sin(2 * np.pi * 440 * np.arange(int(seconds * rate)) / rate) * 0.2
    sf.write(song, np.stack([tone, tone], axis=1), rate)
    target = tmp_path / "Artist - Title.mp3"
    FfmpegRenderer(PackageResources().fonts_dir()).encode_mp3(
        Mp3Request(song, target, scene.lead, scene.duration, log=lambda message: None)
    )
    found = probe(target)
    (stream,) = found["streams"]
    assert stream["codec_name"] == "mp3"
    assert (int(stream["sample_rate"]), stream["channels"]) == (MP3_RATE, 2)
    assert abs(int(stream["bit_rate"]) - MP3_BITRATE * 1000) <= 2000
    length = float(found["format"]["duration"])
    assert abs(length - scene.duration) <= MP3_TOLERANCE, f"{length:.3f} s for {scene.duration} s"
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".mp3"] == [target.name]


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_the_real_mp3_carries_exactly_the_tags_it_was_given_as_id3v24(tmp_path: Path) -> None:
    tags = (
        ("title", 'Alle "meine" Entchen; a=b \U0001f3a4 \u00fcber \u65e5\u672c'),
        ("artist", "Volkslied"),
        ("genre", "Karaoke"),
        ("comment", "Karaoke version made with Vocatron"),
        ("tag", "Duet"),
    )
    song = tmp_path / "karaoke.flac"
    rate = 48000
    tone = np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 0.2
    with sf.SoundFile(song, "w", rate, 2, format="FLAC") as out:
        out.album = "Original Album"  # the input's own tag, which must not be copied
        out.write(np.stack([tone, tone], axis=1))
    target = tmp_path / "Volkslied - Entchen.mp3"
    FfmpegRenderer(PackageResources().fonts_dir()).encode_mp3(
        Mp3Request(song, target, 0.0, 1.0, log=lambda message: None, tags=tags)
    )
    assert target.read_bytes()[:4] == b"ID3\x04"  # ID3v2.4
    found = probe(target)["format"]["tags"]
    seen = {k.lower(): v for k, v in found.items() if k.lower() != "encoder"}  # ffmpeg's own
    assert seen == dict(tags), "a tag differs or was copied"
    raw = target.read_bytes()
    assert raw.startswith(id3_tag(tags)), "the MP3 does not start with exactly Vocatron's tag"
    assert raw.count(b"TXXX") == 1  # the TAG field and no other user-defined frame (ADR-0047)
