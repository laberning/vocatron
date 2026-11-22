"""Objective evaluation of separation models against true instrumentals (ADR-0002).

Three steps, all numbers and file names only, everything in ``.corpus/`` (never in git):

    uv run --no-sync python tools/separation_eval.py fetch [--tracks release|album]
    uv run --no-sync python tools/separation_eval.py run [--models ...]
    uv run --no-sync python tools/separation_eval.py report

``fetch`` downloads Josh Woodward's songs (CC BY) with their instrumental mix from the Internet
Archive mirror into ``.corpus/woodward/`` and writes ``items.json`` there. The material is
``.corpus/instrumentals/`` with the songs of ``.corpus/songs/`` that have an official
instrumental, plus every ``.corpus/*/items.json``. MVSep's multisong set is not usable: its
references are kept secret by MVSep, the download holds mixtures only.

``run`` separates all material with each candidate (a child process per batch with a timeout,
75 % VRAM cap, fp16, fsynced log), caches the estimated instrumentals under
``.corpus/eval/<model>/`` and is resumable; a candidate that fails to load or does not fit the GPU
is recorded in ``failures.jsonl`` and the others go on. The reference model also separates
MP3 versions of the official songs and the five earlier MP3 songs (the source-quality check).

``report`` lines every estimate up with its true instrumental by cross-correlation and prints, per
candidate, mean and standard error of SDR, SI-SDR, fullness and bleedless over all material and per
group, the speed and peak VRAM, the failures, the MP3-against-Ogg check and proposed finalists.
The ensembles are the waveform average of the cached outputs of two members.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

from vocatron.cli.app import real_engines
from vocatron.core.errors import StageError
from vocatron.core.models import VOCALS_MODELS, find_model
from vocatron.core.separation.rules import SAMPLE_RATE, Audio
from vocatron.engines.audio import decode
from vocatron.engines.gpu_process import Supervisor
from vocatron.engines.separation.eval_worker import append_line
from vocatron.lab.separation.evaluation import (
    ALL,
    ENSEMBLES,
    FULLNESS_MARGIN_DB,
    REFERENCE,
    EvalJob,
    EvalPair,
    EvalResult,
    Failure,
    Item,
    Items,
    Timing,
    ensemble_name,
    group_rows,
    plus_minus,
    propose_finalists,
    timing_summary,
)
from vocatron.lab.separation.metrics import (
    MEASURES,
    Scores,
    Summary,
    find_lag,
    score,
    summarise,
    trim_pair,
)
from vocatron.stages.models import LogListener, ModelFolder, ensure_models
from vocatron.stages.separation import model_setup

DEFAULT_CORPUS = Path(".corpus")
DEFAULT_OUT = Path(".corpus/eval")
CANDIDATES: tuple[str, ...] = VOCALS_MODELS
"""What stage A evaluates, in the order it runs (the reference, today's default, first)."""
MODELS_FOLDER = Path(".cache/models")
WORKER_COMMAND = (sys.executable, "-m", "vocatron.engines.separation.eval_worker")
BATCH = 6
"""Files per child process: a failure costs one batch, not the model."""
TIMEOUT_FACTOR = 3.0
"""A batch may run this many audio lengths plus ``TIMEOUT_BASE`` seconds."""
TIMEOUT_BASE = 600.0
MAX_LAG_SECONDS = 5.0
"""The search range for lining a true instrumental up with its mixture."""
BITRATES = (320, 192)
"""The MP3 versions made of the official songs for the source-quality check (kbit/s)."""
WOODWARD_MIX = "jamendo-158415"
WOODWARD_INSTRUMENTAL = "jamendo-158418"
ARCHIVE = "https://archive.org"
ITEMS_FILE = "items.json"

Download = Callable[[str, Path], None]
FetchJson = Callable[[str], dict[str, object]]
Runner = Callable[[str, Sequence[EvalPair], Path], None]
"""Separates the files with a model; the output goes where each pair says."""


def slug(text: str) -> str:
    """Return ``text`` as a short id of letters, digits and hyphens."""
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def http_json(url: str) -> dict[str, object]:
    """Fetch a JSON document."""
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def http_download(url: str, destination: Path) -> None:
    """Download ``url`` to ``destination`` (complete or not at all)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as file:
        while chunk := response.read(1 << 20):
            file.write(chunk)
    partial.replace(destination)


def sha1_of(path: Path) -> str:
    """Return the SHA-1 of a file (the Internet Archive lists SHA-1 sums)."""
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def archive_tracks(metadata: Mapping[str, object]) -> dict[int, tuple[str, str]]:
    """Return ``{track number: (file name, sha1)}`` of the MP3 files of an archive item."""
    files = metadata.get("files", [])
    tracks: dict[int, tuple[str, str]] = {}
    if not isinstance(files, list):
        return tracks
    for entry in files:
        name = str(entry.get("name", ""))
        if name.endswith(".mp3") and re.match(r"\d\d-", name):
            tracks[int(name[:2])] = (name, str(entry.get("sha1", "")))
    return tracks


def fetch_woodward(
    corpus: Path, tracks: str, fetch_json: FetchJson = http_json, download: Download = http_download
) -> Items:
    """Download Josh Woodward's songs and their instrumental mixes; write ``items.json``.

    Args:
        corpus: The corpus folder; the files go to ``woodward/`` in it.
        tracks: ``release`` (track 1 of "Addressed to the Stars") or ``album`` (all 14 tracks).
        fetch_json: Fetches the metadata of an archive item.
        download: Downloads a URL to a file.

    Raises:
        ValueError: If a checksum differs from the archive's or a track has no instrumental.
    """
    folder = corpus / "woodward"
    mixes = archive_tracks(fetch_json(f"{ARCHIVE}/metadata/{WOODWARD_MIX}"))
    instrumentals = archive_tracks(fetch_json(f"{ARCHIVE}/metadata/{WOODWARD_INSTRUMENTAL}"))
    wanted = [1] if tracks == "release" else sorted(mixes)
    items: list[Item] = []
    for number in wanted:
        if number not in instrumentals:
            raise ValueError(f"track {number} has no instrumental version")
        paths: list[str] = []
        for role, (item, (name, sha1)) in (
            ("mix", (WOODWARD_MIX, mixes[number])),
            ("instrumental", (WOODWARD_INSTRUMENTAL, instrumentals[number])),
        ):
            target = folder / f"track-{number:02d}-{role}.mp3"
            if not target.is_file():
                download(f"{ARCHIVE}/download/{item}/{urllib.parse.quote(name)}", target)
            if sha1_of(target) != sha1:
                target.unlink()
                raise ValueError(f"{target.name}: the SHA-1 differs from the archive's {sha1}")
            paths.append(f"woodward/{target.name}")
        items.append(
            Item(id=f"woodward-{number:02d}", group="woodward", mix=paths[0], truth=paths[1],
                 source="mp3")
        )  # fmt: skip
    result = Items(
        items=tuple(items),
        note="Josh Woodward, Addressed to the Stars, CC BY 3.0 (Jamendo mirror on the Internet "
        "Archive, jamendo-158415 and jamendo-158418); lossy VBR MP3 is the best source there.",
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ITEMS_FILE).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def official_items(corpus: Path) -> list[Item]:
    """Return the official instrumentals that have their song in ``songs/``."""
    items: list[Item] = []
    for truth in sorted((corpus / "instrumentals").glob("*.ogg")):
        song = corpus / "songs" / truth.name
        if song.is_file():
            items.append(
                Item(
                    id=slug(truth.stem),
                    group="official",
                    mix=f"songs/{song.name}",
                    truth=f"instrumentals/{truth.name}",
                    source="ogg",
                )
            )
    return items


def collect_items(corpus: Path) -> list[Item]:
    """Return all material: the official instrumentals and every ``<folder>/items.json``."""
    items = official_items(corpus)
    for path in sorted(corpus.glob(f"*/{ITEMS_FILE}")):
        items.extend(Items.model_validate_json(path.read_text(encoding="utf-8")).items)
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("two pieces of material have the same id")
    return items


def mp3_pairs(corpus: Path) -> list[tuple[str, Path, Path]]:
    """Return ``(id, ogg, mp3)`` of every song that exists in both ``songs/`` and ``mp3/``."""
    return [
        (slug(mp3.stem), ogg, mp3)
        for mp3 in sorted((corpus / "mp3").glob("*.mp3"))
        if (ogg := corpus / "songs" / f"{mp3.stem}.ogg").is_file()
    ]


def encode_mp3(source: Path, kbit: int, destination: Path) -> None:
    """Encode ``source`` as CBR MP3 at ``kbit`` kbit/s with ffmpeg."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source), "-vn",
               "-c:a", "libmp3lame", "-b:a", f"{kbit}k", str(destination)]  # fmt: skip
    subprocess.run(command, check=True, timeout=600)


