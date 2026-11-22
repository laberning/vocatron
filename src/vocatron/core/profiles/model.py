"""Style profiles: how the lyrics look and when they appear (ADR-0009).

A profile is a YAML file, validated by the models below. Errors name file, line and column. Single
values can be overridden (``profile_overrides`` in the configuration); an error in an overridden
value is reported against the override, since the file does not hold it. The built-in profiles
are listed in ``BUILTIN_PROFILES``; their YAML ships with the package.

Sizes are shares: the font size of the share of the height of the safe area (the height of the
line cell, which is what an ASS ``Fontsize`` is), edge and shadow of the font size. The optional
``cdg`` section (ADR-0029) is the exception: the CD+G screen has few pixels, so it counts in them.

The five effect sections ``glow``, ``pop``, ``transition``, ``upcoming`` and ``background_motion``
(ADR-0032) are off by default; they are for looks that are MP4 only. So is ``mode: scroll`` with
its ``scroll`` section (ADR-0033): the lyrics as a column that glides up.
"""

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from vocatron.core.colour import HEX_PATTERN, blend, contrast_ratio, distance, luminance
from vocatron.core.config_errors import Issue, Location, Positions, describe_all
from vocatron.core.yaml_pos import YamlSyntaxError, parse_yaml

CLASSIC_PROFILES = (
    "two-line-turns",
    "four-line-stack",
    "full-page",
    "blue-page",
    "one-line-preview",
    "tall-page",
    "three-line",
)
"""The looks that follow classic karaoke discs; each is made for CD+G too (ADR-0029)."""
VIDEO_ONLY_PROFILES = ("neon", "lyric-video", "lyric-scroll")
"""The looks that use the effects of the video (ADR-0032) or scroll (ADR-0033); they have no
``cdg`` section."""
BUILTIN_PROFILES = (*CLASSIC_PROFILES, *VIDEO_ONLY_PROFILES)
DEFAULT_PROFILE = "four-line-stack"
MAX_SLOTS = 6
MAX_LINE_ROWS = 2
SINGER_KEYS = ("singer1", "singer2", "singer3", "singer4", "singer5")

MIN_TEXT_CONTRAST = 3.0
"""WCAG ratio that sung and unsung text need against the background, and the edge against the
text (rule 18)."""
MIN_FILL_DISTANCE = 100.0
"""How far apart (sRGB distance) the unsung and the sung colour of a singer must be."""
MIN_WIPE_CONTRAST = 1.5
"""WCAG ratio that the unsung and the sung colour of a singer need between them, so the wipe can be
seen by its lightness and not by its hue alone. Yellow on white (1.07) is hard to follow in a
video, and light cyan or light green on white (1.2 to 1.3) hardly better; the palest sung colour of
a built-in look, gold on white in two-line-turns, has 1.51."""

MAX_POP_SCALE = 1.15
"""The most a word grows when it is sung (``pop.scale``)."""
MAX_DIM = 0.8
"""The most a line shown before it is sung is dimmed (``upcoming.dim``)."""
BACKGROUND_COLOURS = (2, 4)
"""How many colours a moving background has: at least and at most."""
EFFECT_KEYS = ("glow", "pop", "transition", "upcoming", "background_motion")
"""The profile sections that are effects of the video only (ADR-0032)."""
MAX_BLOCK = 3
"""The most lines in a block of a look that turns in blocks (``block``, ADR-0038)."""
MAX_BEFORE = 2
"""The most sung lines a scrolling column keeps above the line being sung (``scroll.before``)."""
MAX_AFTER = 4
"""The most upcoming lines it shows below (``scroll.after``)."""
MIN_GLIDE = 0.3
"""The shortest glide between two lines when ``scroll.min_glide`` is left out (or ``glide`` if
that is shorter, ADR-0036)."""

SAFE_HEIGHT_PX = 192
"""The height in pixels of the CD+G safe area (the 288 by 192 visible area, ADR-0023)."""
CDG_FONT_PX = (4, 76)
"""The line cell of a CD+G look in pixels; its share of 192 stays inside the limits of ``Font``."""
CDG_HEX_PATTERN = r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})"

Hex = Annotated[str, StringConstraints(pattern=HEX_PATTERN)]
CdgHex = Annotated[str, StringConstraints(pattern=CDG_HEX_PATTERN)]


