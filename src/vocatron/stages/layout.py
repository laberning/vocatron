"""The ``layout`` stage: what is on screen when (ADR-0009).

It turns the syllable times, the lyrics and the song info into the scene of the song with the
style profile (``vocatron.core.layout``), writes it as ``layout.json`` and draws it into the ASS
file ``lyrics.ass`` that the render stage burns into the video. No AI stage runs again when the
profile or the preset changes; only this one does.
"""

from dataclasses import dataclass
from typing import override

from pydantic import BaseModel, Field, JsonValue

from vocatron.core.ass.write import write_ass
from vocatron.core.errors import StageError
from vocatron.core.glyphs import UndrawableLetter
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.file import LayoutFile
from vocatron.core.layout.phrases import Phrase, phrases_from
from vocatron.core.layout.start_text import drawable_text
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import Profile, profile_problems
from vocatron.core.song import SongInfo
from vocatron.core.stage_file import Fingerprint, StageFile, hash_bytes
from vocatron.core.syllables import SyllablesFile
from vocatron.core.tempo import TempoFile
from vocatron.stages.alignment import module_of
from vocatron.stages.config import Config
from vocatron.stages.profiles import folder_path, load_profile, profile_text
from vocatron.stages.stage import StageContext, TypedStage, read_input
from vocatron.stages.tempo import TEMPO_FILE

LAYOUT_STAGE = "layout"
LAYOUT_FILE = "layout.json"
ASS_FILE = "lyrics.ass"
PROFILE_INPUT = "profile"
REVIEW_KINDS = ("too-wide", "block")  # shortfalls that need a look; the others are only logged


class ProfileSettings(BaseModel):
    """The choice of the style profile, which the stages that lay out a song share.

    Attributes:
        profile: The profile name or path.
        overrides: The values that replace those of the profile.
        folder: The ``profiles_folder``. It stays out of the fingerprint (the text of the profile
            is in it), so setting the folder re-runs nothing.
    """

    profile: str
    overrides: dict[str, JsonValue]
    folder: str | None = Field(default=None, exclude=True)


class LayoutSettings(ProfileSettings):
    """What the layout depends on: the profile and the frame size of the preset.

    Attributes:
        width: The frame width of the preset.
        height: The frame height of the preset.
    """

    width: int
    height: int


@dataclass(frozen=True)
class SongLayout:
    """What laying out a song needs, read from the work folder.

    Attributes:
        profile: The style profile.
        phrases: The sung lines with the time of every syllable.
        text: Title, artist, length, singers and tempo, without the symbols the font cannot draw.
        dropped: A review reason for every symbol dropped from title, artist and singer names.
    """

    profile: Profile
    phrases: list[Phrase]
    text: SongText
    dropped: tuple[str, ...] = ()


def profile_inputs(ctx: StageContext, config: Config) -> dict[str, str]:
    """Return the hash of the profile's text (a built-in profile or the user's file)."""
    engines = ctx.engines
    try:
        found = profile_text(
            config.profile,
            folder_path(config.profiles_folder),
            engines.store,
            engines.resources,
        )
    except StageError:  # an unreadable file fails the run itself, with its message
        return {}
    return {} if found is None else {PROFILE_INPUT: hash_bytes(found.text.encode())}


def prepare_layout(ctx: StageContext, settings: ProfileSettings) -> SongLayout:
    """Load the profile and read the stage files the layout of a song is made from.

    Raises:
        StageError: ``invalid-profile`` if the profile does not load, ``missing-input`` if
            an input is missing.
    """
    engines = ctx.engines
    profile = load_profile(
        settings.profile,
        settings.overrides,
        folder_path(settings.folder),
        engines.store,
        engines.resources,
    )
    syllables = read_input(ctx, "syllables.json", SyllablesFile)
    lyrics = read_input(ctx, "lyrics.json", LyricsFile)
    info = read_input(ctx, "song.json", SongInfo)
    tempo = read_input(ctx, TEMPO_FILE, TempoFile)
    language = module_of(syllables.language)  # the words for singing together
    try:
        shown = drawable_text(
            info.title,
            info.artist,
            lyrics.singers,
            engines.resources.drawable_characters(),
            capitals=profile.title.form == "wordmark",
        )
    except UndrawableLetter as error:
        raise StageError("undrawable-character", str(error)) from error
    text = SongText(
        shown.title,
        shown.artist,
        info.duration,
        shown.singers,
        language.together_two,
        language.together_all,
        tempo.bpm,
    )
    phrases = phrases_from(syllables.words, lyrics.lines, profile.font.case, syllables.voices)
    return SongLayout(profile, phrases, text, shown.dropped)


