"""Reads copybook files (.cpy and .txt) from disk and decides which file a name refers to.

Text is decoded by checking, in order:
  1. a byte-order mark (UTF-8, UTF-16 LE/BE), which is what Notepad and many editors write
  2. strict UTF-8
  3. Windows-1252, the usual encoding of older mainframe-exported text on Windows
Anything that still fails is decoded as Latin-1, which never fails, so a copybook is always read.

File names are matched on the stem, ignoring case: CUSTCOMM matches CUSTCOMM.cpy and
CUSTCOMM.txt. Other file types in the folder are ignored. If the same stem exists more than
once, .cpy wins over .txt, and the choice is reported as a shadowed file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Extensions in priority order: the first one wins when a name exists more than once.
SUPPORTED_EXTENSIONS = (".cpy", ".txt")

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def decode_bytes(data: bytes) -> str:
    """Decode copybook bytes into text. Never raises."""
    for bom, codec in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(codec)
            except UnicodeDecodeError:
                break
    for codec in ("utf-8", "cp1252"):
        try:
            return data.decode(codec)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_copybook(path: str) -> str:
    """Read one copybook file and return its text."""
    with open(path, "rb") as handle:
        return decode_bytes(handle.read())


@dataclass
class CopybookFile:
    name: str           # the name used in COPY statements (file stem, upper case)
    path: str
    extension: str


@dataclass
class DirectoryIndex:
    files: dict[str, CopybookFile] = field(default_factory=dict)
    shadowed: list[tuple[str, str]] = field(default_factory=list)   # (name, ignored path)


def index_directory(directory: str, index: DirectoryIndex | None = None) -> DirectoryIndex:
    """Add the copybook files of one folder to the index. Earlier entries win."""
    index = index or DirectoryIndex()
    if not os.path.isdir(directory):
        return index

    found: dict[str, list[CopybookFile]] = {}
    for filename in sorted(os.listdir(directory)):
        stem, extension = os.path.splitext(filename)
        if extension.lower() not in SUPPORTED_EXTENSIONS:
            continue
        full = os.path.join(directory, filename)
        if not os.path.isfile(full):
            continue
        found.setdefault(stem.upper(), []).append(
            CopybookFile(name=stem.upper(), path=full, extension=extension.lower()))

    for name, candidates in found.items():
        candidates.sort(key=lambda c: SUPPORTED_EXTENSIONS.index(c.extension))
        if name in index.files:
            index.shadowed.extend((name, c.path) for c in candidates)
            continue
        index.files[name] = candidates[0]
        index.shadowed.extend((name, c.path) for c in candidates[1:])
    return index
