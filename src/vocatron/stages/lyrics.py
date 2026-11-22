"""The ``lyrics`` stage: a sidecar next to the audio, else a lookup; cleaned, checked, written down.

A ``Song.lrc`` or ``Song.txt`` next to the audio wins (``.lrc`` first). Without one, LRCLIB is asked
and the result is written next to the audio, the only write into the input folder (ADR-0006). The
stage cleans the lyrics, detects the language and decides the status (ADR-0008): ``missing``
fails the song, ``review`` does not stop it. A file that differs from what Vocatron wrote counts
as approved. The file Vocatron writes carries a mark (``vocatron.core.lyrics.origin``), so that it
stays Vocatron's in a work folder that does not remember the run that wrote it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import override

from vocatron.core.alignment.rails import order_notes
from vocatron.core.errors import StageError
from vocatron.core.glyphs import UndrawableLetter
from vocatron.core.languages import is_supported, unsupported_message
from vocatron.core.lyrics.clean import Cleaned, clean
from vocatron.core.lyrics.document import (
    Document,
    FormatError,
    Kind,
    Line,
    format_time,
    has_singer_marks,
    parse_length,
    parse_numbered,
    resolve_singers,
)
from vocatron.core.lyrics.file import LyricLine, LyricsFile, approved_copy
from vocatron.core.lyrics.match import Match, match_record
from vocatron.core.lyrics.origin import write_marked, written_by_vocatron
from vocatron.core.lyrics.verdict import (
    Facts,
    Previous,
    approval,
    decide,
    is_duet,
    lrc_fits,
)
from vocatron.core.lyrics.versions import Candidate, Choice, choose, record_text
from vocatron.core.lyrics.voices import same_time, voices_of
from vocatron.core.song import SongInfo
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.engines.protocols import LyricsLookupError
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.stage import Engines, Song, StageContext, TypedStage

LYRICS_STAGE = "lyrics"
SIDECAR = "sidecar"  # the name of the lyrics file among the inputs of the fingerprint
SONG_FILE = "song.json"
LYRICS_FILE = "lyrics.json"
SUFFIXES: tuple[Kind, ...] = ("lrc", "txt")  # the order of preference


@dataclass(frozen=True)
class Found:
    """The lyrics file next to the audio.

    Attributes:
        path: Where it lies.
        kind: ``lrc`` or ``txt``.
        text: Its content.
    """

    path: Path
    kind: Kind
    text: str


@dataclass(frozen=True)
class Material:
    """Lyrics as read from a file or found online, before cleaning and checking.

    Attributes:
        document: The parsed lyrics.
        rows: The row of each line of ``document`` in ``original``.
        original: Their text before cleaning.
        found: The file they came from; ``None`` for lyrics that are still to be written.
        lookup: How the lookup went; ``None`` for a file.
    """

    document: Document
    rows: tuple[int, ...]
    original: str
    found: Found | None
    lookup: Choice | None


def sidecar_path(song: Song, kind: Kind) -> Path:
    """Return where the lyrics file of ``kind`` lies: next to the audio, same name."""
    return song.source.with_suffix(f".{kind}")


def find_sidecar(song: Song, ctx: StageContext) -> Found | None:
    """Return the lyrics file next to the audio (``.lrc`` before ``.txt``), if there is one.

    Raises:
        StageError: If the file cannot be read as UTF-8 text.
    """
    for kind in SUFFIXES:
        path = sidecar_path(song, kind)
        try:
            text = ctx.engines.store.read_text(path)
        except (OSError, UnicodeDecodeError) as error:
            raise StageError("unreadable-lyrics", f"cannot read {path.name}: {error}") from error
        if text is not None:
            return Found(path, kind, text)
    return None


class LyricsStage(TypedStage[LyricsSettings]):
    """Finds, cleans and checks the lyrics of a song."""

    name = LYRICS_STAGE
    # 3: symbols the font lacks are dropped, a letter it lacks fails (ADR-0046, lyrics.json v3)
    # 4: the voice of every line: `{&}` and the same .lrc time (ADR-0052, lyrics.json v4)
    # 5: whether a line has a singer mark of its own (ADR-0054, lyrics.json v5)
    # 6: only a mark at the start of a line counts as its own (ADR-0054)
    version = 6
    inputs = (SONG_FILE,)
    output = LYRICS_FILE
    output_model = LyricsFile

    def settings_from(self, config: Config) -> LyricsSettings:
        """Return the ``lyrics`` section."""
        return config.lyrics

    @override
    def external_inputs(self, ctx: StageContext, config: Config) -> dict[str, str]:
        """Return the hash of the lyrics file next to the audio, if there is one."""
        del config
        for kind in SUFFIXES:
            digest = ctx.engines.store.sha256(sidecar_path(ctx.song, kind))
            if digest is not None:
                return {SIDECAR: digest}
        return {}

    def run(
        self, ctx: StageContext, settings: LyricsSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Write ``lyrics.json`` (and the lyrics file next to the audio after a lookup).

        Raises:
            StageError: If there are no lyrics, the file is invalid, a letter is not in the
                bundled font, or the language is not supported.
        """
        info = _song_info(ctx)
        previous = load_lyrics(ctx.song, ctx.engines)
        found = find_sidecar(ctx.song, ctx)
        material = (
            _from_file(found) if found is not None else _from_lookup(ctx, info, settings.lookup)
        )
        try:
            cleaned = clean(
                material.document.lines,
                material.rows,
                ctx.engines.resources.drawable_characters(),
            )
        except UndrawableLetter as error:
            raise StageError("undrawable-character", str(error)) from error
        if not cleaned.lines:
            raise StageError("no-lyrics", f"no lyrics found: {_hint(ctx.song)}")
        if found is None:
            found, cleaned = _write_sidecar(ctx, info, material, cleaned)
        for note in order_notes([line.time for line in cleaned.lines]):
            ctx.log(f"lyrics: warning: {note}")
        for index, later in enumerate(same_time([line.time for line in cleaned.lines])):
            if later:
                ctx.log(f"lyrics: line {index + 1} has the time of line {index}: second voice")
        language = settings.language or _language(ctx, cleaned)
        run = Run(ctx, settings, info, previous, fingerprint)
        return _assemble(run, material, found, cleaned, language)