class LayoutStage(TypedStage[LayoutSettings]):
    """Builds the scene of the song and its subtitle file."""

    name = LAYOUT_STAGE
    # 2: a sung line stays in a short gap (rule 11); 3: gaps in the scene's precision;
    # 4: page mode, previews, progress bars (layout.json v2); 5: lines are never merged, a change
    # of singers inside a line is a turn (layout.json v3); 6: a line wrapped onto rows (profile
    # ``line_rows``) is one block of lines that share slot and times; 7: the silent intro
    # (``Scene.lead``, layout.json v4) and the entries for lines sung together on the title screen;
    # 8: countdowns count beats of the song's tempo (``tempo.json``, layout.json v5, ADR-0022);
    # 9: a countdown never starts before the line before it ends (ADR-0026); 10: a countdown in
    # beats ends one beat before the line (layout.json v6, ADR-0028); 11: two rows over two slots
    # (``page.slot_per_row``), the row and part of a line, the parts of a split line in
    # neighbouring slots in line mode, the timer of a break screen (layout.json v7), and the title
    # and break screens that shrink to fit; 12: the effects of the video-only looks (ADR-0032):
    # glow, pop, upcoming dim, transitions (``enter`` and ``exit`` of a line) and a moving
    # background (layout.json v8); 13: scroll mode (ADR-0033): the path of a line, the measures of
    # the column and the dimming of sung lines (layout.json v9); 14: after a long gap the lines
    # start again at the top, and lines go in the order they were sung (ADR-0034); 15: a minimum
    # glide in scroll mode, the glide may start during the end of the line before (ADR-0036;
    # layout.json v10); 16: the glow of a sung line in scroll mode is dimmed with it (lyrics.ass)
    # 17: the hold after the last line gives way to the end screen (ADR-0037); 18: lines turn in
    # blocks (profile ``block``, ADR-0038); 19: a short group sits next to the middle (ADR-0039);
    # 20: the break notice glides with the column (ADR-0040; layout.json v11); 21: symbols the font
    # cannot draw are dropped from title, artist and singer names, a letter it lacks fails the stage
    # (ADR-0046); 22: the glow is a blurred copy of the text swept with it (lyrics.ass)
    # 23: lines of two voices sung at once stand side by side in line mode and blocks, the voice of
    # every line (layout.json v12, ADR-0054)
    # 24: lines of several rows sung at once are paired row by row; a pair of more than two rows
    # takes the rows of both blocks (ADR-0054)
    # 25: a group turns line by line when its block frees late next to the other voice (ADR-0054)
    # 26: also when the other voice held its block until less than the minimum lead-in before it
    # 27: the start screen with the wordmark, the title card's mark (layout.json v13, ADR-0055)
    # 28: the mark of the title screen can be made of pixel letters for CD+G (layout.json v14,
    # ADR-0056); the silent intro is 8 s solo and 9 s group, the start screen at least 4 s
    # (ADR-0020)
    # 29: a long title or artist wraps onto two lines at a word on the start screen with the
    # wordmark; on CD+G a text below ``cdg.min_font_px`` gives the plain card (ADR-0056)
    # 30: the CD+G start screen has sizes of its own (22, 15, 13 px, floor 12 px), the rows of a
    # wrapped text share a size and stand closer, the singers' names stand side by side over as
    # few rows as fit, on the video's start screen too (ADR-0056)
    # 31: the end screen is the wordmark screen of the start without the build-up, the break
    # screen has the V symbol above its notice (layout.json v15, ADR-0057)
    # 32: in a scroll look a long break is a screen of its own: the column goes, the break screen
    # stands alone, the column comes in from below again (layout.json v16, ADR-0040)
    version = 32
    inputs = ("syllables.json", "lyrics.json", "song.json", TEMPO_FILE)
    output = LAYOUT_FILE
    extra_outputs = (ASS_FILE,)
    output_model = LayoutFile

    def settings_from(self, config: Config) -> LayoutSettings:
        """Return the profile with its overrides and the frame size of the preset."""
        preset = PRESETS[config.preset]
        return LayoutSettings(
            profile=config.profile,
            overrides=config.profile_overrides,
            width=preset.width,
            height=preset.height,
            folder=config.profiles_folder,
        )

    @override
    def external_inputs(self, ctx: StageContext, config: Config) -> dict[str, str]:
        """Return the hash of the profile's text."""
        return profile_inputs(ctx, config)

    def run(
        self, ctx: StageContext, settings: LayoutSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Write ``layout.json`` and ``lyrics.ass``.

        Raises:
            StageError: ``invalid-profile`` if the profile does not load, ``missing-input`` if
                an input is missing.
        """
        engines = ctx.engines
        prepared = prepare_layout(ctx, settings)
        profile = prepared.profile
        frame = (settings.width, settings.height)
        scene = layout(prepared.phrases, prepared.text, profile, frame, engines.measurer)
        engines.store.write_text(ctx.song.work_dir / ASS_FILE, write_ass(scene))
        for found in scene.shortfalls:
            where = "" if found.line is None else f" line {found.line}:"
            ctx.log(f"layout: shortfall ({found.kind}){where} {found.message}")
        if scene.lead:
            ctx.log(f"layout: {scene.lead:.2f} s of silence added before the song")
        ctx.log(f"layout: {len(scene.elements)} elements with profile {profile.name}")
        if scene.bpm is None:
            ctx.log(f"layout: countdowns run over {profile.countdown.duration:g} s (tempo unclear)")
        else:
            ctx.log(f"layout: countdowns count beats at {scene.bpm:.1f} BPM")
        reasons = [f.message for f in scene.shortfalls if f.kind in REVIEW_KINDS]
        reasons += prepared.dropped
        reasons += [f"colours: {problem}" for problem in profile_problems(profile)]
        return LayoutFile(
            fingerprint=fingerprint, reasons=sorted(set(reasons)), profile=profile.name, scene=scene
        )
