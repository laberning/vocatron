"""Blind listening test of karaoke-mix variants on the local corpus (ADR-0002).

A *system* is one way of making the karaoke mix: a vocals model, an ensemble of two, the order of
the lead/backing split, the karaoke model. The first system is the current one.

    uv run --no-sync python tools/listening_test.py prepare --systems A B ...
    uv run --no-sync python tools/listening_test.py build --systems current mix
    uv run --no-sync python tools/listening_test.py score results.json [more sessions ...]

``prepare`` (with systems like ``current=model=bs-roformer-ep317`` and
``mix=karaoke_input=mix``) runs the separation stage of every corpus song once per system (GPU
safety rules of the stage apply) into ``<out>/work/<system>/<song>`` (default
``.corpus/listening``, never in git); a system is ``name=key=value;key=value`` with the keys
``model`` (``a`` or ``a+b`` for an ensemble), ``karaoke_input`` and ``karaoke_model``.
A folder under ``work/`` may be a link to a folder that already holds the separation
(for example the work folder of the benchmark).

``build`` takes the hardest passages of each song (where the lead voice is densest in the current
system, plus any ``--extra "<song>@<seconds>"``), cuts 10 s loops of the original and of every
system, levels them, writes lossless FLAC clips, ``key.json`` (which system is behind which clip)
and a static ``index.html`` with seamless switching. Each candidate is judged twice per passage with
swapped order, in different sessions, plus hidden identical pairs.

``score`` merges the ``results.json`` of the sessions, reveals the key and prints, per candidate,
wins, losses and ties, the sign test, the consistency checks, the criteria, the speed and peak GPU
memory, the sync benchmark per system and the verdict of the decision rule. Numbers and file names
only are printed.
"""

import argparse
import hashlib
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from vocatron.cli.app import real_engines
from vocatron.core.bench import BenchRun
from vocatron.core.separation.file import SeparationFile, stem_path
from vocatron.core.separation.rules import SAMPLE_RATE, Audio
from vocatron.engines.audio import decode
from vocatron.engines.separation.output import write_flac
from vocatron.lab.separation.listening import (
    CRITERIA,
    EXCERPT_SECONDS,
    ORIGINAL,
    PASSAGES_PER_SONG,
    TRIALS_PER_SESSION,
    ListeningKey,
    PairTally,
    Passage,
    Results,
    Window,
    common_medians,
    decide,
    judgements_by_trial,
    make_key,
    match_levels,
    merge_results,
    plan_passages,
    tally,
)
from vocatron.lab.separation.page import clip_path, render_page
from vocatron.stages.batch import Options, make_song
from vocatron.stages.config import Config
from vocatron.stages.songs import discover

DEFAULT_OUT = Path(".corpus/listening")
DEFAULT_SONGS = Path(".corpus/songs")
DEFAULT_BENCH = Path(".corpus/bench")
DEFAULT_GPU_GIB = 8188 / 1024
"""The memory of the development GPU (8188 MiB)."""
KEY_FILE = "key.json"
PAGE_FILE = "index.html"
SEED_DEFAULT = 2026
SPEC_KEYS = ("model", "karaoke_input", "karaoke_model")
Prepare = Callable[[Mapping[str, str], Path, Path], list[str]]
"""Separates the songs of a folder with each system (name to spec) into ``<out>/work/<name>``.

Returns the names of the songs."""
Locate = Callable[[Path], dict[str, Path]]
"""Returns the audio file of every song name in a songs folder."""


def work_dir(out: Path, system: str, song: str) -> Path:
    """Return the work folder of ``song`` made by ``system``."""
    return out / "work" / system / song


def read_stem(folder: Path, name: str) -> Audio:
    """Read a stem of a work folder as (channels, samples) float32."""
    data, rate = sf.read(folder / stem_path(name), dtype="float32", always_2d=True)
    if rate != SAMPLE_RATE:
        raise ValueError(f"{folder / stem_path(name)} has the sample rate {rate}")
    return np.ascontiguousarray(data.T, dtype=np.float32)


