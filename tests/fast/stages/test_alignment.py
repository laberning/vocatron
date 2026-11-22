"""Stage 1: the alignment and syllables stages on a fake acoustic model."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fakes.acoustic import SECONDS_PER_FRAME
from fakes.lyrics import ENTCHEN, synced_of
from fakes.songs import FakeWorld
from vocatron.core.alignment import chunks, estimate, hold, mix, unheard, voice
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.alignment.solve import Solution
from vocatron.core.alignment.unheard import UnheardLine
from vocatron.core.alignment.voice import VoiceActivity
from vocatron.core.errors import StageError
from vocatron.core.models import find_model
from vocatron.core.separation.file import stem_path
from vocatron.core.status import SongStatus
from vocatron.core.syllables import SyllablesFile
from vocatron.stages import alignment as alignment_stage
from vocatron.stages.alignment import AlignmentStage, VoiceParameters, load_alignment
from vocatron.stages.config import AlignmentSettings, Config
from vocatron.stages.stage import LOG_FILE

MUSIC = Path("/music")
AUDIO = MUSIC / "Artist - Title.mp3"
LRC = MUSIC / "Artist - Title.lrc"
WORK = MUSIC / "karaoke" / "Artist - Title"


def run(world: FakeWorld, config: Config | None = None, *, force: bool = False) -> SongStatus:
    return world.run(AUDIO, config, force=force)


def alignment_of(world: FakeWorld) -> AlignmentFile:
    text = world.store.read_text(WORK / "alignment.json")
    assert text is not None
    return AlignmentFile.model_validate_json(text)


def with_lrc(world: FakeWorld, text: str = ENTCHEN) -> FakeWorld:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(LRC, ("[length: 03:01]\n" + synced_of(text)).encode())
    return world


def with_alignment(**settings: object) -> Config:
    return Config(alignment=AlignmentSettings.model_validate(settings))


def test_every_word_gets_its_start_end_and_confidence(one: FakeWorld) -> None:
    status = run(one)
    assert status.state == "ok"
    file = alignment_of(one)
    transcript = one.acoustic.transcript
    assert transcript is not None
    assert [w.text for w in file.words] == [w.text for w in transcript.words]
    for word, slot in zip(file.words, transcript.slots, strict=True):
        assert slot is not None
        first = one.acoustic.last[slot[0]] * SECONDS_PER_FRAME
        last = (one.acoustic.last[slot[1]] + 1) * SECONDS_PER_FRAME
        assert (word.start, word.letters[-1][1]) == pytest.approx((first, last))
        assert word.end >= word.heard_end  # held to the end of the voice (ADR-0013)
        assert word.confidence > 0.8
        assert not word.estimated
        assert len(word.letters) == len(word.spoken)
    assert file.rails.kind == "none"
    assert (file.language, file.model, file.device) == ("de", "wav2vec2-de", "cpu")
    assert file.revision == find_model("wav2vec2-de").revision
    assert [(line.first_word, line.word_count) for line in file.lines] == [
        (0, 3), (3, 4), (7, 4), (11, 4), (15, 4)
    ]  # fmt: skip
    assert file.lines[0].start == file.words[0].start
    assert file.lines[0].end == file.words[2].end
    assert file.quality.estimated == 0
    assert file.reasons == []


def test_the_acoustic_model_gets_the_lead_stem_the_pinned_model_and_the_limits(
    one: FakeWorld,
) -> None:
    run(one)
    (request,) = one.acoustic.requests
    assert request.audio == WORK / stem_path("lead")
    assert request.model.name == "wav2vec2-de"
    assert request.model.folder.endswith(".cache/models/wav2vec2-de")
    assert (request.model.precision, request.piece_seconds, request.overlap_seconds) == (
        "fp16", 30.0, 2.0,
    )  # fmt: skip
    assert (request.device, request.timeout_factor_gpu, request.timeout_factor_cpu) == (
        "auto", 1.0, 15.0,
    )  # fmt: skip
    assert (request.duration, request.log_path) == (180.0, WORK / LOG_FILE)


def test_the_stage_declares_the_model_of_the_language_and_downloads_it_on_first_use(
    one: FakeWorld,
) -> None:
    assert AlignmentStage().required_models(one.context(AUDIO), Config()) == ("wav2vec2-de",)
    run(one)
    names = {destination.parent.name for _, destination in one.downloader.calls}
    assert "wav2vec2-de" in names


def test_a_second_run_skips_both_stages_and_a_change_of_the_lyrics_runs_them_again(
    one: FakeWorld,
) -> None:
    run(one)
    status = run(one)
    assert [(o.stage, o.action) for o in status.stages][-5:] == [
        ("alignment", "skipped"),
        ("syllables", "skipped"),
        ("layout", "skipped"),
        ("render", "skipped"),
        ("cdg", "skipped"),
    ]
    assert len(one.acoustic.requests) == 1
    one.store.add(AUDIO.with_suffix(".txt"), b"Ein anderes Lied\nvon der Welt\n")
    again = run(one)
    assert [(o.stage, o.action) for o in again.stages][-5:] == [
        ("alignment", "ran"),
        ("syllables", "ran"),
        ("layout", "ran"),
        ("render", "ran"),
        ("cdg", "ran"),
    ]
    assert len(one.acoustic.requests) == 2


def test_the_file_says_whether_the_voice_was_used_and_what_it_moved(one: FakeWorld) -> None:
    run(one)
    voice = alignment_of(one).voice
    assert (voice.used, voice.reason, voice.placed, voice.re_estimated) == (True, "used", 0, 0)
    assert (voice.kept, voice.unheard) == (0, 0)
    assert voice.held > 0
    assert -70.0 < voice.threshold_db < -20.0
    assert 0.1 < voice.voiced_share < 0.95
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert "alignment: voice activity used: 0 estimated words placed on the voice" in log
    assert "word ends held to the end of the voice" in log


def test_the_file_and_the_log_report_each_count_of_the_voice_in_its_own_place(
    one: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = alignment_stage.solve

    def counted(*args: Any, **kwargs: Any) -> Solution:
        found = real(*args, **kwargs)
        return replace(
            found, voice=replace(found.voice, placed=1, kept=2, re_estimated=3, unheard=4)
        )

    monkeypatch.setattr(alignment_stage, "solve", counted)
    run(one)
    voice = alignment_of(one).voice
    assert (voice.placed, voice.kept, voice.re_estimated, voice.unheard) == (1, 2, 3, 4)
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert (
        "1 estimated words placed on the voice, 2 unsure words kept at the model's position, "
        "3 measured words in silence estimated instead, 4 unheard lines placed at their line time"
    ) in log


def test_a_song_without_loudness_falls_back_and_the_log_says_why(one: FakeWorld) -> None:
    one.acoustic.loudness = False
    run(one)
    voice = alignment_of(one).voice
    assert (voice.used, voice.reason, voice.threshold_db) == (False, "no loudness", 0.0)
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert "alignment: voice activity not used (no loudness)" in log


def test_voice_activity_off_gives_the_words_lines_and_report_of_before_and_reruns(
    one: FakeWorld,
) -> None:
    run(one)
    on = alignment_of(one)
    status = run(one, with_alignment(voice_activity=False))
    off = alignment_of(one)
    assert [o.action for o in status.stages][-4:] == ["ran"] * 4
    assert (off.voice.used, off.voice.reason) == (False, "switched off")
    assert [(w.start, w.letters, w.estimated) for w in off.words] == [
        (w.start, w.letters, w.estimated) for w in on.words
    ]
    assert [w.end for w in off.words] == [w.heard_end for w in off.words]  # nothing held
    assert [line.start for line in off.lines] == [line.start for line in on.lines]
    assert (off.voice.held, off.voice.held_median) == (0, 0.0)
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert "alignment: voice activity is switched off" in log


def vocals() -> Config:
    return with_alignment(voice_source="vocals")


def lead() -> Config:
    return with_alignment(voice_source="lead", hear_backing=False)


def test_the_default_voice_source_is_lead_and_backing_together() -> None:
    # chosen on the benchmark and the demo song, where shouted words sit in the backing stem
    assert Config().alignment.voice_source == "vocals"


def test_the_lead_source_does_not_hand_over_the_backing_stem_and_ignores_it(
    one: FakeWorld,
) -> None:
    one.acoustic.backing_words = frozenset({1})
    run(one, lead())
    (request,) = one.acoustic.requests
    assert request.backing is None
    assert alignment_of(one).voice.used


def test_the_vocals_source_hands_over_the_backing_stem_and_a_backing_only_word_is_voiced(
    one: FakeWorld,
) -> None:
    one.acoustic.backing_words = frozenset({1, 2})
    run(one, lead())
    lead_share = alignment_of(one).voice.voiced_share
    status = run(one, vocals())
    assert status.state == "ok"
    (_, request) = one.acoustic.requests
    assert request.backing == WORK / stem_path("backing")
    assert request.audio == WORK / stem_path("lead")  # the model still hears the lead alone
    assert alignment_of(one).voice.voiced_share > lead_share


def test_the_voice_source_reruns_the_alignment_and_it_is_in_the_fingerprint(
    one: FakeWorld,
) -> None:
    run(one, lead())
    status = run(one, vocals())
    assert [o.action for o in status.stages][-4:] == ["ran"] * 4
    assert [o.action for o in run(one, vocals()).stages][-4:] == ["skipped"] * 4
    assert [o.action for o in run(one, lead()).stages][-4:] == ["ran"] * 4


def test_the_backing_is_handed_over_and_heard_by_default_and_only_added_for_the_loudness_on_request(
    one: FakeWorld,
) -> None:
    run(one, with_alignment(voice_source="lead"))
    run(one, with_alignment(voice_source="vocals", hear_backing=False))
    run(one, with_alignment(voice_source="lead", hear_backing=False))
    run(one)
    first, second, third, fourth = one.acoustic.requests
    backing = WORK / stem_path("backing")
    assert (first.backing, first.sum_backing, first.hear_backing) == (backing, False, True)
    assert (second.backing, second.sum_backing, second.hear_backing) == (backing, True, False)
    assert (third.backing, third.hear_backing) == (None, False)
    assert (fourth.backing, fourth.sum_backing, fourth.hear_backing) == (backing, True, True)


def test_a_word_only_the_backing_sings_is_measured_and_the_file_and_log_say_so(
    one: FakeWorld,
) -> None:
    one.acoustic.backing_only = frozenset({1})
    run(one, with_alignment(hear_backing=False))
    off = alignment_of(one)
    assert off.words[1].estimated
    assert (off.backing.used, off.backing.reason, off.backing.frames) == (False, "switched off", 0)
    status = run(one)
    assert status.state == "ok"
    file = alignment_of(one)
    assert not file.words[1].estimated
    assert file.words[1].letters
    assert file.quality.estimated < off.quality.estimated
    assert (file.backing.used, file.backing.reason, file.backing.words) == (True, "used", 1)
    assert file.backing.frames > 0
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert f"alignment: backing vocals heard in {file.backing.frames} frames" in log


def test_a_song_without_words_in_the_backing_gives_the_same_words_with_the_setting_on_and_off(
    one: FakeWorld,
) -> None:
    run(one, with_alignment(hear_backing=False))
    off = alignment_of(one)
    run(one)
    on = alignment_of(one)
    assert (on.words, on.lines, on.quality, on.voice) == (
        off.words,
        off.lines,
        off.quality,
        off.voice,
    )
    assert (on.backing.used, on.backing.reason) == (False, "no backing frames")
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert "alignment: backing vocals not heard (no backing frames)" in log


def test_hear_backing_reruns_the_alignment_and_is_in_the_fingerprint(one: FakeWorld) -> None:
    run(one)
    again = run(one, with_alignment(hear_backing=False))
    assert [o.action for o in again.stages][-4:] == ["ran"] * 4
    assert [o.action for o in run(one).stages][-4:] == ["ran"] * 4


def test_every_number_of_the_voice_is_in_the_fingerprint() -> None:
    """A new constant in ``voice``, ``estimate``, ``hold``, ``mix`` or ``unheard`` is pinned."""
    elsewhere = {"MIN_CONFIDENCE", "LETTER_SECONDS"}  # pinned on their own in ``Pinned``
    numbers = {
        name.lower(): value
        for module in (voice, estimate, hold, mix, unheard)
        for name, value in vars(module).items()
        if name.isupper() and isinstance(value, float) and name not in elsewhere
    }
    numbers["silence_db"] = chunks.SILENCE_DB
    assert VoiceParameters().model_dump() == numbers


def test_use_lrc_times_reruns_the_alignment_but_device_and_timeouts_do_not(
    one: FakeWorld,
) -> None:
    run(one)
    for settings in ({"device": "cpu"}, {"timeout_factor_gpu": 4.0}, {"timeout_factor_cpu": 9.0}):
        status = run(one, with_alignment(**settings))
        assert status.stages[-4].action == "skipped", settings
    status = run(one, with_alignment(use_lrc_times=False))
    assert [o.action for o in status.stages][-4:] == ["ran"] * 4


def test_a_fitting_lrc_is_corrected_by_its_offset_and_used_as_guide_rails(
    world: FakeWorld,
) -> None:
    with_lrc(world)
    world.acoustic.shift = 0.6
    status = run(world)
    file = alignment_of(world)
    assert status.state == "ok"
    assert file.rails.kind == "shifted"
    assert file.rails.offset == pytest.approx(0.6, abs=0.05)
    assert file.rails.compared == 5
    assert [round(line.start, 1) for line in file.lines] == [5.6, 9.6, 13.6, 17.6, 21.6]
    assert file.voice.used  # the voice is found in both passes and changes no measured word


def test_an_lrc_that_does_not_fit_is_ignored_and_the_song_needs_review(world: FakeWorld) -> None:
    with_lrc(world)
    world.acoustic.jitter = {1: 3.0, 2: -2.0, 3: 6.0}
    status = run(world)
    file = alignment_of(world)
    assert file.rails.kind == "ignored"
    assert file.reasons[0] == "lyrics times do not fit"
    assert status.state == "review"
    assert status.reasons == ["alignment: lyrics times do not fit"]
    sung = [line.start for line in file.lines]
    assert sung == sorted(sung)  # the alignment still worked, without the hints


def test_an_out_of_order_tag_is_dropped_named_in_the_file_and_the_log(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    typo = synced_of(ENTCHEN).replace("[00:13.00]", "[02:23.00]")
    world.store.add(LRC, ("[length: 03:01]\n" + typo).encode())
    world.acoustic.jitter = {2: -130.0}  # sung where it always was
    status = run(world)
    file = alignment_of(world)
    assert status.state == "ok"
    assert file.rails.kind == "shifted"
    assert [(d.line, d.time) for d in file.rails.dropped] == [(3, "02:23.00")]
    assert [round(line.start, 1) for line in file.lines] == [5.0, 9.0, 13.0, 17.0, 21.0]
    log = "\n".join(world.store.log_lines(WORK / LOG_FILE))
    assert "alignment: warning: line 3: time 02:23.00 is out of order, skipped" in log


def test_with_use_lrc_times_off_the_lrc_is_not_used_and_not_judged(world: FakeWorld) -> None:
    with_lrc(world)
    world.acoustic.jitter = {1: 3.0, 2: -2.0, 3: 6.0}
    status = run(world, with_alignment(use_lrc_times=False))
    assert alignment_of(world).rails.kind == "none"
    assert status.state == "ok"


def test_a_text_without_line_times_never_uses_rails(one: FakeWorld) -> None:
    run(one)
    assert alignment_of(one).rails.compared == 0


def test_many_words_without_sound_are_estimated_and_the_song_needs_review(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics="ja — nein — doch\n– sehr gut –\n")
    status = run(world)
    file = alignment_of(world)
    assert file.quality.estimated == 4
    assert [w.estimated for w in file.words if not w.spoken] == [True] * 4
    assert status.state == "review"
    assert status.reasons[0] == "alignment: 44% of words estimated (max 10%)"


def test_lyrics_without_any_sound_fail_the_song_with_a_clear_error(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics="Привет мир\n")
    status = run(world)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("alignment", "alignment-failed")
    assert "the lyrics cannot be aligned" in status.error.message


def test_a_failing_acoustic_model_fails_only_the_alignment(one: FakeWorld) -> None:
    one.acoustic.fail_with = StageError("out-of-memory", "the GPU ran out of memory")
    status = run(one)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("alignment", "out-of-memory")
    assert [(o.stage, o.action) for o in status.stages][2:] == [
        ("separation", "ran"),
        ("tempo", "ran"),
        ("alignment", "failed"),
    ]


def test_the_syllables_stage_splits_every_word(one: FakeWorld) -> None:
    run(one)
    text = one.store.read_text(WORK / "syllables.json")
    assert text is not None
    syllables = SyllablesFile.model_validate_json(text)
    aligned = alignment_of(one)
    assert syllables.language == "de"
    assert [w.text for w in syllables.words] == [w.text for w in aligned.words]
    entchen = syllables.words[2]
    assert [s.text for s in entchen.syllables] == ["Ent", "chen"]
    assert entchen.syllables[0].start == aligned.words[2].start
    assert entchen.syllables[1].end == aligned.words[2].end
    assert entchen.syllables[0].end == entchen.syllables[1].start


def test_the_syllables_file_carries_the_voice_of_every_line(one: FakeWorld) -> None:
    run(one)
    path = WORK / "alignment.json"
    aligned = alignment_of(one)
    assert len(aligned.lines) >= 2
    lines = [
        line.model_copy(update={"voice": 2 if n == 1 else 1})
        for n, line in enumerate(aligned.lines)
    ]
    one.store.write_text(path, aligned.model_copy(update={"lines": lines}).model_dump_json())
    run(one)  # the syllables stage takes the new alignment
    text = one.store.read_text(WORK / "syllables.json")
    assert text is not None
    syllables = SyllablesFile.model_validate_json(text)
    assert syllables.voices == [2 if n == 1 else 1 for n in range(len(aligned.lines))]
    assert syllables.schema_version == 2


def test_the_syllables_depend_on_the_alignment_only(one: FakeWorld) -> None:
    run(one)
    run(one, with_alignment(use_lrc_times=False))
    status = run(one, with_alignment(use_lrc_times=False))
    assert status.stages[-1].action == "skipped"
    assert one.store.read_text(WORK / "syllables.json") is not None


def test_load_alignment_reads_the_file_and_ignores_a_broken_one(world: FakeWorld) -> None:
    with_lrc(world)
    song = world.song(AUDIO)
    assert load_alignment(song, world.engines) is None
    run(world)
    loaded = load_alignment(song, world.engines)
    assert loaded is not None
    assert loaded.rails.dropped == []
    world.store.add(WORK / "alignment.json", b"{broken")
    assert load_alignment(song, world.engines) is None


def test_the_file_names_an_unheard_line_with_little_voice_as_a_reason(
    one: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = alignment_stage.solve

    def with_unheard(*args: Any, **kwargs: Any) -> Solution:
        found = real(*args, **kwargs)
        detection = replace(found.voice.detection, activity=VoiceActivity(()))
        return replace(
            found,
            voice=replace(found.voice, detection=detection, unheard=1),
            unheard=(UnheardLine(0, 0.0, 1.0),),
        )

    monkeypatch.setattr(alignment_stage, "solve", with_unheard)
    run(one)
    assert "little voice where line 1 was placed at its time" in alignment_of(one).reasons


def test_the_file_names_a_line_split_after_weak_first_words_as_a_reason(
    one: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = alignment_stage.solve

    def with_split(*args: Any, **kwargs: Any) -> Solution:
        found = real(*args, **kwargs)
        detection = replace(found.voice.detection, activity=VoiceActivity(()))
        words: list[estimate.Timed] = []
        for index, word in enumerate(found.transcript.words):
            first = index == 0
            start = 10.0 * word.line + 0.5 * index + (0.0 if first or word.line else 3.0)
            words.append(estimate.Timed(start, start + 0.3, 0.1 if first else 0.9, False))
        return replace(found, words=words, voice=replace(found.voice, detection=detection))

    monkeypatch.setattr(alignment_stage, "solve", with_split)
    run(one)
    assert "line 1: its time looks early" in alignment_of(one).reasons


# ---------------------------------------------------------------- a second voice (ADR-0052)

TWO_VOICES = "Alle meine Entchen\n{&} schwimmen auf dem See\nKöpfchen in das Wasser\n"


def test_a_line_marked_for_the_second_voice_is_searched_on_the_backing_and_keeps_its_voice(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=TWO_VOICES)
    world.acoustic.backing_only = frozenset({3, 4, 5, 6})  # the words of the marked line
    assert run(world).state == "ok"
    file = alignment_of(world)
    assert [line.voice for line in file.lines] == [1, 2, 1]
    assert [w.line for w in file.words] == sorted(w.line for w in file.words)  # lyrics order
    marked = [w for w in file.words if w.line == 1]
    assert not any(w.estimated for w in marked)  # heard on the backing's output
    log = "\n".join(world.store.log_lines(WORK / LOG_FILE))
    assert "alignment: second voice sings 1 lines (numbers 2), 0 found in the audio" in log


def test_a_song_with_one_voice_says_so_in_the_log_and_keeps_every_voice_at_one(
    one: FakeWorld,
) -> None:
    run(one)
    assert {line.voice for line in alignment_of(one).lines} == {1}
    assert "alignment: one voice" in "\n".join(one.store.log_lines(WORK / LOG_FILE))


def test_the_second_voice_is_in_the_fingerprint_and_the_stage_numbers_are_pinned(
    one: FakeWorld,
) -> None:
    run(one)
    stored = alignment_of(one).fingerprint
    assert stored.stage_version == AlignmentStage.version
    settings = AlignmentStage().declared_settings(one.context(AUDIO), Config())
    assert settings.model_dump()["second_voice"]["backing_margin"] == pytest.approx(0.2)
