"""Stage 1: the lyrics stage on fakes: sidecar, lookup, cleaning, status, approval, language."""

import json
from pathlib import Path

import pytest

from fakes.lyrics import ENTCHEN, ENTCHEN_CLEANED, ENTCHEN_MESSY, HAENSCHEN, VOGEL, synced_of
from fakes.songs import FakeWorld
from vocatron.core.languages import Detected
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.lyrics.origin import written_by_vocatron
from vocatron.core.lyrics.verdict import UNKNOWN_LOOKUP
from vocatron.core.lyrics.versions import Candidate
from vocatron.core.status import SongStatus
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.lyrics import approve, load_lyrics
from vocatron.stages.songs import discover
from vocatron.stages.stage import LOG_FILE, Song

MUSIC = Path("/music")
AUDIO = MUSIC / "Artist - Title.mp3"
TXT = MUSIC / "Artist - Title.txt"
LRC = MUSIC / "Artist - Title.lrc"


@pytest.fixture
def bare(world: FakeWorld) -> FakeWorld:
    """A song without any lyrics file."""
    world.add_song(AUDIO, lyrics=None)
    return world


def song_of(world: FakeWorld, config: Config | None = None) -> Song:
    return world.song(AUDIO, config)


def run(world: FakeWorld, config: Config | None = None, *, force: bool = False) -> SongStatus:
    cfg = config or Config()
    return run_song(song_of(world, cfg), cfg, world.engines, force=force)


def lyrics_of(world: FakeWorld) -> LyricsFile:
    file = load_lyrics(song_of(world), world.engines)
    assert file is not None
    return file


def record(record_id: int, text: str | None = ENTCHEN, **more: object) -> Candidate:
    fields: dict[str, object] = {
        "source_id": record_id,
        "artist": "Artist",
        "title": "Title",
        "duration": 180.0,
        "plain": text,
    }
    return Candidate.model_validate(fields | more)


def written(world: FakeWorld, path: Path) -> str | None:
    """Return the lyrics Vocatron wrote at ``path`` without its mark (``None`` without a file)."""
    text = world.store.read_text(path)
    if text is None:
        return None
    kind = "lrc" if path.suffix == ".lrc" else "txt"
    assert written_by_vocatron(text, kind)
    rows = text.splitlines(keepends=True)
    return "".join(rows[1:] if kind == "lrc" else rows[3:])  # a .txt: the block of the mark


def written_into_the_input_folder(world: FakeWorld) -> set[str]:
    return {p.name for p in world.store.writes if MUSIC / "karaoke" not in p.parents}


def test_a_sidecar_txt_is_used_and_the_lookup_never_asked(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN)
    status = run(world)
    assert status.state == "ok"
    assert world.lyrics.calls == []
    file = lyrics_of(world)
    assert (file.source, file.sidecar, file.status, file.language) == (
        "sidecar",
        "Artist - Title.txt",
        "ok",
        "de",
    )
    assert [line.text for line in file.lines] == ENTCHEN.splitlines()
    assert {line.singers for line in file.lines} == {"1"}
    assert file.original == ENTCHEN
    assert written_into_the_input_folder(world) == set()


def test_a_sidecar_lrc_beats_a_txt(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=HAENSCHEN)
    world.store.add(LRC, synced_of(ENTCHEN).encode())
    run(world)
    file = lyrics_of(world)
    assert file.sidecar == "Artist - Title.lrc"
    assert [line.text for line in file.lines] == ENTCHEN.splitlines()
    assert file.lines[0].time == 5.0


def test_a_lookup_writes_txt_next_to_the_audio_and_nothing_else(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1), record(2)]
    status = run(bare)
    assert status.state == "ok"
    assert bare.lyrics.calls == [("Artist", "Title", 180.0)]
    assert written(bare, TXT) == ENTCHEN
    assert written_into_the_input_folder(bare) == {"Artist - Title.txt"}
    file = lyrics_of(bare)
    assert (file.source, file.versions_considered, file.versions_agreeing) == ("lookup", 2, 2)
    assert file.written_hash == file.sidecar_hash


