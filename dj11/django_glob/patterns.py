"""Portable glob grammar and SQLite pattern compilation."""

from collections.abc import Iterator


class InvalidPattern(ValueError):
    """A glob pattern uses syntax outside the supported grammar."""


def _tokens(pattern: str) -> Iterator[tuple[str, str]]:
    index = 0
    while index < len(pattern):
        match char := pattern[index]:
            case "\\":
                index = _escaped(pattern, index)
                yield "literal", pattern[index - 1]
            case "[" | "]":
                raise InvalidPattern("character classes are not supported")
            case _:
                yield _kind(char), char
                index += 1


def _escaped(pattern: str, index: int) -> int:
    if index + 1 == len(pattern):
        raise InvalidPattern("trailing escape")
    if pattern[index + 1] not in "*?[]\\":
        raise InvalidPattern("escape must quote a glob metacharacter")
    return index + 2


def _kind(char: str) -> str:
    match char:
        case "*":
            return "star"
        case "?":
            return "one"
        case _:
            return "literal"


def _canonical(kind: str, char: str) -> str:
    if kind in {"star", "one"}:
        return "*" if kind == "star" else "?"
    return f"\\{char}" if char in "*?[]\\" else char


def normalize(pattern: str) -> str:
    """Validate and return a canonical pattern in the package grammar."""
    return "".join(_canonical(kind, char) for kind, char in _tokens(pattern))


def escape_literal(value: str) -> str:
    """Quote every glob metacharacter in a literal value."""
    return "".join(_canonical("literal", char) for char in value)


def sqlite_pattern(pattern: str) -> str:
    """Compile package glob syntax to SQLite GLOB syntax."""
    return "".join(_sqlite_token(kind, char) for kind, char in _tokens(pattern))


def _sqlite_token(kind: str, char: str) -> str:
    if kind == "star":
        return "*"
    if kind == "one":
        return "?"
    return {
        "*": "[*]",
        "?": "[?]",
        "[": "[[]",
        "]": "[]]",
        "\\": r"[\]",
    }.get(char, char)
