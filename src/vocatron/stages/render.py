"""The ``render`` stage: the karaoke video, the audio and the enhanced LRC (ADR-0009).

It hands the subtitle file and the karaoke stem to the renderer, which encodes the audio once and
burns the lyrics into an MP4, and writes the enhanced LRC next to it. The files go to the output
folder as ``Artist - Title.mp4`` and ``.lrc``, and ``.m4a`` or ``.flac`` when ``audio.export``
asks for one (ADR-0048); the stage file ``render.json`` in the work folder lists them. The stage
is skipped only when they all exist. An audio export that an earlier run listed in ``render.json``
and this run does not make is deleted.
"""

from pathlib import Path
from typing import override

from pydantic import BaseModel

from vocatron.core.errors import StageError
from vocatron.core.layout.file import LayoutFile
from vocatron.core.lrc import Heading, enhanced_lrc
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.presets import PRESETS, AudioSettings, Preset
from vocatron.core.render import RenderFile
from vocatron.core.separation.file import stem_path
from vocatron.core.song import SongInfo, media_tags
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.core.syllables import SyllablesFile
from vocatron.engines.protocols import RenderRequest
from vocatron.stages.config import Config
from vocatron.stages.layout import ASS_FILE, LAYOUT_FILE
from vocatron.stages.stage import Song, StageContext, TypedStage, read_input

RENDER_STAGE = "render"
LRC_SUFFIX = ".lrc"
SIDECAR_SUFFIXES = (".lrc", ".txt")
EXPORT_SUFFIXES = (".m4a", ".flac")


class RenderSettings(BaseModel):
    """What the render depends on: the preset and the audio settings."""

    preset: Preset
    audio: AudioSettings