def test_a_lookup_with_synced_lyrics_that_fit_writes_lrc(bare: FakeWorld) -> None:
    synced = synced_of(ENTCHEN)
    bare.lyrics.records = [record(1, synced=synced), record(2)]
    assert run(bare).state == "ok"
    assert bare.store.read_text(TXT) is None
    text = written(bare, LRC)
    assert text is not None
    assert text.startswith(
        "[ar: Artist]\n[ti: Title]\n[length: 03:00]\n[00:05.00] Alle meine Entchen"
    )
    assert written_into_the_input_folder(bare) == {"Artist - Title.lrc"}
    assert lyrics_of(bare).lines[1].time == 9.0


def test_synced_lyrics_of_the_wrong_length_give_txt(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1, synced=synced_of(ENTCHEN), duration=200.0), record(2)]
    run(bare)
    assert bare.store.read_text(TXT) is not None
    assert bare.store.read_text(LRC) is None


def test_synced_only_lyrics_of_the_wrong_length_give_their_words_as_txt(bare: FakeWorld) -> None:
    synced = synced_of(ENTCHEN)
    bare.lyrics.records = [record(number, None, synced=synced, duration=200.0) for number in (1, 2)]
    assert run(bare).state == "ok"
    assert written(bare, TXT) == ENTCHEN
    assert bare.store.read_text(LRC) is None
    file = lyrics_of(bare)
    assert (file.original, file.lines[0].time, file.lrc_fits) == (synced, None, None)


def test_found_text_that_starts_like_a_singer_header_is_not_one(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1, "---\n" + ENTCHEN), record(2)]
    assert run(bare).state == "ok"
    assert written(bare, TXT) == ENTCHEN  # the separator is not written
    assert run(bare, force=True).state == "ok"  # so the file reads back


def test_the_second_run_reads_the_file_it_wrote_and_keeps_the_findings(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1)]
    first = run(bare)
    assert first.state == "review"
    assert first.reasons == ["lyrics: single source: no second version of the lyrics agrees"]
    bare.lyrics.calls.clear()
    second = run(bare, force=True)
    assert bare.lyrics.calls == []  # the file next to the audio is the lyrics now
    assert second.reasons == first.reasons
    file = lyrics_of(bare)
    assert (file.source, file.versions_considered, file.approved) == ("lookup", 1, False)


def test_the_found_text_is_cleaned_before_it_is_written(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1, ENTCHEN_MESSY), record(2, ENTCHEN_MESSY)]
    status = run(bare)
    cleaned = "\n\n".join(["\n".join(ENTCHEN_CLEANED[:2]), "\n".join(ENTCHEN_CLEANED[2:])])
    assert written(bare, TXT) == cleaned + "\n"
    assert status.state == "review"
    assert any("section markers removed" in reason for reason in status.reasons)


@pytest.mark.parametrize(
    ("records", "reason"),
    [
        ([record(1, artist="Somebody Else"), record(2, artist="Somebody Else")], None),
        ([record(1, title="Titles"), record(2, title="Titles")], "unsure match"),
    ],
)
def test_records_of_other_songs_are_dropped_and_close_ones_need_review(
    bare: FakeWorld, records: list[Candidate], reason: str | None
) -> None:
    bare.lyrics.records = records
    status = run(bare)
    if reason is None:
        assert status.state == "failed"
        assert status.error is not None
        assert status.error.kind == "no-lyrics"
    else:
        assert status.state == "review"
        assert reason in status.reasons[0]


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("empty", "no lyrics found: put Artist - Title.txt or Artist - Title.lrc next to"),
        ("error", "lookup failed, try again later: connection refused"),
        ("off", "lookup is off"),
    ],
)
def test_no_lyrics_fails_the_song_with_a_hint(bare: FakeWorld, setup: str, message: str) -> None:
    config = Config(lyrics=LyricsSettings(lookup=setup != "off"))
    if setup == "error":
        bare.lyrics.error = "connection refused"
    status = run(bare, config)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("lyrics", "no-lyrics")
    assert message in status.error.message
    assert (bare.lyrics.calls == []) is (setup == "off")
    assert written_into_the_input_folder(bare) == set()