def parse_system(text: str) -> tuple[str, dict[str, object]]:
    """Split ``name=key=value;key=value`` into the name and the ``separation`` settings.

    ``model=a+b`` makes an ensemble of the two.

    Raises:
        ValueError: If the text is malformed or a key is unknown.
    """
    name, _, rest = text.partition("=")
    if not name or not rest:
        raise ValueError(f"a system is name=key=value;..., not {text!r}")
    settings: dict[str, object] = {}
    for part in rest.split(";"):
        key, _, value = part.partition("=")
        if key not in SPEC_KEYS or not value:
            raise ValueError(f"unknown setting {part!r}; known keys: {', '.join(SPEC_KEYS)}")
        settings[key] = value.split("+") if key == "model" and "+" in value else value
    return name, settings


def prepare_all(systems: Mapping[str, str], songs: Path, out: Path) -> list[str]:
    """Run the separation stage of every song for every system; return the song names.

    Raises:
        RuntimeError: If a song does not separate.
    """
    engines = real_engines()
    names: list[str] = []
    for index, (name, spec) in enumerate(systems.items()):
        _, settings = parse_system(f"{name}={spec}")
        config = Config.model_validate(
            {
                "output": {"folder": str((out / "work" / name).resolve())},
                "separation": settings,
            }
        )
        for song in discover(songs, config, engines):
            print(f"separating {song.name} for {name}", flush=True)
            result = make_song(song, config, engines, Options(only=("separation",)))
            if result.status.state == "failed":
                raise RuntimeError(f"{song.name} failed for {name}; see its log.txt")
            if index == 0:
                names.append(song.name)
    return names


def locate_songs(songs: Path) -> dict[str, Path]:
    """Return the audio file of every song in ``songs`` by the song's name."""
    config = Config()
    return {song.name: song.source for song in discover(songs, config, real_engines())}


@dataclass(frozen=True)
class PassageOptions:
    """How passages are chosen.

    Attributes:
        seed: The seed of the random order.
        seconds: The length of a passage.
        count: Passages per song.
        extra: Passages chosen by hand, ``"<song>@<seconds>"``.
    """

    seed: int = SEED_DEFAULT
    seconds: float = EXCERPT_SECONDS
    count: int = PASSAGES_PER_SONG
    extra: Sequence[str] = ()


def passage_list(
    songs: Sequence[str], reference: str, out: Path, options: PassageOptions
) -> list[Passage]:
    """Choose the passages of every song from the lead stem of the reference system.

    Raises:
        ValueError: If an ``--extra`` is not ``<song>@<seconds>`` or names an unknown song.
    """
    wanted: dict[str, list[float]] = {song: [] for song in songs}
    for item in options.extra:
        song, _, start = item.rpartition("@")
        if song not in wanted:
            raise ValueError(f"--extra {item!r}: no such song")
        wanted[song].append(float(start))
    passages: list[Passage] = []
    for song in songs:
        lead = read_stem(work_dir(out, reference, song), "lead")
        windows = plan_passages(
            lead, seconds=options.seconds, count=options.count, extra_starts=wanted[song]
        )
        for window in windows:
            passages.append(Passage(id=f"p{len(passages) + 1:02d}", song=song, window=window))
    return passages


def cut(audio: Audio, window: Window) -> Audio:
    """Cut a window out of audio."""
    start = round(window.start * SAMPLE_RATE)
    return audio[:, start : start + round(window.seconds * SAMPLE_RATE)]