class Strict(BaseModel):
    """Base of every part of a profile: no unknown keys, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Font(Strict):
    """The font (``font``).

    Attributes:
        family: A font shipped with Vocatron.
        size: Line height as a share of the height of the safe area.
        min_size: The smallest share a line may be shrunk to when one word does not fit.
        case: ``as-written``, ``upper`` or ``lower``.
    """

    family: Literal["bundled-sans-bold"] = "bundled-sans-bold"
    size: float = Field(default=0.12, gt=0.02, le=0.4)
    min_size: float = Field(default=0.08, gt=0.02, le=0.4)
    case: Literal["as-written", "upper", "lower"] = "as-written"

    @model_validator(mode="after")
    def _min_below_size(self) -> Self:
        if self.min_size > self.size:
            raise ValueError("min_size must not be larger than size")
        return self


class SingerColours(Strict):
    """The colours of one singer.

    Attributes:
        unsung: The text before the wipe reaches it.
        sung: The text after the wipe.
        edge: The outline.
    """

    unsung: Hex
    sung: Hex
    edge: Hex


class Colours(Strict):
    """Colours of the singers 1 to 5 and of ``group`` (``all:`` lines and lines of several)."""

    singer1: SingerColours
    singer2: SingerColours
    singer3: SingerColours
    singer4: SingerColours
    singer5: SingerColours
    group: SingerColours


class Edge(Strict):
    """The outline of the text (``edge``); ``width`` is a share of the font size."""

    width: float = Field(default=0.08, ge=0, le=0.3)


class Shadow(Strict):
    """The shadow (``shadow``); ``offset`` is a share of the font size, 0 for none."""

    offset: float = Field(default=0.0, ge=0, le=0.3)
    colour: Hex = "#000000"
    alpha: float = Field(default=0.6, ge=0, le=1)


class Wipe(Strict):
    """How the sung colour sweeps over the text (``wipe``).

    Attributes:
        granularity: ``smooth`` sweeps linearly through each syllable; ``syllable`` switches the
            whole syllable at its start.
        offset: Seconds that shift every wipe (negative: earlier).
    """

    granularity: Literal["smooth", "syllable"] = "smooth"
    offset: float = Field(default=0.0, ge=-0.5, le=0.5)


class LeadIn(Strict):
    """How long before its first syllable a line is on screen (``lead_in``), in seconds."""

    min: float = Field(default=1.0, ge=0)
    target: float = Field(default=2.5, ge=0)
    max: float = Field(default=3.0, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min <= self.target <= self.max:
            raise ValueError("lead_in needs min <= target <= max")
        return self


class Clear(Strict):
    """When sung lines go (``clear``).

    Attributes:
        hold: Before a long gap, the sung lines stay this long after the singing stops unless
            their slot is needed sooner or the line after the gap would get less than
            ``lead_in.min``; otherwise a sung line stays until its slot is needed.
        replace_after: A slot is refilled this long after the other line has started, or
            earlier if the line would otherwise get less than ``lead_in.min``.
    """

    hold: float = Field(default=1.5, ge=0)
    replace_after: float = Field(default=0.33, ge=0)


class Breaks(Strict):
    """Gaps in the singing (``breaks``).

    Attributes:
        clear_after: A gap of this many seconds or more is a long gap (the screen is cleared).
        notice_after: A gap of this many seconds or more gets a break screen.
        notice: The text of the break screen.
        show_title: Show title and artist on the break screen too.
        form: ``notice``: the text only; ``progress``: a bar under the text that fills until the
            next line appears; ``timer``: the whole seconds until the next lines appear, counting
            down under the text.
    """

    clear_after: float = Field(default=5.0, gt=0)
    notice_after: float = Field(default=15.0, gt=0)
    notice: str = Field(default="Instrumental", min_length=1)
    show_title: bool = False
    form: Literal["notice", "progress", "timer"] = "notice"

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.notice_after < self.clear_after:
            raise ValueError("notice_after must not be smaller than clear_after")
        return self


class Countdown(Strict):
    """The countdown before a line after a long gap (``countdown``).

    With a clear tempo the countdown counts ``count`` beats; without one it runs over
    ``duration`` seconds (ADR-0022).

    Attributes:
        min_gap: A countdown runs before the first line and after a gap of this many seconds.
            It never starts before the line before it ends (ADR-0026).
        duration: How long it runs in seconds when the song's tempo is unclear; it ends when the
            line starts.
        form: ``shrinking-bar``, ``dots`` or ``blocks`` (dots drawn as squares).
        count: The number of beats the countdown lasts when the tempo is clear, and the number
            of dots or blocks of those forms, which go out one per beat (ADR-0022).
    """

    min_gap: float = Field(default=5.0, gt=0)
    duration: float = Field(default=2.0, gt=0)
    form: Literal["shrinking-bar", "dots", "blocks"] = "shrinking-bar"
    count: int = Field(default=4, ge=1, le=8)


TitleField = Literal["title", "artist", "singers"]
"""What the title screen can show."""


def _all_title_fields() -> list[TitleField]:
    return ["title", "artist", "singers"]


DEFAULT_MIN_SHORT = 4.0
"""The shortest start screen of the default, in seconds: the wordmark builds up in it (ADR-0020)."""


class Title(Strict):
    """The title screen at the start (``title``).

    Attributes:
        min: How long it is shown at least, seconds.
        min_short: How short it may be made when the singing starts early.
        fields: What it shows, in order: ``title``, ``artist``, ``singers`` (the names from the
            lyrics file, each in its colour).
        form: ``wordmark`` for the start screen with the Vocatron wordmark on its own dark field,
            the title and artist in capitals in a frame below it (ADR-0055), or ``plain`` for a
            card of centred text in the colours of the look. CD+G follows it too (ADR-0056), but a
            start screen shorter than four seconds gets the plain card there.
    """

    min: float = Field(default=5.0, ge=0)
    min_short: float = Field(default=DEFAULT_MIN_SHORT, ge=0)
    fields: list[TitleField] = Field(default_factory=_all_title_fields)
    form: Literal["wordmark", "plain"] = "wordmark"

    @model_validator(mode="before")
    @classmethod
    def _short_follows_min(cls, data: object) -> object:
        """Let a ``min`` below the default ``min_short`` bring ``min_short`` down with it.

        Only a number does; anything else is left to the field's own validation.
        """
        if not isinstance(data, dict) or "min_short" in data:
            return data
        minimum = data.get("min")
        if isinstance(minimum, int | float) and minimum < DEFAULT_MIN_SHORT:
            return {**data, "min_short": minimum}
        return data

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min_short > self.min:
            raise ValueError("min_short must not be larger than min")
        return self


class Intro(Strict):
    """The silent intro before the song (``intro``, ADR-0020).

    When the first sung word comes earlier than the minimum, silence is added at the start,
    only as much as is missing, so the title and the singers' colours can be read.

    Attributes:
        solo: The minimum seconds from the start of the video to the first sung word of a song
            with one singer.
        group: The same for a song with more than one singer or with lines sung together.
            ``0`` for both turns the intro off.
    """

    solo: float = Field(default=8.0, ge=0)
    group: float = Field(default=9.0, ge=0)


class Ending(Strict):
    """The end of the song (``ending``).

    Attributes:
        end_screen: Show title and artist again after the last line.
        start_after: Seconds after the last line ends when the end screen starts.
        fade: The end screen fades out over this many seconds at the end.
    """

    end_screen: bool = True
    start_after: float = Field(default=2.0, ge=0)
    fade: float = Field(default=0.5, ge=0)


type PageTurn = Literal["page", "line"]
"""How a page gives way to the next (``page.turn``)."""


class Page(Strict):
    """Page mode (``page``).

    Attributes:
        min_lines: A page has at least this many lines where the song allows it.
        slot_per_row: Each slot is one row high and a line wrapped onto two rows takes two
            neighbouring slots, so a page holds at most ``slots`` rows. Needs ``mode: page`` and
            ``line_rows: 2``.
        turn: How a page gives way to the next: ``page`` turns the whole page when the next
            page's first line appears; ``line`` (ADR-0041) fills a slot with the next page's line
            as soon as the line in it has been sung, so the next page builds from the top while
            the old one is still sung. Needs ``mode: page``. The built-in looks use ``page``; the
            CD+G fallback sets ``line`` for a song that is late with whole-page turns.
    """

    min_lines: int = Field(default=1, ge=1)
    slot_per_row: bool = False
    turn: PageTurn = "page"


class Preview(Strict):
    """The preview of the next line in single-line looks (``preview``).

    Attributes:
        show: Show the next line below the line being sung, in its unsung colour. Needs
            ``mode: line`` and ``slots: 1``.
        scale: The size of the preview as a share of the size of the line it previews.
    """

    show: bool = False
    scale: float = Field(default=0.7, ge=0.4, le=0.9)


class Glow(Strict):
    """A glow around the sung text (``glow``, ADR-0032).

    Attributes:
        sung: The strength, 0 (off) to 1: a blurred copy of the sung text under the line.
        colour: The colour of the glow; the sung colour of the singer if left out.
    """

    sung: float = Field(default=0.0, ge=0, le=1)
    colour: Hex | None = None


class Pop(Strict):
    """The word being sung grows a little and settles back (``pop``, ADR-0032).

    Attributes:
        scale: How much larger the word gets (1 for none).
        time: Seconds from the start of the word until it is back to its size.
    """

    scale: float = Field(default=1.0, ge=1.0, le=MAX_POP_SCALE)
    time: float = Field(default=0.25, gt=0, le=1)


class Transition(Strict):
    """How lines come and go (``transition``, ADR-0032).

    Attributes:
        form: ``none``; ``fade`` (the line fades in and out); ``slide`` (it also moves in from
            below and out upwards a part of a slot height).
        time: Seconds a line takes to come in and to go, less where there is no room before its
            first syllable or after its last.
    """

    form: Literal["none", "fade", "slide"] = "none"
    time: float = Field(default=0.3, gt=0, le=1)


class Upcoming(Strict):
    """Lines shown before they are sung (``upcoming``, ADR-0032).

    Attributes:
        dim: How much they are dimmed, 0 (not at all) to 0.8; they are back to full when the
            first syllable starts.
    """

    dim: float = Field(default=0.0, ge=0, le=MAX_DIM)


class BackgroundMotion(Strict):
    """A slowly moving colour gradient instead of the plain background (``background_motion``).

    Attributes:
        colours: Two to four colours; none for the plain ``background``.
        speed: How fast the gradient turns (ffmpeg's ``gradients`` speed, 0 to 1).
    """

    colours: list[Hex] = Field(default_factory=list)
    speed: float = Field(default=0.01, gt=0, le=1)

    @field_validator("colours")
    @classmethod
    def _two_to_four(cls, value: list[str]) -> list[str]:
        low, high = BACKGROUND_COLOURS
        if value and not low <= len(value) <= high:
            raise ValueError(f"needs {low} to {high} colours, or none")
        return value


class Scroll(Strict):
    """The column of lyrics in scroll mode (``scroll``, ADR-0033).

    The line being sung stands still at ``current``; the column glides up when the next line is
    to take its place. Sung and upcoming lines are dimmed (``upcoming.dim`` and ``dim_sung``).

    Attributes:
        current: The height of the middle of the line being sung, as a share of the height of
            the safe area from its top.
        before: How many sung lines stay above it at most (0 to 2).
        after: How many upcoming lines are shown below it at most (1 to 4).
        glide: How long the column takes to move up to the next line, in seconds; less where
            the singing leaves no room for it.
        min_glide: The shortest a glide between two lines takes (0.1 to 1.0, not more than
            ``glide``); if left out, ``MIN_GLIDE`` or ``glide`` if that is shorter (see
            ``shortest_glide``). Where the silence between the lines is shorter, the glide starts
            during the end of the line that is finishing (ADR-0036).
        dim_sung: How much a sung line is dimmed, 0 (not at all) to 0.8; the value of
            ``upcoming.dim`` if left out.
    """

    current: float = Field(default=0.42, ge=0.2, le=0.8)
    before: int = Field(default=2, ge=0, le=MAX_BEFORE)
    after: int = Field(default=3, ge=1, le=MAX_AFTER)
    glide: float = Field(default=0.4, ge=0.2, le=1.0)
    min_glide: float | None = Field(default=None, ge=0.1, le=1.0)
    dim_sung: float | None = Field(default=None, ge=0, le=MAX_DIM)

    @field_validator("min_glide")
    @classmethod
    def _min_glide_within_glide(cls, value: float | None, info: ValidationInfo) -> float | None:
        if value is not None and value > info.data.get("glide", value):
            raise ValueError("min_glide must not be larger than glide")
        return value

    @property
    def shortest_glide(self) -> float:
        """The shortest a glide between two lines takes, in seconds.

        ``min_glide`` if set, else the smaller of ``MIN_GLIDE`` and ``glide``, so a profile with a
        ``glide`` below ``MIN_GLIDE`` keeps working (ADR-0036).
        """
        if self.min_glide is None:
            return min(MIN_GLIDE, self.glide)
        return self.min_glide


class CdgSingerColours(Strict):
    """Overrides of one singer's colours on CD+G; a colour left out is the video's, rounded."""

    unsung: CdgHex | None = None
    sung: CdgHex | None = None
    edge: CdgHex | None = None


class CdgColours(Strict):
    """Overrides of colours on CD+G (``cdg.colours``): the video's colour keys and ``background``.

    Colours are ``#rgb`` or ``#rrggbb``. A colour without an override is the video's colour
    rounded to the nearest 12-bit value.
    """

    background: CdgHex | None = None
    singer1: CdgSingerColours | None = None
    singer2: CdgSingerColours | None = None
    singer3: CdgSingerColours | None = None
    singer4: CdgSingerColours | None = None
    singer5: CdgSingerColours | None = None
    group: CdgSingerColours | None = None


class CdgLook(Strict):
    """How a look is simplified for CD+G (``cdg``, ADR-0029).

    The section is also the marker: a look without it, or with ``made_for_cdg: false``, is MP4
    only. On CD+G the shadow and the fade of the end screen are always dropped.

    Attributes:
        made_for_cdg: The look is made for CD+G and passes ``vocatron profiles check`` there.
        slots: How many lines are on screen at most (1 to 6); may be fewer than the video's.
        font_px: The line cell in pixels on the 192 px high safe area.
        min_font_px: The smallest line cell a line is shrunk to when a word does not fit.
        edge_px: The outline in pixels, 1 or 2 (a look without a visible edge gives the edge the
            background colour).
        wipe_columns: The pixels the wipe, a bar or a countdown moves at a time: 1, 2, 3 or 6.
        colours: Colour overrides.
    """

    made_for_cdg: bool = False
    slots: int = Field(default=2, ge=1, le=MAX_SLOTS)
    font_px: int = Field(default=24, ge=CDG_FONT_PX[0], le=CDG_FONT_PX[1])
    min_font_px: int = Field(default=18, ge=CDG_FONT_PX[0], le=CDG_FONT_PX[1])
    edge_px: Literal[1, 2] = 1
    wipe_columns: Literal[1, 2, 3, 6] = 3
    colours: CdgColours = Field(default_factory=CdgColours)

    @field_validator("min_font_px")
    @classmethod
    def _min_below_size(cls, value: int, info: ValidationInfo) -> int:
        if value > info.data.get("font_px", value):
            raise ValueError("min_font_px must not be larger than font_px")
        return value


class Profile(Strict):
    """A style profile.

    Attributes:
        name: The profile's name.
        description: One line about the look.
        mode: ``line``: slots are refilled line by line as they are sung; ``page``: a page of up
            to ``slots`` lines appears together and clears as a whole; ``scroll``: a column of
            lines that glides up, the line being sung at a fixed height (MP4 only, ADR-0033).
        slots: How many lines are on screen at most (1 to 6); not used in scroll mode.
        line_rows: How many rows a lyric line may be wrapped onto (1 or 2). A line wider than one
            row is shown as one block of up to this many rows that appear, are sung and leave
            together; with 1 it is split into lines that are shown one after the other. The rows
            share one slot, or take neighbouring slots with ``page.slot_per_row``.
        block: In line mode, how many neighbouring slots turn together (1 to 3); with 1 every line
            takes a slot of its own. With more the slots form blocks of that many, the lines are
            grouped in sung order and a block is replaced as a whole (ADR-0038).
        page: Page mode settings.
        preview: The preview of the next line.
        align: Horizontal alignment of the lines.
        position: Where the block of slots sits in the safe area.
        safe_area: The share of the frame that text stays inside (0.9 is the TV graphics-safe
            area).
        font: The font.
        background: The plain background colour.
        colours: The singers' colours.
        edge: The outline.
        shadow: The shadow.
        wipe: The wipe.
        lead_in: The lead-in times.
        clear: Hold and replace times.
        breaks: Gaps.
        countdown: The countdown.
        title: The title screen.
        intro: The silent intro before the song.
        ending: The end of the song.
        glow: A glow around the sung text (MP4 only, ADR-0032).
        pop: The word being sung grows a little (MP4 only).
        transition: Lines fade or slide in and out (MP4 only).
        upcoming: Lines shown before they are sung are dimmed (MP4 only).
        background_motion: A moving colour gradient as background (MP4 only).
        scroll: The column of lyrics in scroll mode (MP4 only).
        cdg: How the look is simplified for CD+G; without it the look is MP4 only. A look with
            one of the effects, or in scroll mode, has none.
    """

    name: str = Field(min_length=1)
    description: str = ""
    mode: Literal["line", "page", "scroll"] = "line"
    slots: int = Field(default=2, ge=1, le=MAX_SLOTS)
    line_rows: int = Field(default=1, ge=1, le=MAX_LINE_ROWS)
    block: int = Field(default=1, ge=1, le=MAX_BLOCK)
    page: Page = Field(default_factory=Page)
    preview: Preview = Field(default_factory=Preview)
    align: Literal["center", "left", "right"] = "center"
    position: Literal["top", "middle", "lower-third", "bottom"] = "lower-third"
    safe_area: float = Field(default=0.9, ge=0.5, le=1.0)
    font: Font = Field(default_factory=Font)
    background: Hex = "#000000"
    colours: Colours
    edge: Edge = Field(default_factory=Edge)
    shadow: Shadow = Field(default_factory=Shadow)
    wipe: Wipe = Field(default_factory=Wipe)
    lead_in: LeadIn = Field(default_factory=LeadIn)
    clear: Clear = Field(default_factory=Clear)
    breaks: Breaks = Field(default_factory=Breaks)
    countdown: Countdown = Field(default_factory=Countdown)
    title: Title = Field(default_factory=Title)
    intro: Intro = Field(default_factory=Intro)
    ending: Ending = Field(default_factory=Ending)
    glow: Glow = Field(default_factory=Glow)
    pop: Pop = Field(default_factory=Pop)
    transition: Transition = Field(default_factory=Transition)
    upcoming: Upcoming = Field(default_factory=Upcoming)
    background_motion: BackgroundMotion = Field(default_factory=BackgroundMotion)
    scroll: Scroll = Field(default_factory=Scroll)
    cdg: CdgLook | None = None

    @field_validator("block")
    @classmethod
    def _block_in_line_mode(cls, value: int, info: ValidationInfo) -> int:
        if value > 1 and info.data.get("mode", "line") != "line":  # refused at the key ``block``
            raise ValueError("block needs mode: line")
        return value

    @model_validator(mode="after")
    def _mode_settings_fit(self) -> Self:
        if problems := slot_conflicts(self, self.slots, "slots"):
            raise _error_at(("slots",), problems[0], self.slots)
        if self.page.slot_per_row and (self.mode != "page" or self.line_rows != MAX_LINE_ROWS):
            raise ValueError("page.slot_per_row needs mode: page and line_rows: 2")
        if self.page.turn == "line" and self.mode != "page":
            raise ValueError("page.turn: line needs mode: page")
        return self

    @model_validator(mode="after")
    def _scroll_settings_fit(self) -> Self:
        if self.mode != "scroll":
            if self.scroll != Scroll():
                raise ValueError("the scroll section needs mode: scroll")
            return self
        if self.page != Page():
            raise ValueError("the page section does not go with mode: scroll")
        if self.transition.form != "none":
            raise ValueError("transition does not go with mode: scroll (the column glides)")
        return self

    @property
    def dim_sung(self) -> float:
        """How much a sung line is dimmed: ``scroll.dim_sung``, else ``upcoming.dim``."""
        dim = self.scroll.dim_sung
        return self.upcoming.dim if dim is None else dim

    def padding(self, size: float) -> float:
        """Return the room that outline and shadow take on each side of text at ``size``."""
        return (self.edge.width + self.shadow.offset) * size

    def singer_colours(self, key: str) -> SingerColours:
        """Return the colours of ``1`` to ``5`` or ``group``."""
        colours = self.colours
        return {
            "1": colours.singer1,
            "2": colours.singer2,
            "3": colours.singer3,
            "4": colours.singer4,
            "5": colours.singer5,
            "group": colours.group,
        }[key]


def slot_conflicts(profile: Profile, slots: int, key: str) -> list[str]:
    """Return how ``slots`` (the value of ``key``) breaks the mode settings of ``profile``.

    The one rule for the video's ``slots`` and for ``cdg.slots``: a page needs room for its
    minimum, a preview needs a single line, two rows over two slots need two slots, and blocks
    need a multiple of their size with at least two blocks (ADR-0038).
    """
    problems: list[str] = []
    if profile.page.min_lines > slots:
        problems.append(f"page.min_lines must not be larger than {key}")
    if profile.preview.show and (profile.mode != "line" or slots != 1):
        problems.append(f"preview.show needs mode: line and {key}: 1")
    if profile.page.slot_per_row and slots < MAX_LINE_ROWS:
        problems.append(f"page.slot_per_row needs {key} of at least {MAX_LINE_ROWS}")
    if profile.block > 1 and (slots % profile.block or slots < 2 * profile.block):
        problems.append(
            f"{key} must be a multiple of block ({profile.block}) with at least two blocks"
        )
    return problems


def _error_at(loc: Location, message: str, value: object) -> ValidationError:
    """Return the validation error ``message`` located at the key ``loc``, not at the profile.

    A model validator's own errors are located at the profile; this one names the key, as the
    issues of ``cdg_issues`` do (``slots``: the rules of ``slot_conflicts``).
    """
    error = ValueError(message)
    return ValidationError.from_exception_data(
        "Profile",
        [{"type": "value_error", "loc": loc, "input": value, "ctx": {"error": error}}],
    )


CDG_SLOTS_HINT = "set cdg.slots to match, or cdg.made_for_cdg: false for a look that is MP4 only"
"""What to do when ``cdg.slots`` breaks a rule, for instance after an override of the video's."""


def made_for_cdg(profile: Profile) -> bool:
    """Tell whether the look carries a ``cdg`` section with the marker (ADR-0029)."""
    return profile.cdg is not None and profile.cdg.made_for_cdg


def cdg_issues(profile: Profile) -> list[Issue]:
    """Return how the ``cdg`` section breaks a rule of the profile, located at ``cdg.slots``.

    A section without the marker is not used, so it breaks nothing.
    """
    if profile.cdg is None or not profile.cdg.made_for_cdg:
        return []
    return [
        Issue(("cdg", "slots"), f"{message} ({CDG_SLOTS_HINT})")
        for message in slot_conflicts(profile, profile.cdg.slots, "cdg.slots")
    ]


def effects_used(profile: Profile) -> list[str]:
    """Return the effect sections (``EFFECT_KEYS``) of ``profile`` that change how it looks."""
    used = {
        "glow": profile.glow.sung > 0,
        "pop": profile.pop.scale > 1,
        "transition": profile.transition.form != "none",
        "upcoming": profile.upcoming.dim > 0,
        "background_motion": bool(profile.background_motion.colours),
    }
    return [key for key in EFFECT_KEYS if used[key]]


def digest_json(profile: Profile, *, without: frozenset[str] = frozenset()) -> str:
    """Return the JSON of ``profile`` that the digest of a picture is made from.

    The effect sections that the look does not use, and the scroll section of a look that does not
    scroll, are left out, so that a look made before they existed keeps its digest and its picture
    (ADR-0032, ADR-0033), and so does a look that turns line by line (``block: 1``, ADR-0038).

    Args:
        profile: The profile.
        without: More keys to leave out (the ``cdg`` section of a video picture).
    """
    unused = set(EFFECT_KEYS) - set(effects_used(profile))
    if profile.mode != "scroll":
        unused.add("scroll")  # a section a look does not use must not change its picture
    if profile.block == 1:
        unused.add("block")  # the key of ADR-0038: a look without blocks keeps its digest
    return profile.model_dump_json(exclude={*without, *unused})


def effect_issues(profile: Profile) -> list[Issue]:
    """Return the issues of a look with effects or scrolling that has a ``cdg`` section.

    CD+G cannot draw glow, growing words, transitions, dimmed lines, a moving background or text
    that glides, so such a look is for the video only and leaves the section out (ADR-0032,
    ADR-0033). The issues are located at the section.
    """
    used = effects_used(profile)
    if profile.cdg is None:
        return []
    found: list[Issue] = []
    if used:
        found.append(
            Issue(
                ("cdg",),
                f"cannot be used with the effects {', '.join(used)}, which CD+G cannot draw "
                "(leave the cdg section out: the look is for the video only)",
            )
        )
    if profile.mode == "scroll":
        found.append(
            Issue(
                ("cdg",),
                "cannot be used with mode: scroll, which CD+G cannot draw "
                "(leave the cdg section out: the look is for the video only)",
            )
        )
    return found


class ProfileError(Exception):
    """A profile does not load; ``messages`` are ready to print, one per problem."""

    def __init__(self, messages: list[str]) -> None:
        """Create the error from its printable messages."""
        super().__init__("\n".join(messages))
        self.messages = messages


def _merge(base: object, overrides: Mapping[str, JsonValue]) -> object:
    """Return ``base`` (a parsed mapping) with ``overrides`` merged in, key by key."""
    if not isinstance(base, dict):
        return dict(overrides)
    merged: dict[str, object] = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        merged[key] = _merge(current, value) if isinstance(value, dict) else value
    return merged


def _paths(overrides: Mapping[str, JsonValue], prefix: Location = ()) -> list[Location]:
    """Return the location of every value in ``overrides``."""
    found: list[Location] = []
    for key, value in overrides.items():
        if isinstance(value, dict):
            found += _paths(value, (*prefix, key))
        else:
            found.append((*prefix, key))
    return found


def override_keys(overrides: Mapping[str, JsonValue]) -> list[str]:
    """Return the keys that ``overrides`` replaces, each as a dotted path (``font.size``)."""
    return [".".join(map(str, path)) for path in _paths(overrides)]


def _describe(
    file: str, errors: list[Issue], positions: Positions, overridden: list[Location]
) -> list[str]:
    """Format issues; one under an overridden value names the override instead of the file."""
    messages: list[str] = []
    for issue in errors:
        if any(issue.loc[: len(path)] == path for path in overridden):
            where = ".".join(str(part) for part in issue.loc)
            messages.append(f"profile_overrides.{where}: {issue.message}")
        else:
            messages.extend(describe_all(file, [issue], positions))
    return messages


def describe_issues(
    file: str, issues: list[Issue], positions: Positions, overrides: Mapping[str, JsonValue]
) -> list[str]:
    """Format issues of a profile as ``file:line:column: key: message``.

    An issue under a value that ``overrides`` replaced names the override instead of the file.
    """
    return _describe(file, issues, positions, _paths(overrides))


def parse_profile(
    file: str, text: str, overrides: Mapping[str, JsonValue] | None = None
) -> Profile:
    """Read a profile from YAML text and apply the overrides.

    Args:
        file: The name of the file, for the error messages.
        text: The YAML text.
        overrides: Values that replace those of the file, by the same keys (nested).

    Raises:
        ProfileError: If the text is not valid YAML or does not follow the schema.
    """
    try:
        data, positions = parse_yaml(file, text)
    except YamlSyntaxError as error:
        raise ProfileError([str(error)]) from error
    changes = dict(overrides or {})
    try:
        profile = Profile.model_validate(_merge(data, changes))
    except ValidationError as error:
        issues = [Issue(tuple(e["loc"]), e["msg"]) for e in error.errors()]
        raise ProfileError(describe_issues(file, issues, positions, changes)) from error
    if found := [*cdg_issues(profile), *effect_issues(profile)]:
        raise ProfileError(describe_issues(file, found, positions, changes))
    return profile


PROFILE_SUFFIXES = (".yaml", ".yml")


def is_name(spec: str) -> bool:
    """Tell whether ``spec`` is a profile name (ADR-0019); anything else is the path of a file.

    A name has no path separator and does not end in ``.yaml`` or ``.yml``. A name is looked up
    among the built-in profiles and the ones in ``profiles_folder``.
    """
    return not ({"/", "\\"} & set(spec)) and not spec.lower().endswith(PROFILE_SUFFIXES)


def background_extremes(profile: Profile) -> list[str]:
    """Return what the text has to stand out against.

    That is the plain background, or the darkest and the lightest colour of a moving one
    (ADR-0032).
    """
    colours = profile.background_motion.colours or [profile.background]
    return list(dict.fromkeys((min(colours, key=luminance), max(colours, key=luminance))))


def _worst_contrast(fill: str, backgrounds: list[str]) -> float:
    """Return the lowest contrast ratio of ``fill`` against any of ``backgrounds``."""
    return min(contrast_ratio(fill, background) for background in backgrounds)


def _dim_issues(profile: Profile, backgrounds: list[str]) -> list[Issue]:
    """Judge the unsung text at the opacity of a dimmed upcoming line (rule 18, ADR-0032)."""
    if profile.upcoming.dim <= 0:
        return []
    issues: list[Issue] = []
    for key in (*SINGER_KEYS, "group"):
        unsung: str = getattr(profile.colours, key).unsung
        ratio = min(
            contrast_ratio(blend(unsung, background, 1 - profile.upcoming.dim), background)
            for background in backgrounds
        )
        if ratio < MIN_TEXT_CONTRAST:
            issues.append(
                Issue(("upcoming", "dim"), f"dims the unsung text of {key} to contrast {ratio:.1f}")
            )
    return issues


def profile_issues(profile: Profile) -> list[Issue]:
    """Judge the colours of a profile by the contrast rules (rule 18); empty when it passes.

    Each issue is located at the colour that is the problem, so a file can point at its line.
    Against a moving background the text must stand out against its darkest and its lightest
    colour, and the unsung text of a dimmed upcoming line at its opacity (ADR-0032).
    """
    issues: list[Issue] = []
    backgrounds = background_extremes(profile)
    for key in (*SINGER_KEYS, "group"):
        colours: SingerColours = getattr(profile.colours, key)
        for part in ("unsung", "sung"):
            fill: str = getattr(colours, part)
            ratio = _worst_contrast(fill, backgrounds)
            where: Location = ("colours", key, part)
            if ratio < MIN_TEXT_CONTRAST:
                issues.append(Issue(where, f"has contrast {ratio:.1f} with the background"))
            edge = contrast_ratio(fill, colours.edge)
            if edge < MIN_TEXT_CONTRAST:
                issues.append(Issue(where, f"has contrast {edge:.1f} with its edge"))
        if distance(colours.unsung, colours.sung) < MIN_FILL_DISTANCE:
            issues.append(
                Issue(("colours", key), "sung and unsung colours are too alike to tell apart")
            )
        wipe = contrast_ratio(colours.unsung, colours.sung)
        if wipe < MIN_WIPE_CONTRAST:
            issues.append(
                Issue(
                    ("colours", key, "sung"),
                    f"has contrast {wipe:.2f} with the unsung colour, too little to see the wipe",
                )
            )
    return [*issues, *_dim_issues(profile, backgrounds)]


def _problem(issue: Issue) -> str:
    """Write an issue of the colours as one line: ``singer1.sung has contrast ...``."""
    if issue.loc[0] == "upcoming":
        return f"upcoming.dim {issue.message}"
    key, *part = issue.loc[1:]  # below ``colours``
    return f"{key}.{part[0]} {issue.message}" if part else f"{key}: {issue.message}"


def profile_problems(profile: Profile) -> list[str]:
    """Return the messages of ``profile_issues`` (rule 18); empty when the colours pass."""
    return [_problem(issue) for issue in profile_issues(profile)]