def variant_path(out: Path, item_id: str, kbit: int) -> Path:
    """Return where the MP3 version of an official mixture is kept."""
    return out / "sources" / f"{item_id}-mp3-{kbit}.mp3"


def variant_item(corpus: Path, out: Path, item: Item, kbit: int) -> Item:
    """Return the MP3 version of an official mixture as material with the same truth."""
    return Item(
        id=f"{item.id}-mp3-{kbit}",
        group=f"mp3-{kbit}",
        mix=os.path.relpath(variant_path(out, item.id, kbit), corpus),
        truth=item.truth,
        source="mp3",
    )


def source_variants(corpus: Path, out: Path, items: Sequence[Item]) -> list[Item]:
    """Make MP3 versions of the official mixtures; return them as material with the same truth."""
    variants: list[Item] = []
    for item in items:
        if item.group != "official":
            continue
        for kbit in BITRATES:
            target = variant_path(out, item.id, kbit)
            if not target.is_file():
                encode_mp3(corpus / item.mix, kbit, target)
            variants.append(variant_item(corpus, out, item, kbit))
    return variants


def pairs_for(model: str, out: Path, files: Mapping[str, Path]) -> list[EvalPair]:
    """Return the work of a model: one pair per file, with the output in the model's folder."""
    return [
        EvalPair(name=name, audio=str(path), output=str(out / model / f"{name}.wav"))
        for name, path in files.items()
    ]