class RenderStage(TypedStage[RenderSettings]):
    """Renders the video and writes the files of the finished track."""

    name = RENDER_STAGE
    # 2: the enhanced LRC marks a change of singers inside a line; 3: BT.709 colour tags;
    # 4: the silent intro (``Scene.lead``) shifts the audio, the exports and the LRC;
    # 5: artist, title, genre and comment tags in the MP4 (ADR-0031)
    # 6: Vocatron writes the MP4's tags itself, with Duet to Quintet in TAG (ADR-0047)
    # 7: no audio export by default; an export the run no longer makes is deleted (ADR-0048)
    # 8: the enhanced LRC marks the second voice with `{&}` and keeps the lines in time order
    # 9: the lyrics.ass of the start screen with the wordmark (ADR-0055)
    # 10: the silent intro is 8 s solo and 9 s group, the start screen lasts at least four seconds
    # (ADR-0020)
    # 11: the lyrics.ass of the end screen with the wordmark and of the break screen with the V
    # symbol (ADR-0057)
    # 12: the lyrics.ass of a scroll look with the break screen alone and the lines fading out
    # before it (ADR-0040)
    version = 12
    inputs = (
        LAYOUT_FILE,
        ASS_FILE,
        stem_path("karaoke"),
        "syllables.json",
        "lyrics.json",
        "song.json",
    )
    output = "render.json"
    output_model = RenderFile

    def settings_from(self, config: Config) -> RenderSettings:
        """Return the preset and the audio settings."""
        return RenderSettings(preset=PRESETS[config.preset], audio=config.audio)

    @override
    def products(self, ctx: StageContext, stored: StageFile) -> tuple[Path, ...]:
        """Return the finished files in the output folder that ``render.json`` lists."""
        if not isinstance(stored, RenderFile):
            return ()
        return tuple(ctx.song.output_dir / name for name in stored.files)

    def run(
        self, ctx: StageContext, settings: RenderSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Render the video, write the enhanced LRC and ``render.json``.

        Raises:
            StageError: ``output-collision`` if an output file would replace the song or its
                lyrics file, ``missing-input``, or the renderer's errors (``missing-tool``,
                ``render-failed``, ``render-timeout``, ``wrong-font``).
        """
        song = ctx.song
        exported: dict[str, list[str]] = {"m4a": [".m4a"], "flac": [".flac"], "none": []}
        refuse_collisions(
            ctx,
            [
                f"{song.name}{suffix}"
                for suffix in (".mp4", LRC_SUFFIX, *exported[settings.audio.export])
            ],
        )
        layout = read_input(ctx, LAYOUT_FILE, LayoutFile)
        syllables = read_input(ctx, "syllables.json", SyllablesFile)
        lyrics = read_input(ctx, "lyrics.json", LyricsFile)
        info = read_input(ctx, "song.json", SongInfo)
        lead = layout.scene.lead
        request = RenderRequest(
            ass=song.work_dir / ASS_FILE,
            audio=song.work_dir / stem_path("karaoke"),
            work_dir=song.work_dir,
            output_dir=song.output_dir,
            name=song.name,
            preset=settings.preset,
            audio_settings=settings.audio,
            background=layout.scene.background,
            motion=layout.scene.background_motion,
            duration=None if info.duration is None else info.duration + lead,
            log=ctx.log,
            watch=ctx.watch,
            lead=lead,
            tags=media_tags(info, lyrics),
        )
        result = ctx.engines.renderer.render(request)
        lrc = f"{song.name}{LRC_SUFFIX}"
        heading = Heading(info.title, info.artist, info.duration)
        text = enhanced_lrc(
            syllables.words, lyrics.lines, heading, lyrics.singers, lead, syllables.voices
        )
        ctx.engines.store.write_text(song.output_dir / lrc, text)
        ctx.log(f"render: wrote {', '.join(result.files)}, {lrc} in {result.seconds:.1f} s")
        files = [*result.files, lrc]
        delete_stale_exports(ctx, files)
        return RenderFile(
            fingerprint=fingerprint,
            preset=settings.preset.name,
            audio_encoder=result.audio_encoder,
            files=files,
            fonts=list(result.fonts),
            seconds=round(result.seconds, 2),
        )


def delete_stale_exports(ctx: StageContext, made: list[str]) -> None:
    """Delete the audio export that the previous ``render.json`` lists and ``made`` lacks.

    Only a file named in Vocatron's own ``render.json``, directly in the output folder (the
    work folder, and so ``render.json``, lies inside it, so another ``--output`` has its own).
    Never a file with the name of the song itself or of its lyrics file: when the output
    folder is the song folder, an old export can have become a song of its own. Names, not
    paths, are compared, because a symlink or ``..`` can make two paths one file; an export
    named like the song file is so left in any output folder. Names are compared without case,
    so a file this run made on a case-insensitive file system is never taken for a stale one.
    """
    store, song = ctx.engines.store, ctx.song
    try:
        text = store.read_text(song.work_dir / RenderStage.output)
        previous = None if text is None else RenderFile.model_validate_json(text)
    except OSError, ValueError:
        return  # no usable earlier file: nothing is known to be Vocatron's
    if previous is None:
        return
    kept = {name.casefold() for name in [*made, *(path.name for path in song_files(song))]}
    for name in previous.files:
        if not name.endswith(EXPORT_SUFFIXES) or Path(name).name != name:
            continue  # not an audio export, or not a plain name in the output folder
        if name.casefold() in kept:
            continue
        try:
            store.delete(song.output_dir / name)
        except OSError as error:
            ctx.log(f"render: could not delete {name}: {error}")
            continue
        ctx.log(f"render: deleted {name}, the audio export is off")


def refuse_collisions(ctx: StageContext, names: list[str]) -> None:
    """Refuse to write over the song itself or its lyrics file when the output folder is theirs.

    Raises:
        StageError: ``output-collision``.
    """
    song = ctx.song
    owned = song_files(song)
    clash = [name for name in names if song.output_dir / name in owned]
    if clash:
        raise StageError(
            "output-collision",
            f"{clash[0]} in the output folder would replace a file of the song; "
            "choose another output folder with --output",
        )


def song_files(song: Song) -> set[Path]:
    """Return the files that belong to the song: the audio file and its possible lyrics files."""
    return {song.source, *(song.source.with_suffix(suffix) for suffix in SIDECAR_SUFFIXES)}