def write_clips(key: ListeningKey, out: Path, originals: Mapping[str, Path]) -> None:
    """Cut every passage from the original and each system's karaoke mix, level it, write FLAC."""
    (out / "clips").mkdir(parents=True, exist_ok=True)
    by_passage: dict[str, dict[str, list[str]]] = {}
    for clip in key.clips:
        by_passage.setdefault(clip.passage, {}).setdefault(clip.system, []).append(clip.id)
    for passage in key.passages:
        sources: dict[str, Audio] = {
            ORIGINAL: cut(decode(str(originals[passage.song])), passage.window)
        }
        for system in key.systems:
            folder = work_dir(out, system, passage.song)
            sources[system] = cut(read_stem(folder, "karaoke"), passage.window)
        names = list(sources)
        length = min(a.shape[1] for a in sources.values())
        levelled = match_levels([sources[n][:, :length] for n in names])
        for name, audio in zip(names, levelled, strict=True):
            for clip_id in by_passage[passage.id][name]:
                write_flac(out / clip_path(clip_id), audio)


def build(
    songs: Sequence[str],
    systems: Sequence[str],
    out: Path,
    originals: Mapping[str, Path],
    options: PassageOptions = PassageOptions(),  # noqa: B008  # a frozen value, safe to share
) -> ListeningKey:
    """Make the clips, the key and the page for songs that are separated already."""
    passages = passage_list(songs, systems[0], out, options)
    key = make_key(passages, systems, options.seed, TRIALS_PER_SESSION)
    write_clips(key, out, originals)
    text = key.model_dump_json(indent=2) + "\n"
    (out / KEY_FILE).write_text(text, encoding="utf-8")
    build_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    (out / PAGE_FILE).write_text(render_page(key.trials, key.sessions, build_id), encoding="utf-8")
    return key


def read_bench(bench: Path, system: str, reference: str) -> BenchRun | None:
    """Return the benchmark run of ``system``, or ``None`` if there is none.

    The reference's is the accepted baseline; the others' are ``last-<system>.json``.
    """
    path = bench / ("baseline.json" if system == reference else f"last-{system}.json")
    if not path.is_file():
        return None
    return BenchRun.model_validate_json(path.read_text(encoding="utf-8"))


def speed_and_memory(out: Path, system: str, songs: list[str]) -> tuple[float | None, float | None]:
    """Return the separation time per second of audio and the peak GPU memory in GiB."""
    files = [
        work_dir(out, system, song) / "separation.json"
        for song in songs
        if (work_dir(out, system, song) / "separation.json").is_file()
    ]
    runs = [SeparationFile.model_validate_json(f.read_text(encoding="utf-8")) for f in files]
    audio = sum(run.samples / run.sample_rate for run in runs)
    peaks = [run.peak_vram_gib for run in runs if run.peak_vram_gib is not None]
    seconds = sum(run.seconds for run in runs if run.seconds is not None)
    return (seconds / audio if audio else None), (max(peaks) if peaks else None)


def pair_lines(result: PairTally) -> list[str]:
    """Format the counts and consistency checks of one candidate."""
    lines = [
        f"  judged {result.judged} times: preferred {result.wins}, reference preferred "
        f"{result.losses}, cannot tell {result.ties}; sign test p {result.p_value:.3f}",
        f"  {result.passages} passages judged in both orders: candidate won both "
        f"{result.consistent_wins}, reference won both {result.consistent_losses}, "
        f"different winners {result.flips}",
        f"  hidden identical pairs: {result.identical_tied} of {result.identical} judged "
        "'cannot tell'",
    ]
    for name in CRITERIA:
        better, worse, same = result.criteria[name]
        lines.append(
            f"  criterion {name}: candidate better {better}, reference better {worse}, same {same}"
        )
    return lines


