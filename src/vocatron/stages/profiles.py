"""Finding, listing and loading the style profiles a configuration can use (ADR-0009, ADR-0019).

``profile`` is a name or the path of a YAML file. A name is a built-in profile or the file
``<name>.yaml`` in ``profiles_folder``; a name in both is an error, so a shared name never
silently changes a look. The text decides the fingerprint of the layout stage, so a changed
profile file re-runs exactly the layout and the render, and setting the folder re-runs nothing.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from vocatron.core.errors import StageError
from vocatron.core.profiles.model import (
    BUILTIN_PROFILES,
    PROFILE_SUFFIXES,
    Profile,
    ProfileError,
    is_name,
    parse_profile,
)
from vocatron.engines.protocols import FileStore, Resources

OWN_SUFFIX = PROFILE_SUFFIXES[0]  # own profiles are the .yaml files of the folder


@dataclass(frozen=True)
class ProfileText:
    """The text of a profile and where it came from (for error messages).

    Attributes:
        label: The file name for messages: ``profiles/<name>.yaml`` for a built-in profile, the
            path otherwise.
        text: The YAML text.
        path: The file, or ``None`` for a built-in profile.
    """

    label: str
    text: str
    path: Path | None = None


@dataclass(frozen=True)
class ProfileEntry:
    """One profile of the list ``vocatron profiles`` prints.

    Attributes:
        name: The name to choose it by.
        source: ``built in``, or the path of the file.
        path: The file, or ``None`` for a built-in profile.
        profile: The loaded profile, or ``None`` when it does not load.
        problem: Why it is invalid, or ``None``.
    """

    name: str
    source: str
    path: Path | None
    profile: Profile | None
    problem: str | None = None


def folder_path(profiles_folder: str | None) -> Path | None:
    """Return the ``profiles_folder`` setting as a path, or ``None`` when it is not set."""
    return None if profiles_folder is None else Path(profiles_folder)


def builtin_label(name: str) -> str:
    """Return the file name of the built-in profile ``name`` for messages."""
    return f"profiles/{name}.yaml"


def own_files(folder: Path | None, store: FileStore) -> list[Path]:
    """Return the own profile files of ``folder`` (none without a folder), sorted.

    Only files ending in exactly ``.yaml`` count: a name is looked up as ``<name>.yaml``, so a
    file ``Mine.YAML`` could be listed but never chosen.
    """
    if folder is None:
        return []
    return [path for path in store.list_files(folder, (OWN_SUFFIX,)) if path.suffix == OWN_SUFFIX]


def known_names(folder: Path | None, store: FileStore) -> list[str]:
    """Return the names a ``profile`` can have: the built-in ones, then the own ones."""
    own = [path.stem for path in own_files(folder, store) if path.stem not in BUILTIN_PROFILES]
    return [*BUILTIN_PROFILES, *own]


def clash_message(name: str, path: Path) -> str:
    """Return the error for an own profile that has the name of a built-in one."""
    return (
        f"{path}: {name!r} is also the name of a built-in profile; rename the file. To change "
        f"single values of the built-in profile use profile_overrides, to start an own look "
        f"from it use `vocatron profiles copy {name}`"
    )


def profile_text(
    spec: str, folder: Path | None, store: FileStore, resources: Resources
) -> ProfileText | None:
    """Return the text of the profile ``spec`` names, or ``None`` if there is none.

    Args:
        spec: A name (built in, or a file of ``folder``) or the path of a YAML file.
        folder: The ``profiles_folder``, or ``None``.
        store: Reads the files.
        resources: Holds the built-in profiles.

    Raises:
        StageError: ``invalid-profile`` if a file cannot be read, or a name is both built in and
            in the folder.
    """
    if not is_name(spec):
        return _read(Path(spec), store)
    built_in = resources.builtin_profile(spec)
    own = None if folder is None else _read(folder / f"{spec}{OWN_SUFFIX}", store)
    if built_in is not None and own is not None:
        raise StageError("invalid-profile", clash_message(spec, own.path or Path(spec)))
    if built_in is not None:
        return ProfileText(builtin_label(spec), built_in)
    return own


def _read(path: Path, store: FileStore) -> ProfileText | None:
    """Read a profile file; ``None`` if it does not exist."""
    try:
        text = store.read_text(path)
    except (OSError, UnicodeDecodeError) as error:
        raise StageError("invalid-profile", f"{path}: cannot read: {error}") from error
    return None if text is None else ProfileText(str(path), text, path)


def not_found(spec: str, folder: Path | None, store: FileStore) -> str:
    """Return the error for a profile that does not exist, with the names that do."""
    if is_name(spec):
        return (
            f"profile {spec!r} not found; known profiles: {', '.join(known_names(folder, store))}"
        )
    return f"profile file {spec!r} not found"


def load_profile(
    spec: str,
    overrides: dict[str, JsonValue],
    folder: Path | None,
    store: FileStore,
    resources: Resources,
) -> Profile:
    """Load the profile ``spec`` with the overrides applied.

    Raises:
        StageError: ``invalid-profile`` if there is no such profile or it does not validate; the
            message has one line per problem, each with file, line and column.
    """
    found = profile_text(spec, folder, store, resources)
    if found is None:
        raise StageError("invalid-profile", not_found(spec, folder, store))
    try:
        return parse_profile(found.label, found.text, overrides)
    except ProfileError as error:
        raise StageError("invalid-profile", "\n".join(error.messages)) from error


def list_profiles(
    folder: Path | None, store: FileStore, resources: Resources
) -> list[ProfileEntry]:
    """Return every built-in profile and every own profile, each loaded without overrides.

    An own file that does not load, or that has the name of a built-in profile, is listed with
    its problem.
    """
    entries: list[ProfileEntry] = []
    for name in BUILTIN_PROFILES:
        text = resources.builtin_profile(name) or ""
        entries.append(_entry(name, "built in", None, builtin_label(name), text))
    for path in own_files(folder, store):
        name = path.stem
        if name in BUILTIN_PROFILES:
            entries.append(ProfileEntry(name, str(path), path, None, clash_message(name, path)))
            continue
        try:
            found = _read(path, store)
        except StageError as error:
            entries.append(ProfileEntry(name, str(path), path, None, str(error)))
            continue
        entries.append(_entry(name, str(path), path, str(path), found.text if found else ""))
    return entries


def _entry(name: str, source: str, path: Path | None, label: str, text: str) -> ProfileEntry:
    """Load ``text`` and wrap the profile, or the first problem, in an entry."""
    try:
        return ProfileEntry(name, source, path, parse_profile(label, text))
    except ProfileError as error:
        return ProfileEntry(name, source, path, None, error.messages[0])


def is_chosen(entry: ProfileEntry, spec: str) -> bool:
    """Tell whether the profile ``spec`` of the configuration is the one ``entry`` lists.

    A name picks the built-in profile of that name, or else the own file of that name (an own file
    with a built-in name is a clash and never chosen). A path picks the entry with that file.
    """
    if entry.path is None:
        return entry.name == spec
    if is_name(spec):
        return entry.name == spec and entry.name not in BUILTIN_PROFILES
    return Path(os.path.normpath(entry.path)) == Path(os.path.normpath(spec))