def audio_seconds(path: Path) -> float:
    """Return the length of an audio file in seconds (``600`` if it cannot be read)."""
    try:
        return float(sf.info(path).duration)
    except OSError, RuntimeError:
        return 600.0


def real_runner(model: str, pairs: Sequence[EvalPair], out: Path) -> None:
    """Separate ``pairs`` with ``model`` in child processes, a batch at a time.

    Raises:
        StageError: If a batch fails (out of memory, timeout, crash); finished files stay.
    """
    engines = real_engines()
    folder = ModelFolder(MODELS_FOLDER, engines.store)
    log_file = out / model / "log.txt"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        append_line(log_file, message)  # synced to disk: a crash leaves evidence

    ensure_models(
        [model], folder=folder, downloader=engines.downloader, offline=False,
        listener=LogListener(log),
    )  # fmt: skip
    setup = model_setup(find_model(model), folder)
    supervisor = Supervisor("evaluation", WORKER_COMMAND, TIMEOUT_BASE)
    choice = supervisor.choose("cuda")  # never the CPU for hours: no GPU is an error
    todo = [pair for pair in pairs if not Path(pair.output).is_file()]
    for start in range(0, len(todo), BATCH):
        batch = tuple(todo[start : start + BATCH])
        length = sum(audio_seconds(Path(pair.audio)) for pair in batch)
        job = EvalJob(
            log_path=str(log_file),
            result_path=str(out / model / "result.json"),
            device=choice.device,
            model=setup,
            pairs=batch,
            timings_path=str(out / model / "timings.jsonl"),
        )
        print(f"{model}: {len(batch)} files, {length:.0f} s of audio", flush=True)
        supervisor.run(
            job, out / model / "job.json", TIMEOUT_FACTOR * length + TIMEOUT_BASE, log, EvalResult
        )


def record_failure(out: Path, failure: Failure) -> None:
    """Append a failure to the model's ``failures.jsonl``, synced to disk."""
    folder = out / failure.model
    folder.mkdir(parents=True, exist_ok=True)
    append_line(folder / "failures.jsonl", failure.model_dump_json())


def run_all(models: Sequence[str], corpus: Path, out: Path, runner: Runner) -> int:
    """Separate the material with each model; return how many models had a failure.

    A model that fails is recorded, the others go on. The reference also separates the MP3
    versions and the MP3 songs (the source-quality check).
    """
    items = collect_items(corpus)
    material = {item.id: corpus / item.mix for item in items}
    extra = {item.id: corpus / item.mix for item in source_variants(corpus, out, items)}
    for pair_id, ogg, mp3 in mp3_pairs(corpus):
        extra[f"pair-ogg-{pair_id}"] = ogg
        extra[f"pair-mp3-{pair_id}"] = mp3
    failed = 0
    for model in models:
        files = {**material, **(extra if model == REFERENCE else {})}
        try:
            runner(model, pairs_for(model, out, files), out)
        except StageError as error:
            failed += 1
            message = str(error).splitlines()[0] if str(error) else ""
            print(f"{model}: FAILED {error.kind}: {message}", flush=True)
            record_failure(
                out,
                Failure(model=model, items=tuple(files), kind=error.kind, message=message[:500]),
            )
    return failed


# ------------------------------------------------------------------------------------ report


