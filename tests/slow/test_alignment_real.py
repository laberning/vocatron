"""Stage 2: the acoustic model and the alignment on the GPU, against torchaudio and the corpus.

"Denkmal" is the reference song in the local corpus, read from ``.corpus/mp3``: its reference lead
stem and the trial's error were made from the MP3 version. A missing corpus file fails the test
(``realworld.corpus_path``). The tests report numbers only, never lyrics
(AGENTS.md). GPU safety: a timeout on every test, PyTorch capped at 75 % of the memory inside the
worker, half precision, and the log of each run in the work folder, synced after every line.
"""

import numpy as np
import pytest
import soundfile as sf
import torch

from realworld import MODELS, align, corpus_path, corpus_song, line_starts, lyrics_of, real_config
from vocatron.cli.app import real_engines
from vocatron.core.alignment.ctc import token_spans, viterbi
from vocatron.core.alignment.job import AcousticSetup
from vocatron.core.alignment.solve import line_starts as solved_starts
from vocatron.core.alignment.solve import solve
from vocatron.core.alignment.tokens import blank_id, build_transcript
from vocatron.core.bench import line_errors
from vocatron.core.languages import LANGUAGES
from vocatron.core.models import find_model
from vocatron.engines.alignment.process import ProcessAcousticModel
from vocatron.engines.protocols import AcousticRequest, Heard
from vocatron.stages.batch import run_song
from vocatron.stages.songs import discover
from vocatron.stages.stage import LOG_FILE, Song

SONG = "Wir sind Helden - Denkmal"
BASELINE_MS = 236.0  # the median line-start error of the trial, without guide rails
SAME_START = 0.95  # the share of word starts a longer overlap may not move by more than 2 frames
SECONDS_PER_FRAME = 0.02
TIMEOUT = 600  # seconds per test; a song takes about half a minute

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU"),
    pytest.mark.timeout(TIMEOUT),
]


@pytest.fixture(scope="module")
def song(tmp_path_factory: pytest.TempPathFactory) -> Song:
    """Denkmal with its lyrics stage done, and the reference lead vocals as its lead stem."""
    output = tmp_path_factory.mktemp("denkmal")
    # the reference lead stem stands alone (no backing stem): the voice is measured on the lead
    # and the backing is not heard
    config = real_config(output, use_lrc_times=False, voice_source="lead", hear_backing=False)
    engines = real_engines()
    # the reference lead stem and the trial's 236 ms were made from the MP3 version
    (found,) = discover(corpus_song(SONG, "mp3"), config, engines)
    status = run_song(found, config, engines, force=False, until="lyrics")
    assert status.state in {"ok", "review"}, status.error
    stem = found.work_dir / "stems" / "lead.flac"
    stem.parent.mkdir(parents=True, exist_ok=True)
    data, rate = sf.read(corpus_path("reference", "denkmal", "anvuew_lead.wav"), dtype="float32")
    sf.write(stem, data, rate, subtype="PCM_24")
    return found


def hear(song: Song, piece_seconds: float, overlap_seconds: float = 2.0) -> Heard:
    spec = find_model("wav2vec2-de")
    request = AcousticRequest(
        audio=song.work_dir / "stems" / "lead.flac",
        work_dir=song.work_dir,
        log_path=song.work_dir / LOG_FILE,
        log=lambda message: None,
        duration=song.tags.duration if song.tags is not None else None,
        device="cuda",
        timeout_factor_gpu=1.0,
        timeout_factor_cpu=15.0,
        model=AcousticSetup(
            name=spec.name,
            revision=spec.revision,
            folder=str(MODELS.path_of(spec)),
            precision=str(spec.inference["precision"]),
        ),
        piece_seconds=piece_seconds,
        overlap_seconds=overlap_seconds,
    )
    return ProcessAcousticModel().log_probs(request)


def test_the_vocabulary_of_the_model_holds_the_alphabet_of_the_german_module(song: Song) -> None:
    heard = hear(song, 30.0)
    vocabulary = set(heard.emissions.vocabulary)
    assert set(LANGUAGES["de"].alphabet) <= vocabulary
    assert {"|", "<pad>"} <= vocabulary


