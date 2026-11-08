"""Command line: python -m src.copybooks PROGRAM [--copybook-dir DIR] [--expanded]

Prints which copybooks were used and which were missing. With --expanded, prints the
program text after expansion, with the file and line each line came from.
"""
from __future__ import annotations

import argparse
import os
import sys

from ..parser.source_format import normalize
from .expander import expand_copybooks
from .library import CopybookLibrary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expand COPY statements in a COBOL program.")
    parser.add_argument("source", nargs="?", help="COBOL program (omit with --list)")
    parser.add_argument("--list", action="store_true", help="list the copybooks found in the --copybook-dir folders")
    parser.add_argument("--copybook-dir", action="append", default=[])
    parser.add_argument("--expanded", action="store_true", help="print the expanded program")
    args = parser.parse_args(argv)

    if args.list:
        library = CopybookLibrary(directories=args.copybook_dir)
        for name in library.available():
            print(name)
        for name, path in library.shadowed:
            print(f"ignored  {name:<12} {path} (a file with a higher-priority extension exists)")
        return 0
    if not args.source:
        parser.error("a COBOL source file is required unless --list is given")

    folder = os.path.dirname(os.path.abspath(args.source))
    library = CopybookLibrary.from_environment(
        extra=[folder, os.path.join(folder, "copybooks")] + args.copybook_dir)
    with open(args.source, encoding="utf-8", errors="replace") as handle:
        result = expand_copybooks(normalize(handle.read()), library, os.path.basename(args.source))

    for use in result.used:
        print(f"used     {use.name:<12} {'  ' * use.depth}from {use.source} (line {use.line})")
    for name in result.missing:
        print(f"MISSING  {name}")
    for problem in result.problems:
        print(f"problem  {problem}")
    if not result.expanded:
        print("No COPY statements found.")

    if args.expanded:
        print()
        for line in result.lines:
            print(f"{line.number:>5}  {line.text:<72}  {line.origin or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