def _hint(song: Song) -> str:
    """Say what the fan can do when there are no lyrics."""
    return f"put {song.source.stem}.txt or {song.source.stem}.lrc next to {song.source.name}"


def _song_info(ctx: StageContext) -> SongInfo:
    """Return the ``song.json`` of the probe stage.

    Raises:
        StageError: If it is missing or invalid.
    """
    info = _read_model(ctx.song, ctx.engines, SONG_FILE, SongInfo)
    if info is None:
        raise StageError("missing-input", f"{SONG_FILE} is missing or invalid")
    return info


def _read_model[M: StageFile](song: Song, engines: Engines, name: str, model: type[M]) -> M | None:
    """Return a stage file of the song, or ``None`` if it is missing or invalid."""
    try:
        text = engines.store.read_text(song.work_dir / name)
        return None if text is None else model.model_validate_json(text)
    except ValueError:
        return None


def _from_file(found: Found) -> Material:
    """Read the lyrics from the file next to the audio.

    Raises:
        StageError: If the file does not follow the format.
    """
    try:
        document, rows = parse_numbered(found.text, found.kind)
    except FormatError as error:
        raise StageError("invalid-lyrics", f"{found.path.name}: {error}") from error
    return Material(document, rows, found.text, found, None)


def _from_lookup(ctx: StageContext, info: SongInfo, lookup: bool) -> Material:
    """Ask the lyrics source; keep the records that match artist and title, choose a version."""
    if not lookup:
        raise StageError("no-lyrics", f"no lyrics found and lookup is off: {_hint(ctx.song)}")
    try:
        records = ctx.engines.lyrics.find(info.artist, info.title, info.duration)
    except LyricsLookupError as error:
        ctx.log(f"lyrics: lookup failed: {error}")
        raise StageError("no-lyrics", f"lookup failed, try again later: {error}") from error
    matching = [r for r in records if _match(info, r) != "none"]
    ctx.log(f"lyrics: {len(records)} records found, {len(matching)} match")
    choice = choose(matching, info.duration)
    if choice is None:
        raise StageError("no-lyrics", f"no lyrics found: {_hint(ctx.song)}")
    synced = choice.synced
    text, kind = (synced.synced, "lrc") if synced and synced.synced else record_text(choice.chosen)
    document, rows = parse_numbered(text, kind, header=False)  # a record is not a file of ours
    return Material(document, rows, text, None, choice)


