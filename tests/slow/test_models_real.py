"""Stage 2: the real downloader against the real source, and ``doctor`` on this machine."""

from pathlib import Path

import pytest

from vocatron.core.models import find_model
from vocatron.engines.downloader import Urllib3Downloader
from vocatron.engines.files import LocalFileStore
from vocatron.engines.protocols import DownloadError
from vocatron.engines.system import LocalSystemProbe
from vocatron.stages.config import Config
from vocatron.stages.doctor import run_checks
from vocatron.stages.models import ModelFolder

pytestmark = pytest.mark.enable_socket


def test_the_2_kb_config_of_the_separation_model_is_downloaded_and_verified(
    tmp_path: Path,
) -> None:
    spec = find_model("bs-roformer-ep317")
    (config,) = [f for f in spec.files if f.path.endswith(".yaml")]
    destination = tmp_path / spec.name / config.path
    done: list[int] = []
    Urllib3Downloader().download(config, destination, lambda now, total: done.append(now))
    assert destination.stat().st_size == config.size
    assert done[-1] == config.size
    folder = ModelFolder(tmp_path, LocalFileStore())
    assert folder.file_state(spec, config, verify=True) == "present"
    assert folder.state(spec, verify=True) == "partial"  # the big checkpoint was not fetched


def test_a_file_with_a_wrong_checksum_is_deleted_and_fails(tmp_path: Path) -> None:
    spec = find_model("bs-roformer-ep317")
    (config,) = [f for f in spec.files if f.path.endswith(".yaml")]
    wrong = config.model_copy(update={"sha256": "0" * 64})
    destination = tmp_path / "config.yaml"
    with pytest.raises(DownloadError, match="checksum mismatch"):
        Urllib3Downloader().download(wrong, destination, lambda now, total: None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.gpu  # it asserts that doctor finds the GPU
def test_doctor_on_this_machine_finds_ffmpeg_pytorch_and_the_gpu(tmp_path: Path) -> None:
    checks = run_checks(
        LocalSystemProbe(),
        LocalFileStore(),
        ModelFolder(tmp_path / "models", LocalFileStore()),
        tmp_path,
        Config(),
    )
    by_name = {check.name: check for check in checks}
    assert by_name["ffmpeg"].ok, by_name["ffmpeg"]
    assert by_name["libass"].ok
    assert by_name["encoders"].ok, by_name["encoders"]
    assert by_name["fdkaac"].ok, by_name["fdkaac"]
    assert by_name["PyTorch"].ok, by_name["PyTorch"]
    assert by_name["GPU"].ok, by_name["GPU"]
    assert not by_name["models"].ok  # an empty model folder
    assert by_name["output folder"].ok
