"""Stage 1: Ctrl-C during a batch, the live lines, and the options of ``make`` for them."""

import signal
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from vocatron.cli import app as app_module
from vocatron.cli.app import app
from vocatron.cli.commands import Edges
from vocatron.cli.console import batch_text, song_text
from vocatron.cli.interrupt import FIRST_NOTICE, stop_on_interrupt
from vocatron.stages.batch import StopFlag
from vocatron.stages.progress import View


def view(stage: str | None = "separation", fraction: float = 0.414) -> View:
    return View(
        index=2,
        total=5,
        finished=1,
        percent=23,
        elapsed=250.0,
        left=830.0,
        song="Artist - Title",
        stage=stage,
        fraction=fraction,
        song_left=200.0,
    )


def test_the_first_ctrl_c_asks_for_a_stop_and_the_second_one_gets_through() -> None:
    stop = StopFlag()
    printed = StringIO()
    before = signal.getsignal(signal.SIGINT)
    with stop_on_interrupt(stop, Console(file=printed)):
        signal.raise_signal(signal.SIGINT)
        assert stop.requested
        assert FIRST_NOTICE + "\n" in printed.getvalue()  # one line, not wrapped at 80
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGINT)
    assert signal.getsignal(signal.SIGINT) == before


def test_the_live_lines_name_the_batch_progress_and_the_stage() -> None:
    assert batch_text(view()) == "[1/5] 23%  elapsed 4m 10s  about 13m 50s left"
    assert song_text(view()) == "Artist - Title: separation 41%  about 3m 20s left"
    assert song_text(view(stage=None)) == "Artist - Title"


def test_make_has_a_log_option_and_runs_under_the_ctrl_c_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[bool, object]] = []

    def fake_run_make(path: Path, **kwargs: object) -> int:
        edges = kwargs["edges"]
        assert isinstance(edges, Edges)
        seen.append((edges.log, signal.getsignal(signal.SIGINT)))
        return 0

    monkeypatch.setattr(app_module, "run_make", fake_run_make)
    before = signal.getsignal(signal.SIGINT)
    for argv in (["make", "x.mp3", "--log"], ["make", "x.mp3"]):
        with pytest.raises(SystemExit) as stop:
            app(argv)
        assert stop.value.code == 0
    assert [log for log, _ in seen] == [True, False]
    assert all(handler != before for _, handler in seen)  # ours was installed during the run
    assert signal.getsignal(signal.SIGINT) == before


def test_render_runs_under_the_ctrl_c_handler_too(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers: list[object] = []

    def fake_run_render(path: Path, **kwargs: object) -> int:
        handlers.append(signal.getsignal(signal.SIGINT))
        return 0

    monkeypatch.setattr(app_module, "run_render", fake_run_render)
    before = signal.getsignal(signal.SIGINT)
    with pytest.raises(SystemExit):
        app(["render", "x.mp3"])
    assert handlers[0] != before
