"""The ``cdg`` stage: the MP3 and the CD+G file of a song (ADR-0023, ADR-0024, ADR-0029, ADR-0030).

It runs after ``render`` and only when ``cdg`` is in the config's ``outputs``; otherwise it writes
``cdg.json`` with no files and does nothing else. It lays the song out again for the 300 by 216
CD+G screen with the CD+G profile of the look (``vocatron.core.cdg.look``), writes the packets of
the scene as ``Artist - Title.cdg`` (``vocatron.core.cdg.fit`` falls back in fixed steps when a
song does not keep the timing) and encodes the karaoke stem to ``Artist - Title.mp3`` with the
silent intro in front. A song that is not in time after the last fallback step is written all the
same and needs review: ``cdg.json`` gets the reason "CD+G not in time" (ADR-0041). A look that is
not made for CD+G fails here, for each song, with
``cdg-not-made-for-cdg``; the video is made before. With ``cdg_zip`` the pair is packed into
``Artist - Title.zip`` and not written loose. Turning CD+G on or off never renders the MP4 again,
and a missing product runs the stage again.
"""

import time
from pathlib import Path
from typing import override

from vocatron.core.cdg.file import CdgFile, CdgValues
from vocatron.core.cdg.fit import Fit, fit_stream
from vocatron.core.cdg.look import cdg_section
from vocatron.core.cdg.pack import ZIP_TIME, pair_names, zip_name
from vocatron.core.cdg.palette import hex_of
from vocatron.core.errors import StageError
from vocatron.core.layout.rules import scene_findings
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.profiles.model import Profile, made_for_cdg
from vocatron.core.separation.file import stem_path
from vocatron.core.song import SongInfo, media_tags
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.engines.protocols import Mp3Request, PackMember, PackRequest
from vocatron.stages.config import Config
from vocatron.stages.layout import LayoutStage, ProfileSettings, prepare_layout, profile_inputs
from vocatron.stages.render import refuse_collisions
from vocatron.stages.stage import StageContext, TypedStage, read_input
from vocatron.stages.tempo import TEMPO_FILE

CDG_STAGE = "cdg"
CDG_FILE = "cdg.json"


class CdgSettings(ProfileSettings):
    """What the CD+G output depends on.

    Attributes:
        enabled: ``cdg`` is in the config's ``outputs``. When it is not, the profile does not
            count, so changing it re-runs nothing.
        layout_version: ``LayoutStage.version`` while CD+G is on (0 otherwise): the stage lays
            the song out with the same code, so a change of the layout that bumps that version
            makes the CD+G files again too.
        zipped: Pack the pair into a zip (``cdg_zip``, ADR-0030); only while CD+G is on.
    """

    enabled: bool
    layout_version: int = 0
    zipped: bool = False


