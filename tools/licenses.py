"""List the licence of every runtime dependency and fail on one that is not allowed.

``make licenses`` runs this. It starts at the installed ``vocatron`` package, follows its
requirements (the ``cpu`` or ``cuda`` extra of PyTorch included, other extras and requirements
of packages that are not installed left out) and reads each package's licence from its installed
metadata. No network is used. A licence is allowed when it is permissive, LGPL or MPL; for an
``OR`` expression one allowed alternative is enough, for ``AND`` every part must be allowed.
GPL, AGPL and non-commercial licences, and licences this tool does not know, are refused unless
the package is a documented exception (``EXCEPTIONS``), which ``THIRD_PARTY.md`` must mention.
"""

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
ROOT_PACKAGE = "vocatron"
ROOT_EXTRAS = ("cpu", "cuda")  # the extras that bring PyTorch; the other extras are not runtime
MAX_LICENCE_FIELD = 120  # a longer ``License`` field holds the licence text, not its name

# Order matters: the first pattern that matches decides.
REFUSED = re.compile(
    r"non-?commercial|\bnc\b|-nc-|\bagpl|(?<![l\w])gpl|(?<!lesser )general public license",
    re.IGNORECASE,
)
ALLOWED = re.compile(
    r"\bl-?gpl|lesser|\bmit|\bbsd|apache|\bisc\b|\bpsf|python|\bmpl|mozilla|zlib|\b0bsd|\bcc0"
    r"|hpnd|\bbsl-1\.0|boost|unlicense|public domain|cnri",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Package:
    """The licence facts of one installed package.

    Attributes:
        name: The normalised project name.
        version: The installed version.
        expression: The ``License-Expression`` metadata field, else empty.
        field: The ``License`` metadata field, else empty.
        classifiers: The ``License ::`` trove classifiers, without the prefix.
    """

    name: str
    version: str
    expression: str = ""
    field: str = ""
    classifiers: tuple[str, ...] = ()

    @property
    def licence(self) -> str:
        """The licence as one text: the expression, else a short field, else the classifiers."""
        if self.expression:
            return self.expression
        if self.field and len(self.field) <= MAX_LICENCE_FIELD and "\n" not in self.field.strip():
            return self.field.strip()
        return " OR ".join(self.classifiers)


@dataclass(frozen=True)
class Allowance:
    """A package whose licence is not on the allow list, accepted on purpose.

    Attributes:
        prefix: The start of the normalised package name.
        mention: A text that ``THIRD_PARTY.md`` must contain to document the exception.
        reason: Why the exception is accepted, shown in the report.
    """

    prefix: str
    mention: str
    reason: str


EXCEPTIONS = (
    Allowance(
        "nvidia-",
        "NVIDIA CUDA runtime",
        "proprietary NVIDIA runtime libraries that the CUDA build of PyTorch installs",
    ),
    Allowance(
        "cuda-toolkit",
        "NVIDIA CUDA runtime",
        "meta package of the NVIDIA CUDA runtime libraries of the CUDA build of PyTorch",
    ),
)


@dataclass(frozen=True)
class Verdict:
    """The result for one package.

    Attributes:
        package: The package.
        allowed: Whether its licence is on the allow list.
        exception: The documented exception that accepts it, if any.
        undocumented: Whether an exception applies but ``THIRD_PARTY.md`` does not mention it.
    """

    package: Package
    allowed: bool
    exception: Allowance | None = None
    undocumented: bool = False

    @property
    def ok(self) -> bool:
        """Whether the package passes."""
        return (self.allowed or self.exception is not None) and not self.undocumented


def normalise(name: str) -> str:
    """Return a project name in its canonical form (lower case, runs of ``-_.`` as ``-``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def term_allowed(term: str) -> bool:
    """Return whether one licence name (no ``AND`` or ``OR``) is on the allow list."""
    text = re.sub(r"\s+with\s+.*", "", term.strip(), flags=re.IGNORECASE)
    return bool(text) and not REFUSED.search(text) and bool(ALLOWED.search(text))


OPERATOR = r"\(|\)|\bAND\b|\bOR\b|/|;"
# A licence name, with a bracketed note directly after it ("ISC License (ISCL)") kept as part of
# the name; operators are upper case as in SPDX, so "Library or Lesser" stays one name.
TOKEN = re.compile(rf"\s*({OPERATOR}|[^()/;\s][^()/;]*?(?:\s*\([^()]*\))?(?=\s*(?:{OPERATOR}|$)))")


class _Malformed(Exception):
    """A licence expression whose brackets or operators do not fit together."""


def licence_allowed(licence: str) -> bool:
    """Return whether a licence expression is allowed.

    ``AND`` binds closer than ``OR`` (as in SPDX), brackets group, and ``/`` and ``;`` count as
    ``OR``. ``OR`` needs one allowed side, ``AND`` needs both. An empty or malformed expression
    is refused.
    """
    tokens = [match.group(1).strip() for match in TOKEN.finditer(licence) if match.group(1).strip()]
    tokens = ["OR" if token in ("/", ";") else token for token in tokens]
    if not tokens:
        return False
    try:
        allowed, rest = _any_of(tokens)
    except _Malformed:
        return False
    return allowed and not rest


def _any_of(tokens: list[str]) -> tuple[bool, list[str]]:
    """Parse ``a AND b OR c ...``; return whether it is allowed and the tokens after it."""
    allowed, tokens = _all_of(tokens)
    while tokens and tokens[0] == "OR":
        right, tokens = _all_of(tokens[1:])
        allowed = allowed or right
    return allowed, tokens


def _all_of(tokens: list[str]) -> tuple[bool, list[str]]:
    """Parse ``a AND b ...``; return whether every part is allowed and the tokens after it."""
    allowed, tokens = _one(tokens)
    while tokens and tokens[0] == "AND":
        right, tokens = _one(tokens[1:])
        allowed = allowed and right
    return allowed, tokens


def _one(tokens: list[str]) -> tuple[bool, list[str]]:
    """Parse one licence name or a bracketed expression."""
    if not tokens or tokens[0] in ("AND", "OR", ")"):
        raise _Malformed
    if tokens[0] == "(":
        allowed, rest = _any_of(tokens[1:])
        if not rest or rest[0] != ")":
            raise _Malformed
        return allowed, rest[1:]
    return term_allowed(tokens[0]), tokens[1:]


def judge(packages: Iterable[Package], third_party: str) -> list[Verdict]:
    """Judge every package against the allow list and the documented exceptions."""
    verdicts: list[Verdict] = []
    for package in packages:
        allowed = licence_allowed(package.licence)
        exception = next((e for e in EXCEPTIONS if package.name.startswith(e.prefix)), None)
        verdicts.append(
            Verdict(
                package,
                allowed,
                None if allowed else exception,
                undocumented=not allowed
                and exception is not None
                and exception.mention not in third_party,
            )
        )
    return verdicts


def requirement_name(requirement: str) -> tuple[str, str]:
    """Split a requirement line into its normalised name and its marker text."""
    head, _, marker = requirement.partition(";")
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", head)
    return normalise(match.group(1)) if match else "", marker


def follows(owner: str, marker: str) -> bool:
    """Return whether a requirement of ``owner`` with this marker is part of the runtime."""
    if "extra" not in marker:
        return True
    return owner == ROOT_PACKAGE and any(
        f'"{e}"' in marker or f"'{e}'" in marker for e in ROOT_EXTRAS
    )


def installed_packages(root: str = ROOT_PACKAGE) -> list[Package]:
    """Return the installed packages reachable from ``root``, sorted by name, from metadata."""
    found: dict[str, Package] = {}
    todo = [root]
    while todo:
        name = todo.pop()
        if name in found:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue  # not installed on this machine (a platform marker excluded it)
        meta = dist.metadata
        found[name] = Package(
            name=name,
            version=dist.version,
            expression=meta.get("License-Expression") or "",
            field=meta.get("License") or "",
            classifiers=tuple(
                c.split("::")[-1].strip()
                for c in meta.get_all("Classifier") or []
                if c.startswith("License ::")
            ),
        )
        for requirement in dist.requires or []:
            child, marker = requirement_name(requirement)
            if child and follows(name, marker):
                todo.append(child)
    return sorted((p for n, p in found.items() if n != root), key=lambda p: p.name)


def report(verdicts: list[Verdict]) -> list[str]:
    """Return the report lines: one per package, then the problems."""
    lines = [
        f"{'ok  ' if v.ok else 'FAIL'}  {v.package.name} {v.package.version}  "
        f"{v.package.licence or 'no licence stated'}"
        + (f"  [exception: {v.exception.reason}]" if v.exception else "")
        for v in verdicts
    ]
    for v in verdicts:
        if v.undocumented and v.exception:
            lines.append(
                f"{v.package.name}: the exception needs the words '{v.exception.mention}' "
                "in THIRD_PARTY.md"
            )
        elif not v.ok:
            lines.append(
                f"{v.package.name}: licence '{v.package.licence}' is not allowed and has no "
                "documented exception"
            )
    return lines


def main() -> int:
    """Check the installed runtime dependencies and print the report."""
    third_party = (CLONE / "THIRD_PARTY.md").read_text(encoding="utf-8")
    verdicts = judge(installed_packages(), third_party)
    print("\n".join(report(verdicts)))
    failed = [v for v in verdicts if not v.ok]
    print(f"{len(verdicts)} runtime dependencies, {len(failed)} not allowed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