def test_a_sidecar_with_only_junk_is_missing(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics="[Chorus]\n(2x)\n")
    status = run(world)
    assert status.error is not None
    assert status.error.kind == "no-lyrics"


def test_a_sidecar_with_junk_is_review_until_edited(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    status = run(world)
    assert status.state == "review"
    assert [r.split(" (")[0] for r in status.reasons] == [
        "lyrics: section markers removed",
        "lyrics: repeat markers removed",
        "lyrics: credits removed",
    ]
    file = lyrics_of(world)
    assert file.original == ENTCHEN_MESSY
    assert [r.line for r in file.removed] == [1, 3, 5, 7, 9]  # the rows of the file
    assert world.store.read_text(TXT) == ENTCHEN_MESSY  # the fan's file is never changed


def test_an_edited_sidecar_counts_as_approved_and_reruns_the_stage(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    assert run(world).state == "review"
    world.store.add(TXT, (ENTCHEN_MESSY + "\n[Outro]\n").encode())
    status = run(world)
    assert status.state == "ok"
    assert status.stages[1].action == "ran"
    file = lyrics_of(world)
    assert file.approved
    assert file.status == "ok"
    assert file.reasons == []
    assert len(file.findings) == 3  # what was found stays on record
    assert len(file.removed) == 6


def test_an_unchanged_sidecar_is_skipped_and_stays_review(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    run(world)
    status = run(world)
    assert status.stages[-1].action == "skipped"
    assert status.state == "review"


def test_a_sidecar_that_cannot_be_read_as_text_fails(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(TXT, b"\xff\xfe not utf-8")
    status = run(world)
    assert status.error is not None
    assert status.error.kind == "unreadable-lyrics"
    assert "Artist - Title.txt" in status.error.message


def test_an_invalid_singer_header_fails_with_the_file_name(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics="---\nsingers:\n  1: Anna\n" + ENTCHEN)
    status = run(world)
    assert status.error is not None
    assert status.error.kind == "invalid-lyrics"
    assert status.error.message.startswith("Artist - Title.txt: ")


def test_singers_names_and_colours_are_stored(world: FakeWorld) -> None:
    text = (
        '---\nsingers:\n  1: {name: Anna, colour: "#e0b000"}\n  2: Ben\n---\n'
        "{1} Hänschen klein\n{2} ging allein\nin die weite {all} Welt\n{all} hinein\n"
    )
    world.add_song(AUDIO, lyrics=text)
    assert run(world).state == "ok"
    file = lyrics_of(world)
    assert [line.singers for line in file.lines] == ["1", "2", "2", "all"]
    assert [[(t.word, t.singers) for t in line.turns] for line in file.lines] == [
        [], [], [(3, "all")], [],
    ]  # fmt: skip
    assert file.singers[1].name == "Anna"
    assert file.singers[1].colour == "#e0b000"
    assert json.loads(world.store.read_text(song_of(world).work_dir / "lyrics.json") or "")[
        "singers"
    ]["2"] == {"name": "Ben", "colour": None}


def test_a_duet_without_singer_marks_needs_review(world: FakeWorld) -> None:
    duet = MUSIC / "Anna & Ben - Hänschen klein (Duett).mp3"
    world.add_song(duet, lyrics=HAENSCHEN)
    (song,) = discover(duet, Config(), world.engines)
    status = run_song(song, Config(), world.engines, force=False)
    assert status.reasons == ["lyrics: duet without singer marks"]
    world.store.add(duet.with_suffix(".txt"), ("1: " + HAENSCHEN).encode())
    run_song(song, Config(), world.engines, force=False)
    file = load_lyrics(song, world.engines)
    assert file is not None
    assert file.findings == ["duet without singer marks"]  # an old prefix is lyrics
    world.store.add(duet.with_suffix(".txt"), ("{1} " + HAENSCHEN).encode())
    assert run_song(song, Config(), world.engines, force=False).state == "ok"


def test_marks_never_reach_the_text_of_the_lyrics_file(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics="{2} Hänschen {1} klein\n{all}\nging {3,1} allein\n")
    assert run(world).state == "ok"
    file = lyrics_of(world)
    assert [line.text for line in file.lines] == ["Hänschen klein", "ging allein"]
    assert "{" not in "".join(line.text for line in file.lines)
    assert [(line.singers, [(t.word, t.singers) for t in line.turns]) for line in file.lines] == [
        ("2", [(1, "1")]),
        ("all", [(1, "1,3")]),
    ]
    assert file.schema_version == 5


def test_the_duet_pattern_is_a_setting(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=HAENSCHEN)
    status = run(world, Config(lyrics=LyricsSettings(duet_pattern="Title")))
    assert status.reasons == ["lyrics: duet without singer marks"]


@pytest.mark.parametrize(
    ("detected", "kind", "message"),
    [
        (
            Detected("fr", "French"),
            "unsupported-language",
            "French (fr), which Vocatron does not support",
        ),
        (None, "unknown-language", "cannot tell the language"),
    ],
)
def test_an_unsupported_or_unknown_language_fails_the_song(
    world: FakeWorld, detected: Detected | None, kind: str, message: str
) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN)
    world.language.language = detected
    status = run(world)
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("lyrics", kind)
    assert message in status.error.message


def test_the_language_is_detected_from_the_cleaned_lyrics(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    run(world)
    assert world.language.texts == ["\n".join(ENTCHEN_CLEANED)]


def test_an_lrc_that_does_not_fit_the_recording_needs_review(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(LRC, ("[length: 05:00]\n" + synced_of(ENTCHEN)).encode())
    status = run(world)
    assert status.reasons == ["lyrics: the .lrc does not fit the recording"]
    assert lyrics_of(world).lrc_fits is False


def test_an_lrc_that_fits_is_ok(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    world.store.add(LRC, ("[length: 03:01]\n" + synced_of(ENTCHEN)).encode())
    assert run(world).state == "ok"
    assert lyrics_of(world).lrc_fits is True


def test_approve_records_an_unchanged_file_as_approved(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    run(world)
    song = song_of(world)
    assert approve(song, world.engines) is None
    approved = lyrics_of(world)
    assert (approved.approved, approved.status, approved.reasons) == (True, "ok", [])
    status = run(world)
    assert status.state == "ok"
    actions = {o.stage: o.action for o in status.stages}
    assert (actions["lyrics"], actions["separation"]) == ("skipped", "skipped")
    assert actions["alignment"] == "ran"  # its input, lyrics.json, changed with the approval
    assert lyrics_of(world).findings  # the findings stay on record


def test_approve_keeps_the_approval_when_the_stage_runs_again(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    run(world)
    approve(song_of(world), world.engines)
    assert run(world, force=True).state == "ok"


def test_approve_refuses_without_a_run_without_a_file_and_after_an_edit(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    song = song_of(world)
    assert approve(song, world.engines) == (
        "there is no lyrics.json yet; run 'vocatron lyrics' on the song first"
    )
    run(world)
    world.store.add(TXT, VOGEL.encode())
    refusal = approve(song, world.engines)
    assert refusal is not None
    assert "changed since the last run" in refusal
    del world.store.files[TXT]
    assert approve(song, world.engines) == "Artist - Title.txt is not next to the song any more"


def test_load_lyrics_ignores_a_broken_file(world: FakeWorld) -> None:
    world.add_song(AUDIO)
    song = song_of(world)
    assert load_lyrics(song, world.engines) is None
    world.store.add(song.work_dir / "lyrics.json", b"{broken")
    assert load_lyrics(song, world.engines) is None


def test_a_language_setting_skips_the_detection(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN)
    world.language.language = None  # detection would fail
    status = run(world, Config(lyrics=LyricsSettings(language="de")))
    assert status.state == "ok"
    assert world.language.texts == []
    assert lyrics_of(world).language == "de"


def test_a_changed_language_setting_runs_the_stage_again(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN)
    run(world)
    status = run(world, Config(lyrics=LyricsSettings(language="de")))
    # lyrics.json carries its fingerprint, so the stages that read it run again too
    assert [o.action for o in status.stages] == ["skipped", "ran", "skipped", "skipped"] + [
        "ran"
    ] * 5
    again = run(world, Config(lyrics=LyricsSettings(language="de")))
    assert [o.action for o in again.stages] == ["skipped"] * 9


def test_an_unsupported_language_setting_is_invalid() -> None:
    with pytest.raises(
        ValueError,
        match="language 'fr' is not supported; supported: de \\(German\\), en \\(English\\)",
    ):
        LyricsSettings(language="fr")


def elsewhere() -> Config:
    """A configuration with a new output folder: a work folder that remembers nothing."""
    return Config.model_validate({"output": {"folder": "/elsewhere"}})


@pytest.mark.parametrize("synced", [False, True])
def test_a_file_vocatron_wrote_stays_its_own_in_a_new_work_folder(
    bare: FakeWorld, synced: bool
) -> None:
    more = {"synced": synced_of(ENTCHEN)} if synced else {}
    bare.lyrics.records = [record(1, **more)]
    assert run(bare).state == "review"  # a single source
    bare.lyrics.calls.clear()
    status = run(bare, elsewhere())
    assert bare.lyrics.calls == []
    assert status.state == "review"
    file = load_lyrics(song_of(bare, elsewhere()), bare.engines)
    assert file is not None
    assert (file.source, file.approved) == ("lookup", False)
    assert file.written_hash == file.sidecar_hash
    assert file.reasons == [UNKNOWN_LOOKUP]


def test_an_edit_of_a_file_vocatron_wrote_makes_it_the_fans_in_a_new_work_folder(
    bare: FakeWorld,
) -> None:
    bare.lyrics.records = [record(1)]
    run(bare)
    text = bare.store.read_text(TXT)
    assert text is not None
    bare.store.add(TXT, text.replace("Entchen", "Entlein", 1).encode())
    assert run(bare, elsewhere()).state == "ok"
    file = load_lyrics(song_of(bare, elsewhere()), bare.engines)
    assert file is not None
    assert (file.source, file.written_hash) == ("sidecar", None)


def test_a_file_vocatron_wrote_stays_its_own_in_a_work_folder_that_knew_another_file(
    bare: FakeWorld,
) -> None:
    bare.store.add(TXT, HAENSCHEN.encode())  # the fan's file, met by the other work folder
    assert run(bare, elsewhere()).state == "ok"
    bare.store.delete(TXT)
    bare.lyrics.records = [record(1)]
    run(bare)  # looked up again and written with the mark
    status = run(bare, elsewhere())
    assert status.state == "review"
    file = load_lyrics(song_of(bare, elsewhere()), bare.engines)
    assert file is not None
    assert (file.source, file.approved, file.reasons) == ("lookup", False, [UNKNOWN_LOOKUP])
    assert file.written_hash == file.sidecar_hash


def test_approving_a_file_vocatron_wrote_in_a_new_work_folder_lasts(bare: FakeWorld) -> None:
    bare.lyrics.records = [record(1)]
    run(bare)
    assert run(bare, elsewhere()).state == "review"
    assert approve(song_of(bare, elsewhere()), bare.engines) is None
    assert run(bare, elsewhere(), force=True).state == "ok"
    file = load_lyrics(song_of(bare, elsewhere()), bare.engines)
    assert file is not None
    assert (file.source, file.approved, file.findings) == ("lookup", True, [UNKNOWN_LOOKUP])


SQRT = "√"


def test_a_symbol_the_font_lacks_is_dropped_and_the_song_needs_review(world: FakeWorld) -> None:
    lines = ENTCHEN.splitlines()
    sidecar = "\n".join([*lines[:2], f"{lines[2]} {SQRT}", *lines[3:]]) + "\n"
    world.add_song(AUDIO, lyrics=sidecar)
    status = run(world)
    assert status.state == "review"
    assert status.reasons == ["lyrics: line 3: dropped U+221A SQUARE ROOT (not in the font)"]
    file = lyrics_of(world)
    assert [line.text for line in file.lines] == lines
    assert file.original == sidecar  # the original text stays in the stage file
    assert [(r.line, r.kind, r.character) for r in file.removed] == [(3, "glyph", 0x221A)]


def test_a_letter_the_font_lacks_fails_the_lyrics_stage_before_the_slow_stages(
    world: FakeWorld,
) -> None:
    lines = ENTCHEN.splitlines()
    world.add_song(AUDIO, lyrics="\n".join([*lines[:3], f"{lines[3]} ก", *lines[4:]]))
    status = run(world)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("lyrics", "undrawable-character")
    assert status.error.message == (
        "line 4: U+0E01 THAI CHARACTER KO KAI is a letter the bundled font cannot draw"
    )
    assert world.separator.requests == []  # before the slow stages


def test_an_approval_recorded_in_a_lyrics_file_of_version_2_survives_the_new_stage_version(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=ENTCHEN_MESSY)
    run(world)
    song = song_of(world)
    approve(song, world.engines)
    path = song.work_dir / "lyrics.json"
    old = json.loads(world.store.read_text(path) or "")
    old["schema_version"] = 2
    old["fingerprint"]["stage_version"] = 2  # made by the lyrics stage before ADR-0046
    for removal in old["removed"]:
        del removal["character"]
    world.store.write_text(path, json.dumps(old))
    status = run(world)
    assert {o.stage: o.action for o in status.stages}["lyrics"] == "ran"
    assert (status.state, lyrics_of(world).approved, lyrics_of(world).schema_version) == (
        "ok",
        True,
        5,
    )


def test_the_later_line_of_one_time_and_a_marked_line_are_the_second_voice(
    world: FakeWorld,
) -> None:
    world.add_song(AUDIO, lyrics=None)
    synced = (
        "[00:01.00] Alle meine Entchen\n[00:05.00] schwimmen auf dem See\n"
        "[00:05.00] Köpfchen in das Wasser\n[00:09.00] {&} Schwänzchen in die Höh\n"
    )
    world.store.add(LRC, synced.encode())
    status = run_song(
        song_of(world), Config(), world.engines, force=False, only=("probe", "lyrics")
    )
    assert status.state == "ok"  # two lines with one time are no reason for review
    assert [line.voice for line in lyrics_of(world).lines] == [1, 1, 2, 2]
    log = world.store.log_lines(song_of(world).work_dir / LOG_FILE)
    assert "lyrics: line 3 has the time of line 2: second voice" in "\n".join(log)


def test_a_line_remembers_whether_it_has_a_singer_mark_of_its_own(world: FakeWorld) -> None:
    world.add_song(AUDIO, lyrics=None)
    synced = (
        "[00:01.00] Alle meine Entchen\n[00:01.00] {&} schwimmen auf dem See\n"
        "[00:05.00] {&} {3} Köpfchen in das Wasser\n[00:09.00] {2} Schwänzchen in die Höh\n"
        "[00:12.00] {&} Alle meine {2} Entchen\n"
    )
    world.store.add(LRC, synced.encode())
    run_song(song_of(world), Config(), world.engines, force=False, only=("probe", "lyrics"))
    lines = lyrics_of(world).lines
    assert [(line.voice, line.own_mark) for line in lines] == [
        (1, False),
        (2, False),
        (2, True),
        (1, True),
        (2, False),  # a mark in the middle changes the colour from that word on
    ]
    assert "own_mark" not in lines[0].model_dump_json()  # not written for a line without a mark
