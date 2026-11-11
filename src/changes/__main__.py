"""Command line: python -m src.changes path/to/program.cbl "update FIELD with 'Y'" [--json]"""
from __future__ import annotations

import argparse
import json
import sys

from .propose import open_program, propose_change


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Propose a COBOL change from a requirement and the analyzer's facts. The source file is not modified."
    )
    parser.add_argument("source", help="COBOL source file")
    parser.add_argument("requirement", help="for example: update SETATRK-ACOP-PROMO-FLG with 'Y'")
    parser.add_argument("--json", action="store_true", help="print the proposal as JSON")
    parser.add_argument("--copybook-dir", action="append", default=[], help="folder to search for COPY and INCLUDE members")
    args = parser.parse_args(argv)

    analysis, library = open_program(args.source, args.copybook_dir)
    proposal = propose_change(analysis, args.requirement, library)
    if args.json:
        print(json.dumps(proposal, indent=2))
    else:
        print(_text(proposal))
    return 0 if proposal["ok"] else 2


def _text(proposal: dict) -> str:
    lines = [proposal["understood"], ""]
    if proposal.get("error") and not proposal["ok"]:
        lines.append(proposal["error"])
        lines.append("")
    field = proposal.get("field")
    if field:
        pic = f" PIC {field['pic']}" if field.get("pic") else ""
        column = ""
        if field.get("column"):
            column = f"  column {field['column']} {field.get('sql_type') or ''}".rstrip()
        lines.append(f"Field  {field['name']}{pic}{column}")
        if field.get("copybook"):
            lines.append(f"From   {field.get('copybook_label') or field['copybook']}")
        lines.append("")
    placement = proposal.get("placement")
    if placement:
        lines.append(
            f"Place  {placement['paragraph']}  {placement['origin']}  "
            f"({placement['kind']} {placement['table']})"
        )
        lines.append(placement["why"])
        lines.append("")
    if proposal.get("edits"):
        lines.append("Edits")
        for edit in proposal["edits"]:
            lines.append(f"  {edit['kind']} at {edit['origin']}")
            lines.append(f"  {edit['reason']}")
            lines.append(f"  {edit['text']}")
            lines.append("")
    elif proposal["ok"] and not proposal["change_required"]:
        lines.append("No edit.")
        lines.append("")
    if proposal.get("diff"):
        lines.append("Paragraph after the change")
        lines.extend(proposal["diff"])
        lines.append("")
    if proposal.get("consequences"):
        lines.append("Consequences")
        for note in proposal["consequences"]:
            lines.append(f"- {note}")
        lines.append("")
    if proposal.get("warnings"):
        lines.append("Warnings")
        for note in proposal["warnings"]:
            lines.append(f"- {note}")
        lines.append("")
    if proposal.get("evidence"):
        lines.append("Facts used")
        for note in proposal["evidence"]:
            lines.append(f"- {note}")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
