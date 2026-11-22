"""Text tables of the CD+G analysis: one block per song and one per vendor (numbers only)."""

from collections import Counter
from collections.abc import Sequence

from vocatron.core.cdg import TILE_WIDTH, Colour4
from vocatron.lab.cdg.analysis import Analysis, ColourUse, Countdown, Gap, median_or_none


def _num(value: float | None, unit: str = "", digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}{unit}"


def _rgb(colour: ColourUse | None) -> str:
    if colour is None:
        return "-"
    red, green, blue = colour.rgb
    return f"#{colour.index} ({red:x}{green:x}{blue:x})"


def _countdown(countdown: Countdown | None) -> str:
    if countdown is None:
        return "none"
    return (
        f"{countdown.ticks} ticks every {countdown.interval:.2f} s "
        f"from {countdown.first_tick:.1f} s, "
        f"{countdown.length:.1f} s long, last tick {countdown.before_wipe:.2f} s before the wipe, "
        f"left column {countdown.left_column}, rows {list(countdown.rows)}, "
        f"{countdown.draws} drawn / {countdown.erases} erased / {countdown.recoloured} recoloured"
    )


def _breaks(analysis: Analysis) -> list[Gap]:
    return [gap for gap in analysis.gaps if gap.is_break]


def song_block(name: str, analysis: Analysis) -> str:
    """Return the measured numbers of one song as indented text lines."""
    title = analysis.title
    lines = [f"song {name}: {analysis.duration:.1f} s, {len(analysis.lines)} wiped lines"]
    if title is None:
        lines.append("  title: none found")
    else:
        lines.append(
            f"  title: shown {title.shown_from:.2f} s, cleared "
            f"{_num(title.cleared_at, ' s')}, first wipe {title.first_wipe:.2f} s, "
            f"phase {title.duration:.2f} s, first line drawn {title.lyrics_from:.2f} s, "
            f"rows {list(title.rows)}, {title.lines} lines"
        )
    positions = ", ".join(f"{list(rows)}x{count}" for rows, count in analysis.row_positions[:6])
    align = analysis.alignment
    speed = analysis.wipe_speed
    tiles_per_second = None if speed is None else speed / TILE_WIDTH
    steps = median_or_none(float(line.wipe_steps) for line in analysis.lines)
    lines += [
        f"  lines per screen: median {_num(analysis.lines_per_screen, digits=1)}, "
        f"max {analysis.lines_per_screen_max}; tile rows {positions or '-'}",
        f"  alignment: {align.kind} (spread px: left {align.left_stdev:.1f}, centre "
        f"{align.centre_stdev:.1f}, right {align.right_stdev:.1f}; centre offset "
        f"{align.centre_offset:.1f}, left edge median {align.left_median:.0f})",
        f"  lead-in (drawn to first wipe): median {_num(analysis.lead_in, ' s')}",
        f"  wipe: {dict(analysis.wipe_methods) or '-'}, "
        f"speed {_num(analysis.wipe_speed, ' px/s', 1)} = {_num(tiles_per_second, ' tiles/s', 1)}"
        f", step {_num(analysis.wipe_step_px, ' px', 1)}, "
        f"sample {_num(analysis.wipe_sample_px, ' px', 1)}, "
        f"{_num(steps, ' steps per line', 0)}",
        f"  hold after wipe: median {_num(analysis.hold, ' s')}; ends {dict(analysis.end_kinds)}; "
        f"next line drawn {_num(analysis.redraw_delay, ' s')} after the wipe in the same rows",
        f"  palette: background {_rgb(analysis.palette.background)}, unsung "
        f"{_rgb(analysis.palette.unsung)}, sung {_rgb(analysis.palette.sung)}, "
        f"edge {_rgb(analysis.palette.edge)}",
        f"  singers: {_singers(analysis)}",
        f"  presets {analysis.presets}, scrolls {analysis.scrolls}, ending "
        f"{_num(analysis.ending, ' s')}, rows left at the end {list(analysis.rows_at_end)}",
    ]
    for gap in analysis.gaps:
        if gap.kind == "between" and not gap.is_break and gap.countdown is None and gap.bar is None:
            continue
        lines.append(
            f"  {gap.kind} gap {gap.start:.1f}-{gap.end:.1f} s ({gap.length:.1f} s)"
            f"{' BREAK' if gap.is_break else ''}: lyric rows kept {list(gap.sung_rows_at_middle)},"
            f" other text rows {list(gap.other_rows_at_middle)}, {gap.other_changes} other"
            f" changes; countdown: {_countdown(gap.countdown)};"
            f" progress bar: {_num(gap.bar, ' s', 1)}"
        )
    return "\n".join(lines)


