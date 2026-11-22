"""Stage 1 tests for ``tools/licenses.py``: made-up package metadata, no network."""

from pathlib import Path

import pytest

import licenses
from licenses import Package

ROOT = Path(__file__).resolve().parents[3]
CUDA_NOTE = "NVIDIA CUDA runtime"


@pytest.mark.parametrize(
    "licence",
    [
        "MIT",
        "BSD-3-Clause",
        "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND MIT",
        "Apache Software License",
        "ISC License (ISCL)",
        "LGPL-2.1-or-later",
        "GNU Lesser General Public License v2 or later (LGPLv2+)",
        "MPL-2.0 AND MIT",
        "MIT-CMU",
        "GPL-2.0-or-later OR MPL-1.1",
        "(GPL-3.0 OR LGPL-2.1)",
        "GNU Library or Lesser General Public License (LGPL)",
        "GPL-2.0+ / LGPL-2.1+ / MPL-1.1",
        "MIT OR GPL-3.0-only AND AGPL-3.0-only",
        "(MIT OR GPL-3.0-only) AND BSD-3-Clause",
    ],
)
def test_permissive_lgpl_and_mpl_licences_are_allowed(licence: str) -> None:
    assert licenses.licence_allowed(licence)


@pytest.mark.parametrize(
    "licence",
    [
        "GPL-3.0-only",
        "GNU General Public License v3 (GPLv3)",
        "AGPL-3.0-or-later",
        "MIT AND GPL-2.0-only",
        "CC-BY-NC-4.0",
        "Creative Commons Non-Commercial",
        "LicenseRef-NVIDIA-Proprietary",
        "Other/Proprietary License",
        "",
        "GPL-3.0-only AND (MIT OR BSD-3-Clause)",
        "(MIT OR GPL-3.0-only) AND GPL-2.0-only",
        "(MIT",
        "MIT)",
        "MIT AND",
        "OR MIT",
    ],
)
def test_copyleft_non_commercial_and_unknown_licences_are_refused(licence: str) -> None:
    assert not licenses.licence_allowed(licence)


def test_the_licence_comes_from_the_expression_then_a_short_field_then_the_classifiers() -> None:
    assert Package("a", "1", expression="MIT", field="GPL").licence == "MIT"
    assert Package("a", "1", field="BSD").licence == "BSD"
    long_text = "Permission is hereby granted\n" + "x" * 200
    assert Package("a", "1", field=long_text, classifiers=("MIT License",)).licence == "MIT License"
    assert Package("a", "1", classifiers=("A", "B")).licence == "A OR B"
    assert Package("a", "1").licence == ""


def test_a_documented_exception_passes_an_undocumented_one_fails() -> None:
    nvidia = Package("nvidia-cublas", "1", expression="LicenseRef-NVIDIA-Proprietary")
    (documented,) = licenses.judge([nvidia], f"... {CUDA_NOTE} ...")
    assert documented.ok
    assert documented.exception is not None
    (undocumented,) = licenses.judge([nvidia], "nothing about it")
    assert not undocumented.ok
    assert undocumented.undocumented


def test_a_refused_package_without_an_exception_fails() -> None:
    (verdict,) = licenses.judge([Package("evil", "1", expression="GPL-3.0-only")], CUDA_NOTE)
    assert not verdict.ok
    assert verdict.exception is None


def test_the_report_names_each_problem() -> None:
    packages = [
        Package("good", "1.0", expression="MIT"),
        Package("evil", "2.0", expression="GPL-3.0-only"),
        Package("nvidia-x", "3.0", expression="LicenseRef-NVIDIA-Proprietary"),
    ]
    lines = licenses.report(licenses.judge(packages, ""))
    assert lines[0].startswith("ok") and "good 1.0" in lines[0]
    assert lines[1].startswith("FAIL") and "evil 2.0" in lines[1]
    assert any("evil: licence 'GPL-3.0-only' is not allowed" in line for line in lines)
    assert any("nvidia-x: the exception needs the words" in line for line in lines)


def test_requirement_lines_are_split_into_name_and_marker() -> None:
    assert licenses.requirement_name("Foo_Bar>=1.0; python_version >= '3'") == (
        "foo-bar",
        " python_version >= '3'",
    )
    assert licenses.requirement_name("") == ("", "")


def test_only_the_pytorch_extras_of_vocatron_and_no_other_extras_are_followed() -> None:
    assert licenses.follows("x", "")
    assert licenses.follows("x", " sys_platform == 'linux'")
    assert licenses.follows("vocatron", ' extra == "cuda"')
    assert not licenses.follows("vocatron", ' extra == "dev"')
    assert not licenses.follows("transformers", ' extra == "cuda"')


def test_the_installed_runtime_dependencies_are_found_and_pass() -> None:
    packages = licenses.installed_packages()
    names = {p.name for p in packages}
    assert {"pydantic", "numpy", "pyphen"} <= names
    assert "vocatron" not in names
    third_party = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert [v.package.name for v in licenses.judge(packages, third_party) if not v.ok] == []


def test_third_party_mentions_the_text_every_exception_needs() -> None:
    third_party = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert all(e.mention in third_party for e in licenses.EXCEPTIONS)