def read_estimate(out: Path, model: str, name: str) -> Audio | None:
    """Read a cached estimate (channels, samples), or ``None`` if there is none."""
    path = out / model / f"{name}.wav"
    if not path.is_file():
        return None
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != SAMPLE_RATE:
        raise ValueError(f"{path} has the sample rate {rate}")
    return np.ascontiguousarray(data.T, dtype=np.float32)


class Lines:
    """The true instrumentals and mixtures, decoded once, and the lag between them."""

    def __init__(self, corpus: Path, out: Path) -> None:
        """Remember the folders; ``lags.json`` in ``out`` caches the lags."""
        self._corpus = corpus
        self._cache = out / "lags.json"
        self._lags: dict[str, int] = (
            json.loads(self._cache.read_text(encoding="utf-8")) if self._cache.is_file() else {}
        )
        self._truth: dict[str, Audio] = {}

    def truth(self, item: Item) -> Audio:
        """Return the true instrumental of ``item`` (the last one is kept in memory)."""
        if item.truth not in self._truth:
            self._truth.clear()
            self._truth[item.truth] = decode(str(self._corpus / item.truth))
        return self._truth[item.truth]

    def lag(self, item: Item) -> int:
        """Return by how many samples the mixture lags the true instrumental."""
        key = f"{item.truth}|{item.mix}"
        if key not in self._lags:
            mix = decode(str(self._corpus / item.mix))
            self._lags[key] = find_lag(self.truth(item), mix, int(MAX_LAG_SECONDS * SAMPLE_RATE))
            self._cache.write_text(json.dumps(self._lags, indent=1), encoding="utf-8")
        return self._lags[key]


def score_against_truth(lines: Lines, item: Item, estimate: Audio) -> Scores:
    """Line the estimate up with the true instrumental and return the four measures."""
    truth, aligned = trim_pair(lines.truth(item), estimate, lines.lag(item))
    return score(truth, aligned)


def average(first: Audio, second: Audio) -> Audio:
    """Return the waveform average of two estimates (the shorter length)."""
    length = min(first.shape[1], second.shape[1])
    return ((first[:, :length] + second[:, :length]) / np.float32(2)).astype(np.float32)


def candidate_scores(
    name: str, items: Sequence[Item], out: Path, lines: Lines
) -> dict[str, Scores]:
    """Return the scores of a candidate or ensemble on the items it has estimates for.

    Scores are cached in ``scores/<name>.json``; an ensemble is formed from its members.
    """
    cache = out / "scores" / f"{slug(name)}.json"
    known: dict[str, Scores] = {}
    if cache.is_file():
        known = {k: Scores(**v) for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    members = next((m for m in ENSEMBLES if ensemble_name(m) == name), None)
    for item in items:
        if item.id in known:
            continue
        if members is None:
            estimate = read_estimate(out, name, item.id)
        else:
            first, second = (read_estimate(out, member, item.id) for member in members)
            estimate = average(first, second) if first is not None and second is not None else None
        if estimate is not None:
            known[item.id] = score_against_truth(lines, item, estimate)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({k: vars(v) for k, v in known.items()}, indent=1), encoding="utf-8")
    return known


def read_timings(out: Path, model: str) -> list[Timing]:
    """Return the timings of a model (the last line of an item wins)."""
    path = out / model / "timings.jsonl"
    if not path.is_file():
        return []
    latest: dict[str, Timing] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            timing = Timing.model_validate_json(line)
            latest[timing.name] = timing
    return list(latest.values())


