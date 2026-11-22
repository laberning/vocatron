"""Stage 1: the real system probe, with subprocess, PATH and PyTorch replaced."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from fakes.system import GOOD_FFMPEG
from vocatron.engines import system
from vocatron.engines.system import LocalSystemProbe


def not_installed(name: str) -> None:
    del name


def fake_path(name: str) -> str:
    return f"/fake/{name}"


def test_without_ffmpeg_on_path_the_probe_answers_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", not_installed)
    probe = LocalSystemProbe()
    assert probe.ffmpeg_version() is None
    assert probe.ffmpeg_encoders() is None


def test_the_probe_returns_stdout_and_passes_the_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(stdout=GOOD_FFMPEG)

    monkeypatch.setattr("shutil.which", fake_path)
    monkeypatch.setattr("subprocess.run", run)
    probe = LocalSystemProbe()
    assert probe.ffmpeg_version() == GOOD_FFMPEG
    assert probe.ffmpeg_encoders() == GOOD_FFMPEG
    assert calls == [["/fake/ffmpeg", "-version"], ["/fake/ffmpeg", "-hide_banner", "-encoders"]]


def test_a_broken_binary_answers_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr("shutil.which", fake_path)
    monkeypatch.setattr("subprocess.run", fail)
    assert system.run_ffmpeg("-version") is None


def fake_torch(*, cuda: bool) -> SimpleNamespace:
    """A stand-in for the ``torch`` module with the few names the probe reads."""

    def device_name(index: int) -> str:
        del index
        return "Fake GPU"

    def properties(index: int) -> SimpleNamespace:
        del index
        return SimpleNamespace(total_memory=8 << 30)

    return SimpleNamespace(
        __version__="2.14.1+fake",
        version=SimpleNamespace(cuda="13.0" if cuda else None),
        cuda=SimpleNamespace(
            is_available=lambda: cuda, get_device_name=device_name, get_device_properties=properties
        ),
    )


def test_torch_info_reads_name_and_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", fake_torch(cuda=True))
    info = LocalSystemProbe().torch_info()
    assert info is not None
    assert (info.version, info.cuda_version, info.gpu_name, info.vram_bytes) == (
        "2.14.1+fake",
        "13.0",
        "Fake GPU",
        8 << 30,
    )


def test_torch_info_without_a_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", fake_torch(cuda=False))
    info = LocalSystemProbe().torch_info()
    assert info is not None
    assert info.gpu_name is None
    assert info.vram_bytes is None


def test_torch_info_without_pytorch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)  # makes "import torch" raise ImportError
    assert LocalSystemProbe().torch_info() is None
