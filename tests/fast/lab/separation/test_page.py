"""Stage 1: the static listening page (golden, placeholder clip names, no audio)."""

import json
import re

from syrupy.assertion import SnapshotAssertion

from vocatron.lab.separation.listening import CRITERIA, ListeningKey, Passage, Window, make_key
from vocatron.lab.separation.page import RAMP_MS, RESULTS_NAME, clip_path, render_page

SYSTEMS = ("system-one", "system-two", "system-three")
BUILD = "0123456789abcdef"


def key() -> ListeningKey:
    passages = [
        Passage(id=f"p{i}", song="Placeholder Song", window=Window(start=i, seconds=10))
        for i in range(1, 4)
    ]
    return make_key(passages, SYSTEMS, 4, 8)


def page(build: str = BUILD) -> str:
    made = key()
    return render_page(made.trials, made.sessions, build)


def test_the_page_is_golden(snapshot: SnapshotAssertion) -> None:
    assert page() == snapshot


def test_the_unsaved_judgements_are_kept_per_build() -> None:
    assert "'vocatron-listening-0123456789abcdef'" in page()
    assert page() != page("fedcba9876543210")


def test_the_page_names_neither_systems_nor_songs_nor_passages() -> None:
    text = page().lower()
    for secret in (
        *SYSTEMS,
        "placeholder song",
        "verse",
        "chorus",
        "p1",
        "ensemble",
        "karaoke_input",
    ):
        assert secret not in text


def data_of(text: str) -> dict[str, object]:
    found = re.search(r"const DATA = (\{.*?\});\nconst CRITERIA", text, re.S)
    assert found is not None
    return json.loads(found.group(1))


def test_every_trial_has_its_three_clips_and_session_in_the_page_data() -> None:
    made = key()
    data = data_of(page())
    trials = data["trials"]
    assert isinstance(trials, list)
    assert [t["id"] for t in trials] == [t.id for t in made.trials]
    assert data["sessions"] == made.sessions
    for item, trial in zip(trials, made.trials, strict=True):
        assert (item["a"], item["b"], item["o"], item["session"]) == (
            trial.a,
            trial.b,
            trial.original,
            trial.session,
        )
    assert clip_path("c001") == "clips/c001.flac"
    assert data["suffix"] == ".flac"


def test_the_page_has_the_original_button_the_loops_and_a_five_millisecond_ramp() -> None:
    text = page()
    assert "Original song" in text
    assert "s.loop = true" in text
    assert f"const RAMP = {float(RAMP_MS)}" in text
    assert "linearRampToValueAtTime" in text
    assert "s.start(when, p.offset)" in text  # every source starts at the same moment and offset
    assert "Better overall" in text
    assert "can't tell" in text


def test_every_criterion_has_a_selector_and_the_results_have_their_name() -> None:
    text = page()
    ids = re.findall(r'"id":"(\w+)"', text.split("const CRITERIA = ")[1].split(";")[0])
    assert tuple(ids) == CRITERIA
    assert RESULTS_NAME in text
    assert "judgements: all" in text


def test_the_page_is_one_self_contained_document() -> None:
    text = page()
    assert text.startswith("<!doctype html>")
    assert "http://" not in text
    assert "https://" not in text
    assert "<script src" not in text


def test_one_position_timer_serves_all_trials_and_a_chosen_button_survives_play() -> None:
    text = page()
    assert text.count("setInterval(") == 1  # not one per card, which piles up on every session
    assert "player.which = Number(box.dataset.which || 0)" in text