def read_failures(out: Path, model: str) -> list[Failure]:
    """Return the failures recorded for a model."""
    path = out / model / "failures.jsonl"
    if not path.is_file():
        return []
    return [
        Failure.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def table_lines(name: str, rows: Mapping[str, Mapping[str, Summary]]) -> list[str]:
    """Format the per-group summaries of one candidate."""
    lines = [name]
    for group, summaries in rows.items():
        cells = "  ".join(f"{measure} {plus_minus(summaries[measure])}" for measure in MEASURES)
        count = summaries[MEASURES[0]].count
        lines.append(f"  {group:<10} n={count:<3} {cells}")
    return lines


def source_check(out: Path, corpus: Path, lines: Lines, items: Sequence[Item]) -> list[str]:
    """Return the lines of the MP3-against-Ogg check (reference model, five MP3 songs)."""
    result = ["", f"Source quality ({REFERENCE}):"]
    scored: list[Scores] = []
    for pair_id, _, _ in mp3_pairs(corpus):
        ogg = read_estimate(out, REFERENCE, f"pair-ogg-{pair_id}")
        mp3 = read_estimate(out, REFERENCE, f"pair-mp3-{pair_id}")
        if ogg is None or mp3 is None:
            continue
        lag = find_lag(ogg, mp3, int(MAX_LAG_SECONDS * SAMPLE_RATE))
        first, second = trim_pair(ogg, mp3, lag)
        scored.append(score(first, second))
        result.append(
            f"  mp3 against ogg, {pair_id}: lag {lag} samples, SDR {scored[-1].sdr:.2f} dB"
        )
    if scored:
        sdr = summarise([s.sdr for s in scored])
        result.append(
            f"  instrumental from MP3 against from Ogg ({sdr.count} songs): "
            f"SDR {plus_minus(sdr)} dB; "
            f"fullness {plus_minus(summarise([s.fullness for s in scored]))}; bleedless "
            f"{plus_minus(summarise([s.bleedless for s in scored]))}"
        )
    official = [item for item in items if item.group == "official"]
    own = candidate_scores(REFERENCE, official, out, lines)
    for kbit in BITRATES:
        for item in official:
            variant = variant_item(corpus, out, item, kbit)
            estimate = read_estimate(out, REFERENCE, variant.id)
            if estimate is None or item.id not in own:
                continue
            mp3_scores = score_against_truth(lines, variant, estimate)
            result.append(
                f"  official song {item.id} as MP3 {kbit} kbit/s: SDR {mp3_scores.sdr:.2f} dB, "
                f"{mp3_scores.sdr - own[item.id].sdr:+.2f} dB against the Ogg version"
            )
    return result


def report(corpus: Path, out: Path) -> list[str]:
    """Return the lines of the report."""
    items = collect_items(corpus)
    groups = {item.id: item.group for item in items}
    lines = Lines(corpus, out)
    names = [m for m in CANDIDATES if (out / m).is_dir()]
    names += [ensemble_name(m) for m in ENSEMBLES if all(x in names for x in m)]
    result = [
        "Stage A: objective scores against true instrumentals (mean ± standard error; "
        "SDR and SI-SDR in dB, fullness and bleedless 0 to 100, higher is better).",
        "Material: "
        + ", ".join(
            f"{g} {sum(1 for v in groups.values() if v == g)}" for g in sorted(set(groups.values()))
        )
        + ".",  # fmt: skip
        "",
    ]
    means: dict[str, tuple[float, float]] = {}
    for name in names:
        scores = candidate_scores(name, items, out, lines)
        rows = group_rows(scores, groups)
        result.extend(table_lines(name, rows))
        speed, vram = (
            timing_summary(read_timings(out, name)) if name in CANDIDATES else (None, None)
        )
        failures = read_failures(out, name) if name in CANDIDATES else []
        result.append(
            f"  speed {'-' if speed is None else f'{speed:.3f}'} s per s of audio; peak VRAM "
            f"{'-' if vram is None else f'{vram:.2f}'} GiB; failures {len(failures)}"
            + "".join(f" [{f.kind}: {f.message}]" for f in failures)
        )
        everything = rows.get(ALL)
        if everything:
            means[name] = (everything["sdr"].mean, everything["fullness"].mean)
    result.extend(source_check(out, corpus, lines, items))
    result.append("")
    result.append(
        f"Proposed finalists (best SDR, a fuller one within {FULLNESS_MARGIN_DB} dB may replace "
        "the last): "
    )
    result[-1] += ", ".join(propose_finalists(means)) or "none yet"
    return result


def parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    top.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    top.add_argument("--out", type=Path, default=DEFAULT_OUT)
    commands = top.add_subparsers(dest="command", required=True)
    get = commands.add_parser("fetch", help="download Josh Woodward's songs with instrumentals")
    get.add_argument("--tracks", choices=("release", "album"), default="release")
    go = commands.add_parser("run", help="separate all material with each candidate")
    go.add_argument("--models", nargs="+", default=list(CANDIDATES), choices=VOCALS_MODELS)
    commands.add_parser("report", help="print the scores, speed, source check and finalists")
    return top


def main(argv: Sequence[str] | None = None, runner: Runner = real_runner) -> int:
    """Run the command line; return the exit code."""
    args = parser().parse_args(argv)
    try:
        if args.command == "fetch":
            items = fetch_woodward(args.corpus, args.tracks)
            print(f"{len(items.items)} songs in {args.corpus / 'woodward'}")
        elif args.command == "run":
            failed = run_all(args.models, args.corpus, args.out, runner)
            print(f"done; {failed} model(s) failed")
        else:
            print("\n".join(report(args.corpus, args.out)))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