def _match(info: SongInfo, record: Candidate) -> Match:
    """Compare a record with the song."""
    return match_record(info.artist, info.title, record.artist, record.title)


def _write_sidecar(
    ctx: StageContext, info: SongInfo, material: Material, cleaned: Cleaned
) -> tuple[Found, Cleaned]:
    """Write the cleaned lyrics next to the audio: ``.lrc`` when synced lyrics fit, else ``.txt``.

    This is the only write into the input folder; the file carries Vocatron's mark.

    Returns:
        The file written, and the cleaned lyrics as written (a ``.txt`` has no line times).
    """
    kind: Kind = "lrc" if material.lookup is not None and material.lookup.synced else "txt"
    lines = cleaned.lines if kind == "lrc" else _untimed(cleaned.lines)
    tags = _lrc_tags(info) if kind == "lrc" else ()
    document = Document(kind=kind, tags=tags, lines=lines)
    path = sidecar_path(ctx.song, kind)
    text = write_marked(document)
    ctx.engines.store.write_text(path, text)
    ctx.log(f"lyrics: wrote {path.name}")
    return Found(path, kind, text), cleaned.model_copy(update={"lines": lines})


def _lrc_tags(info: SongInfo) -> tuple[tuple[str, str], ...]:
    """Return the ID tags of an ``.lrc`` that Vocatron writes: artist, title and length."""
    tags = [("ar", info.artist)] if info.artist else []
    tags.append(("ti", info.title))
    if info.duration is not None:
        tags.append(("length", format_time(info.duration)[:-3]))
    return tuple(tags)


def _untimed(lines: tuple[Line, ...]) -> tuple[Line, ...]:
    """Return the lines without times (a plain ``.txt`` has none)."""
    return tuple(line.model_copy(update={"time": None}) for line in lines)


def _language(ctx: StageContext, cleaned: Cleaned) -> str:
    """Detect the language of the lyrics and require it to be supported.

    Not called when ``lyrics.language`` (or ``--language``) names the language.

    Raises:
        StageError: If the language cannot be told or is not supported.
    """
    detected = ctx.engines.language.detect("\n".join(line.text for line in cleaned.lines))
    if detected is None:
        raise StageError("unknown-language", "cannot tell the language of the lyrics")
    if not is_supported(detected.code):
        raise StageError("unsupported-language", unsupported_message(detected))
    ctx.log(f"lyrics: language {detected.name}")
    return detected.code


@dataclass(frozen=True)
class Run:
    """What one run of the stage works with.

    Attributes:
        ctx: The context of the song.
        settings: The settings of the stage.
        info: Artist, title and duration of the song.
        previous: The lyrics file of an earlier run, if there is a valid one.
        fingerprint: The fingerprint of this run, without the lyrics file.
    """

    ctx: StageContext
    settings: LyricsSettings
    info: SongInfo
    previous: LyricsFile | None
    fingerprint: Fingerprint


def _facts(
    run: Run, material: Material, cleaned: Cleaned, found: Found, keep: bool, forgotten: bool
) -> Facts:
    """Collect what the status rules need.

    Found lyrics bring the facts of their lookup; the file Vocatron wrote earlier brings them from
    the earlier run (the file cannot tell). A file Vocatron wrote in a run that is ``forgotten``
    (the work folder remembers no run or another file) is found lyrics whose lookup is not known.
    A fan's own file is trusted.
    """
    duet = is_duet(run.settings.duet_pattern, run.ctx.song.source.stem, run.info.title)
    base = Facts(
        source="sidecar",
        lines=len(cleaned.lines),
        removals=cleaned.removals,
        duet=duet,
        marked=has_singer_marks(cleaned.lines),
    )
    if material.lookup is not None:
        choice = material.lookup
        return base.model_copy(
            update={
                "source": "lookup",
                "match": _match(run.info, choice.chosen),
                "agreeing": choice.agreeing,
                "lrc_fits": True if choice.synced is not None else None,
            }
        )
    if keep and run.previous is not None:
        earlier = run.previous
        return base.model_copy(
            update={
                "source": "lookup",
                "match": earlier.match,
                "agreeing": earlier.versions_agreeing,
                "removals": tuple(earlier.removed),
                "lrc_fits": earlier.lrc_fits,
            }
        )
    if forgotten:
        base = base.model_copy(update={"source": "lookup"})
    if found.kind == "lrc":
        times = [line.time for line in material.document.lines if line.time is not None]
        fits = lrc_fits(max(times, default=None), _length(material.document), run.info.duration)
        return base.model_copy(update={"lrc_fits": fits})
    return base


