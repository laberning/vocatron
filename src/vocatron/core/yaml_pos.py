"""Parse YAML text and remember the line and column of every key (ADR-0002, ADR-0009).

Pydantic reports an error as a path of keys; the position of a key comes from the YAML parser.
The configuration file and the style profiles both use this to report ``file:line:column``.
"""

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from vocatron.core.config_errors import Location, Positions


class YamlSyntaxError(Exception):
    """The text is not valid YAML; the message is ``file:line:column: problem``."""


def _positions(node: object, prefix: Location, found: dict[Location, tuple[int, int]]) -> None:
    """Record the line and column (from 1) of every key and list item below ``node``."""
    if isinstance(node, CommentedMap):
        for key, value in node.items():
            line, column = node.lc.key(key)
            found[(*prefix, str(key))] = (line + 1, column + 1)
            _positions(value, (*prefix, str(key)), found)
    elif isinstance(node, CommentedSeq):
        for index, value in enumerate(node):
            line, column = node.lc.item(index)
            found[(*prefix, index)] = (line + 1, column + 1)
            _positions(value, (*prefix, index), found)


def parse_yaml(file: str, text: str) -> tuple[object, Positions]:
    """Parse YAML text; return the data and the position of every key.

    Raises:
        YamlSyntaxError: If the text is not valid YAML.
    """
    try:
        data: object = YAML(typ="rt").load(text)
    except YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (1, 1)
        problem = getattr(error, "problem", None) or "invalid YAML"
        raise YamlSyntaxError(f"{file}:{line}:{column}: {problem}") from error
    found: dict[Location, tuple[int, int]] = {}
    _positions(data, (), found)
    return data, found