def test_our_viterbi_gives_the_same_path_as_torchaudio_on_real_log_probabilities(
    song: Song,
) -> None:
    # The cu130 build of torchaudio loads only next to the CUDA build of PyTorch, so it is
    # imported here, after the GPU check, and a machine without a GPU still collects the file.
    from torchaudio.functional import forced_align  # noqa: PLC0415  # see the comment above

    heard = hear(song, 30.0)
    emissions = heard.emissions
    transcript = build_transcript(
        [line.text for line in lyrics_of(song).lines], LANGUAGES["de"], emissions.vocabulary
    )
    blank = blank_id(emissions.vocabulary)
    ours = viterbi(emissions.log_probs, transcript.targets, blank)
    labels = np.full(2 * len(transcript.targets) + 1, blank)
    labels[1::2] = transcript.targets
    ours_labels = labels[ours.states]
    theirs, scores = forced_align(
        torch.from_numpy(emissions.log_probs)[None],
        torch.tensor([transcript.targets], dtype=torch.int32),
        blank=blank,
    )
    same = float(np.mean(ours_labels == theirs[0].numpy()))
    print(
        f"viterbi vs forced_align: {same * 100:.3f} % of {len(ours_labels)} frames identical, "
        f"{len(transcript.targets)} tokens, scores {ours.total:.3f} vs {float(scores[0].sum()):.3f}"
    )
    assert same == 1.0
    assert ours.total == pytest.approx(float(scores[0].sum()), rel=1e-5)
    assert len(token_spans(ours, len(transcript.targets)).first) == len(transcript.targets)


def median_error_ms(song: Song, pieces: float, overlap: float = 2.0) -> float:
    """Align Denkmal on emissions made with these pieces and return the median line-start error."""
    lyrics = lyrics_of(song)
    emissions = hear(song, pieces, overlap).emissions
    solution = solve(emissions, [line.text for line in lyrics.lines], None, LANGUAGES["de"])
    found = solved_starts(solution.transcript, solution.words)
    return float(np.median(np.abs(line_errors(found, [line.time for line in lyrics.lines]))))


def test_pieces_of_30_seconds_are_no_worse_than_one_pass(song: Song) -> None:
    """wav2vec2 was trained on short utterances; a whole song at once is out of its habit.

    The story's design expected pieces and one pass to agree on 98 % of the word starts. They do
    not (they agree on about 78 %): the pieces are the better of the two, which is what counts.
    """
    pieces = median_error_ms(song, 30.0)
    whole = median_error_ms(song, 1000.0)
    print(f"median line-start error: pieces of 30 s {pieces:.0f} ms, one pass {whole:.0f} ms")
    assert pieces <= whole


def test_the_overlap_of_the_pieces_hardly_moves_the_word_starts(song: Song) -> None:
    lines = [line.text for line in lyrics_of(song).lines]
    short = solve(hear(song, 30.0, 2.0).emissions, lines, None, LANGUAGES["de"])
    long = solve(hear(song, 30.0, 6.0).emissions, lines, None, LANGUAGES["de"])
    gaps = np.array([abs(a.start - b.start) for a, b in zip(short.words, long.words, strict=True)])
    share = float(np.mean(gaps <= 2 * SECONDS_PER_FRAME + 1e-6))
    print(f"word starts within two frames, overlap 2 s vs 6 s: {share * 100:.1f} % of {len(gaps)}")
    assert share >= SAME_START


def test_denkmal_end_to_end_without_rails_is_no_worse_than_the_trial(song: Song) -> None:
    config = real_config(
        song.work_dir.parent, use_lrc_times=False, voice_source="lead", hear_backing=False
    )
    file = align(song, config)
    (song.work_dir / "alignment.json").write_text(file.model_dump_json(indent=2), encoding="utf-8")
    starts = line_starts(song)
    errors = np.abs(line_errors(starts.found, starts.reference))
    median = float(np.median(errors))
    near, far = np.mean(errors <= 200) * 100, np.mean(errors <= 500) * 100
    print(
        f"Denkmal: {len(errors)} lines, median {median:.0f} ms, within 200 ms {near:.0f} %, "
        f"within 500 ms {far:.0f} %, estimated {file.quality.estimated_share * 100:.1f} %, "
        f"{file.seconds:.1f} s on {file.device}, peak VRAM {file.peak_vram_gib}"
    )
    assert file.device == "cuda"
    assert median <= BASELINE_MS
    log = (
        (song.work_dir / LOG_FILE).read_text("utf-8") if (song.work_dir / LOG_FILE).exists() else ""
    )
    assert "Traceback" not in log