class CdgStage(TypedStage[CdgSettings]):
    """Writes the CD+G file and the MP3 of the song."""

    name = CDG_STAGE
    # 2: artist, title, genre and comment ID3 tags in the MP3 (ADR-0031); 3: the look's cdg section,
    # the fallback steps and the optional zip (cdg.json v2, ADR-0029, ADR-0030); 4: the timer of a
    # break screen is drawn, the parts of a split line read top to bottom; 5: Vocatron writes the
    # ID3 tag of the MP3 itself, with the standard comment frame (ADR-0035); 6: CD+G clears a tile
    # before it draws new text there, pages may turn line by line, a line is judged on the frame
    # it is shown in, and a song that is not in time needs review (ADR-0041); 7: symbols the font
    # cannot draw are dropped from title, artist and singer names (ADR-0046); 8: the MP3 gets
    # Duet to Quintet in its TAG frame (ADR-0047); 9: the start screen with the wordmark in pixel
    # letters, in its own palette that the song's palette replaces when it ends (ADR-0056)
    version = 9
    inputs = ("syllables.json", "lyrics.json", "song.json", TEMPO_FILE, stem_path("karaoke"))
    output = CDG_FILE
    output_model = CdgFile

    def settings_from(self, config: Config) -> CdgSettings:
        """Return whether CD+G is on and, if it is, the profile with its overrides."""
        enabled = "cdg" in config.outputs
        return CdgSettings(
            enabled=enabled,
            layout_version=LayoutStage.version if enabled else 0,
            profile=config.profile if enabled else "",
            overrides=config.profile_overrides if enabled else {},
            folder=config.profiles_folder if enabled else None,
            zipped=enabled and config.cdg_zip,
        )

    @override
    def external_inputs(self, ctx: StageContext, config: Config) -> dict[str, str]:
        """Return the hash of the profile's text, when CD+G is on."""
        return profile_inputs(ctx, config) if "cdg" in config.outputs else {}

    @override
    def products(self, ctx: StageContext, stored: StageFile) -> tuple[Path, ...]:
        """Return the products in the output folder that ``cdg.json`` lists: the pair or the zip."""
        if not isinstance(stored, CdgFile):
            return ()
        return tuple(ctx.song.output_dir / name for name in stored.files)

    def run(self, ctx: StageContext, settings: CdgSettings, fingerprint: Fingerprint) -> StageFile:
        """Write the CD+G file and the MP3 (or the zip of both), and ``cdg.json``.

        Raises:
            StageError: ``output-collision`` if an output file would replace the song or its
                lyrics file, ``cdg-not-made-for-cdg`` if the look has no ``cdg`` section with
                the marker, ``cdg-palette`` if the look needs more than 16 colours,
                ``missing-input``, or the encoder's errors (``missing-tool``, ``render-failed``,
                ``render-timeout``).
        """
        if not settings.enabled:
            return CdgFile(fingerprint=fingerprint, enabled=False)
        started = time.monotonic()
        song, engines = ctx.song, ctx.engines
        mp3_name, cdg_name = pair_names(song.name)
        names = [zip_name(song.name)] if settings.zipped else [mp3_name, cdg_name]
        refuse_collisions(ctx, names)
        prepared = prepare_layout(ctx, settings)
        profile = prepared.profile
        if not made_for_cdg(profile):
            raise StageError("cdg-not-made-for-cdg", _not_made_for_cdg(profile))
        fit = fit_stream(
            prepared.phrases, prepared.text, profile, engines.measurer, engines.rasteriser
        )
        _log_fit(ctx, fit)
        written = fit.written
        if settings.zipped:
            mp3_target = song.work_dir / mp3_name  # the zip holds it; no loose copy
        else:
            mp3_target = song.output_dir / mp3_name
            engines.store.write_bytes(song.output_dir / cdg_name, written.stream)
        engines.mp3.encode_mp3(
            Mp3Request(
                source=song.work_dir / stem_path("karaoke"),
                target=mp3_target,
                lead=fit.scene.lead,
                duration=fit.scene.duration,
                log=ctx.log,
                watch=ctx.watch,
                tags=media_tags(
                    read_input(ctx, "song.json", SongInfo),
                    read_input(ctx, "lyrics.json", LyricsFile),
                ),
            )
        )
        if settings.zipped:
            engines.packer.pack(
                PackRequest(
                    target=song.output_dir / names[0],
                    members=(
                        PackMember(mp3_name, mp3_target),
                        PackMember(cdg_name, written.stream),
                    ),
                    time=ZIP_TIME,
                )
            )
        scheduled = written.scheduled
        ctx.log(
            f"cdg: {written.packets} packets ({scheduled.drawing_packets} drawing), "
            f"worst lag {scheduled.draw_lag * 1000:.0f} ms drawing, "
            f"{scheduled.wipe_lag * 1000:.0f} ms wiping; wrote {', '.join(names)}"
        )
        return CdgFile(
            fingerprint=fingerprint,
            enabled=True,
            profile=profile.name,
            files=names,
            zipped=settings.zipped,
            values=_values_of(fit),
            step=fit.step.number,
            step_name=fit.step.name,
            in_time=fit.in_time,
            late_lines=fit.late_lines,
            reasons=[] if fit.in_time else [_not_in_time(fit)],
            palette=[hex_of(entry) for entry in written.palette.entries],
            packets=written.packets,
            drawing_packets=scheduled.drawing_packets,
            draw_lag=round(scheduled.draw_lag, 3),
            wipe_lag=round(scheduled.wipe_lag, 3),
            seconds=round(time.monotonic() - started, 2),
        )


def _not_made_for_cdg(profile: Profile) -> str:
    """Return the error for a look without the CD+G marker."""
    what = "has no cdg section" if profile.cdg is None else "has cdg.made_for_cdg: false"
    return (
        f"the profile {profile.name!r} is not made for CD+G: it {what}; add a cdg section with "
        "made_for_cdg: true (see docs/user/cdg.md) or choose a look that is made for CD+G"
    )


def _values_of(fit: Fit) -> CdgValues:
    """Return the CD+G values a stream was written with, after the fallback step."""
    section = cdg_section(fit.profile)
    return CdgValues(
        slots=section.slots,
        font_px=section.font_px,
        min_font_px=section.min_font_px,
        edge_px=section.edge_px,
        wipe_columns=fit.step.wipe_columns,
        lead_in_min=fit.profile.lead_in.min,
    )


def _not_in_time(fit: Fit) -> str:
    """Return the review reason of a song that is not in time after the last fallback step."""
    return (
        f"CD+G not in time: {fit.late_lines} lines drawn late, "
        f"wipe {fit.wipe_lag * 1000:.0f} ms behind"
    )


def _log_fit(ctx: StageContext, fit: Fit) -> None:
    """Write the shortfalls, the layout findings and the fallback step to the song log."""
    for found in fit.scene.shortfalls:
        where = "" if found.line is None else f" line {found.line}:"
        ctx.log(f"cdg: shortfall ({found.kind}){where} {found.message}")
    for finding in scene_findings(fit.scene, fit.profile):
        ctx.log(f"cdg: {finding}")
    if fit.step.number:
        ctx.log(f"cdg: fallback step {fit.step.number} of {fit.steps - 1}: {fit.step.name}")
    if not fit.in_time:
        ctx.log(
            f"cdg: warning: not in time even with {fit.step.name}: lines drawn late: "
            f"{fit.late_lines}, wipe {fit.wipe_lag * 1000:.0f} ms behind; "
            "check the look with `vocatron profiles check`"
        )
