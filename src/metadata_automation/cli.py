"""Command line interface; JSON is read and written only by explicit commands."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib

from .metadata import PLATFORMS, ValidationError, extract, generate, schema, validate


def _version() -> str:
    try:
        return version("metadata-automation")
    except PackageNotFoundError:
        return tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())["project"]["version"]


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValidationError(f"Nonfinite JSON number: {value}")


def _read(path: str) -> object:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as error:
        raise ValidationError(f"Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}") from error


def _write(value: object, path: str | None) -> None:
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if path is None or path == "-":
        sys.stdout.write(content)
        return
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Derive metadata drafts from one editorial JSON brief.")
    parser.add_argument("--version", action="version", version=f"metadata-automation {_version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate", help="Generate the nine-platform metadata envelope")
    create.add_argument("brief", help="Brief JSON path, or - for stdin")
    create.add_argument("-o", "--output", help="Output JSON path; default: stdout")
    create.add_argument("--youtube-metadata", help="Import validated flat YouTube title/description/tags JSON")
    check = commands.add_parser("validate", help="Validate against a bundled JSON Schema")
    check.add_argument("input", help="JSON path, or - for stdin")
    check.add_argument("--kind", choices=("brief", "metadata"), default="metadata")
    publish_schema = commands.add_parser("schema", help="Export the published Draft 2020-12 schema")
    publish_schema.add_argument("--kind", choices=("brief", "metadata"), default="metadata")
    publish_schema.add_argument("-o", "--output", help="Output JSON path; default: stdout")
    select = commands.add_parser("extract", help="Extract one validated platform block")
    select.add_argument("platform", choices=PLATFORMS)
    select.add_argument("metadata", help="Metadata envelope JSON path, or - for stdin")
    select.add_argument("-o", "--output", help="Output JSON path; default: stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "generate":
            if arguments.brief == "-" and arguments.youtube_metadata == "-":
                raise ValidationError("Only one input can use stdin")
            imported = _read(arguments.youtube_metadata) if arguments.youtube_metadata else None
            _write(generate(_read(arguments.brief), imported), arguments.output)
        elif arguments.command == "validate":
            validate(_read(arguments.input), arguments.kind)
            print(f"Valid {arguments.kind} document.", file=sys.stderr)
        elif arguments.command == "schema":
            _write(schema(arguments.kind), arguments.output)
        else:
            _write(extract(_read(arguments.metadata), arguments.platform), arguments.output)
    except (ValidationError, OSError, UnicodeError, ValueError) as error:
        print(f"metadata-automation: {error}", file=sys.stderr)
        return 2
    return 0
