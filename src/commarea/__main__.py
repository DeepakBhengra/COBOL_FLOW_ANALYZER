"""Command line: python -m src.commarea path/to/program.cbl [--json]"""
from __future__ import annotations

import argparse
import json
import sys

from ..pipeline import analyze_file
from .report import to_dict, to_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain how a CICS COBOL program uses its COMMAREA.")
    parser.add_argument("source", help="COBOL source file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--copybook-dir", action="append", default=[], help="folder to search for COPY members")
    args = parser.parse_args(argv)

    analysis = analyze_file(args.source, copybook_dirs=args.copybook_dir)
    report = analysis.commarea
    if args.json:
        print(json.dumps(to_dict(report), indent=2))
    else:
        print(to_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