def _singers(analysis: Analysis) -> str:
    if not analysis.singers:
        return "-"
    return "; ".join(f"{_rgb(s.unsung)} -> {_rgb(s.sung)} x{s.lines}" for s in analysis.singers[:4])


def _mode(values: Sequence[str | Colour4 | None]) -> str:
    found = Counter(v for v in values if v is not None)
    return ", ".join(f"{k} x{n}" for k, n in found.most_common(3)) or "-"


def vendor_block(vendor: str, songs: Sequence[tuple[str, Analysis]]) -> str:
    """Return the medians over the songs of one vendor as text lines."""
    found = [analysis for _, analysis in songs]
    countdowns = [g.countdown for a in found for g in a.gaps if g.countdown is not None]
    bars = [g.bar for a in found for g in a.gaps if g.bar is not None]
    breaks = [g for a in found for g in _breaks(a)]
    titles = [a.title.duration if a.title else None for a in found]
    singers = max((len(a.singers) for a in found), default=0)
    rows = [
        ("title phase (median)", _num(median_or_none(titles), " s")),
        (
            "lines per screen (median)",
            _num(median_or_none([a.lines_per_screen for a in found]), "", 1),
        ),
        ("most lines on screen", str(max((a.lines_per_screen_max for a in found), default=0))),
        ("alignment", _mode([a.alignment.kind for a in found])),
        ("lead-in (median)", _num(median_or_none([a.lead_in for a in found]), " s")),
        ("wipe speed (median)", _num(median_or_none([a.wipe_speed for a in found]), " px/s", 1)),
        ("wipe step (median)", _num(median_or_none([a.wipe_step_px for a in found]), " px", 1)),
        (
            "wipe sample advance (median)",
            _num(median_or_none([a.wipe_sample_px for a in found]), " px", 1),
        ),
        ("wipe methods", _mode([m for a in found for m, _ in a.wipe_methods])),
        ("hold after the wipe (median)", _num(median_or_none([a.hold for a in found]), " s")),
        (
            "next line drawn after the wipe",
            _num(median_or_none([a.redraw_delay for a in found]), " s"),
        ),
        ("ways lines end", _mode([kind for a in found for kind, _ in a.end_kinds])),
        ("unsung colour", _mode([_rgb(a.palette.unsung) for a in found])),
        ("sung colour", _mode([_rgb(a.palette.sung) for a in found])),
        ("background colour", _mode([_rgb(a.palette.background) for a in found])),
        (
            "breaks / countdowns / progress bars found",
            f"{len(breaks)} / {len(countdowns)} / {len(bars)}",
        ),
        (
            "countdown ticks (median)",
            _num(median_or_none([float(c.ticks) for c in countdowns]), "", 0),
        ),
        (
            "countdown interval (median)",
            _num(median_or_none([c.interval for c in countdowns]), " s"),
        ),
        (
            "countdown length (median)",
            _num(median_or_none([c.length for c in countdowns]), " s", 1),
        ),
        ("ending after the last wipe", _num(median_or_none([a.ending for a in found]), " s", 1)),
        ("most colour pairs in one song", str(singers)),
    ]
    lines = [f"vendor {vendor}: {len(found)} songs"]
    lines += [f"  {label}: {value}" for label, value in rows]
    return "\n".join(lines)