def _considered(material: Material, carried: LyricsFile | None) -> int:
    """Return how many records the lookup compared (from the earlier run for a written file)."""
    if material.lookup is not None:
        return material.lookup.considered
    return carried.versions_considered if carried is not None else 0


def _length(document: Document) -> float | None:
    """Return the ``[length:]`` tag of an ``.lrc`` in seconds, if it has one."""
    for key, value in document.tags:
        if key.lower() == "length":
            return parse_length(value)
    return None


def _assemble(
    run: Run, material: Material, found: Found, cleaned: Cleaned, language: str
) -> LyricsFile:
    """Check the lyrics, decide their status and build the stage file."""
    digest = run.ctx.engines.store.sha256(found.path) or ""
    previous = run.previous
    fresh = material.found is None  # looked up in this run
    known = previous is not None and digest in {previous.sidecar_hash, previous.written_hash}
    forgotten = (
        not fresh and not known and written_by_vocatron(found.text, found.kind, digest)
    )  # Vocatron wrote it in a run this work folder does not remember (or knows another file)
    remembered = (
        Previous(
            sidecar_hash=previous.sidecar_hash,
            written_hash=previous.written_hash,
            approved=previous.approved,
        )
        if previous is not None and not fresh and not forgotten
        else None
    )
    decision = approval(digest, remembered)
    facts = _facts(run, material, cleaned, found, decision.keep_findings, forgotten)
    verdict = decide(facts)
    carried = previous if decision.keep_findings else None
    findings = list(verdict.reasons)
    reasons = [] if decision.approved else findings
    singers = resolve_singers(cleaned.lines)
    voices = voices_of(cleaned.lines)
    return LyricsFile(
        fingerprint=run.fingerprint.model_copy(
            update={"inputs": {**run.fingerprint.inputs, SIDECAR: digest}}
        ),
        reasons=reasons,
        source=facts.source,
        sidecar=found.path.name,
        sidecar_hash=digest,
        written_hash=digest
        if fresh or forgotten
        else (previous.written_hash if previous else None),
        original=carried.original if carried else material.original,
        lines=[
            LyricLine(
                text=line.text,
                singers=who.singers,
                turns=list(who.turns),
                voice=voice,
                own_mark=bool(line.marks) and line.marks[0].word == 0,
                time=line.time,
            )
            for line, who, voice in zip(cleaned.lines, singers, voices, strict=True)
        ],
        singers=material.document.singers,
        duet=facts.duet,
        language=language,
        match=facts.match,
        lrc_fits=facts.lrc_fits,
        versions_considered=_considered(material, carried),
        versions_agreeing=facts.agreeing,
        removed=list(facts.removals),
        findings=findings,
        approved=decision.approved,
        status="review" if reasons else "ok",
    )


def load_lyrics(song: Song, engines: Engines) -> LyricsFile | None:
    """Return the ``lyrics.json`` of a song, or ``None`` if it is missing or invalid."""
    return _read_model(song, engines, LYRICS_FILE, LyricsFile)


def approve(song: Song, engines: Engines) -> str | None:
    """Record the lyrics file next to the audio as approved, as it is now.

    Args:
        song: The song.
        engines: The engines (file store).

    Returns:
        ``None`` when the lyrics are approved, otherwise why they cannot be.
    """
    file = load_lyrics(song, engines)
    if file is None:
        return "there is no lyrics.json yet; run 'vocatron lyrics' on the song first"
    digest = engines.store.sha256(song.source.with_name(file.sidecar))
    if digest is None:
        return f"{file.sidecar} is not next to the song any more"
    if digest != file.sidecar_hash:
        return (
            f"{file.sidecar} changed since the last run; run 'vocatron lyrics' on the song: "
            "an edited file counts as approved"
        )
    engines.store.write_text(
        song.work_dir / LYRICS_FILE, approved_copy(file).model_dump_json(indent=2) + "\n"
    )
    return None