def score(key: ListeningKey, results: Results, out: Path, bench: Path, gpu_gib: float) -> list[str]:
    """Reveal the key and return the lines of the report."""
    table = judgements_by_trial(key, results)
    songs = sorted({passage.song for passage in key.passages})
    reference = key.reference
    lines = [f"reference: {reference}; {len(key.trials)} judgements in {key.sessions} sessions"]
    for system in key.systems:
        factor, vram = speed_and_memory(out, system, songs)
        lines.append(
            f"{system}: separation {'-' if factor is None else f'{factor:.3f}'} s per s of audio "
            f"(all steps of the stage); peak VRAM {'-' if vram is None else f'{vram:.2f}'} GiB"
        )
    for candidate in key.systems[1:]:
        result = tally(key, table, candidate)
        factor, vram = speed_and_memory(out, candidate, songs)
        run, base = read_bench(bench, candidate, reference), read_bench(bench, reference, reference)
        sync, base_sync = common_medians(run, base) if run and base else (None, None)
        lines.append(f"{candidate} against {reference}:")
        lines.extend(pair_lines(result))
        verdict = decide(
            result,
            sync_median_ms=sync,
            reference_sync_median_ms=base_sync,
            peak_vram_gib=vram,
            gpu_gib=gpu_gib,
        )
        lines.extend(
            f"  [{'ok' if check.ok else 'FAIL'}] {check.name}: {check.detail}"
            for check in verdict.checks
        )
        lines.append(f"  verdict: {'may become the default' if verdict.passes else 'stays'}")
    return lines


def parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    commands = top.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="separate the corpus songs for each system")
    prep.add_argument("--systems", nargs="+", required=True, help="name=key=value;key=value ...")
    prep.add_argument("--songs", type=Path, default=DEFAULT_SONGS)
    prep.add_argument("--out", type=Path, default=DEFAULT_OUT)
    make = commands.add_parser("build", help="cut the passages, write the clips and the page")
    make.add_argument("--systems", nargs="+", required=True, help="names; the first is current")
    make.add_argument("--songs", type=Path, default=DEFAULT_SONGS)
    make.add_argument("--out", type=Path, default=DEFAULT_OUT)
    make.add_argument("--seed", type=int, default=SEED_DEFAULT)
    make.add_argument("--seconds", type=float, default=EXCERPT_SECONDS)
    make.add_argument("--passages", type=int, default=PASSAGES_PER_SONG, help="per song")
    make.add_argument("--extra", action="append", default=[], help='"<song>@<seconds>"')
    reveal = commands.add_parser("score", help="reveal the key and print the numbers")
    reveal.add_argument("results", type=Path, nargs="+", help="the results.json of the sessions")
    reveal.add_argument("--out", type=Path, default=DEFAULT_OUT)
    reveal.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    reveal.add_argument("--gpu-gib", type=float, default=DEFAULT_GPU_GIB)
    return top


def main(
    argv: Sequence[str] | None = None, prepare: Prepare = prepare_all, locate: Locate = locate_songs
) -> int:
    """Run the command line; return the exit code."""
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            systems = dict(
                parse_system(text)[0:1] + (text.partition("=")[2],) for text in args.systems
            )
            names = prepare(systems, args.songs, args.out)
            print(f"{len(names)} songs prepared for {len(systems)} systems")
        elif args.command == "build":
            originals = locate(args.songs)
            songs = sorted(
                s for s in originals if (work_dir(args.out, args.systems[0], s) / "stems").is_dir()
            )
            options = PassageOptions(args.seed, args.seconds, args.passages, args.extra)
            key = build(songs, args.systems, args.out, originals, options)
            print(f"{len(key.trials)} judgements in {key.sessions} sessions: open "
                  f"{args.out / PAGE_FILE}")  # fmt: skip
        else:
            key = ListeningKey.model_validate_json(
                (args.out / KEY_FILE).read_text(encoding="utf-8")
            )
            parts = [
                Results.model_validate_json(p.read_text(encoding="utf-8")) for p in args.results
            ]
            print("\n".join(score(key, merge_results(parts), args.out, args.bench, args.gpu_gib)))
    except (
        OSError,
        ValueError,
        RuntimeError,
    ) as error:  # a Pydantic ValidationError is a ValueError
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
