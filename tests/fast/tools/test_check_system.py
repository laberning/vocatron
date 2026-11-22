"""Stage 1 tests for ``tools/check_system.py`` on a faked system probe."""

import pytest

import check_system
from fakes.system import GOOD_FFMPEG, FakeSystemProbe


def probe(version: str | None) -> FakeSystemProbe:
    found = FakeSystemProbe()
    found.version = version
    return found


def test_main_succeeds_with_good_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_system, "LocalSystemProbe", lambda: probe(GOOD_FFMPEG))
    assert check_system.main() == 0
    assert "ok" in capsys.readouterr().out


def test_main_fails_and_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_system, "LocalSystemProbe", lambda: probe(None))
    assert check_system.main() == 1
    assert "MISSING" in capsys.readouterr().err
