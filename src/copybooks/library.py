"""Where copybooks come from: uploaded text, folders on disk, or the COBOL_COPYBOOKS variable.

Resolution order for a name such as CUSTCOMM:
  1. texts supplied in memory (for example uploads from the UI or API)
  2. the directories given, in order; see reader.py for the file types and encodings
"""
from __future__ import annotations

import os

from .reader import DirectoryIndex, index_directory, read_copybook

ENV_VAR = "COBOL_COPYBOOKS"


class CopybookLibrary:
    def __init__(self, directories: list[str] | None = None, texts: dict[str, str] | None = None):
        self._texts: dict[str, tuple[str, str]] = {}
        self._index = DirectoryIndex()
        for name, text in (texts or {}).items():
            self._texts[_key(name)] = (f"{name} (uploaded)", text)
        for directory in directories or []:
            index_directory(directory, self._index)

    @classmethod
    def from_environment(cls, extra: list[str] | None = None, texts: dict[str, str] | None = None) -> "CopybookLibrary":
        dirs = list(extra or [])
        dirs += [d for d in os.environ.get(ENV_VAR, "").split(os.pathsep) if d.strip()]
        return cls(directories=dirs, texts=texts)

    def resolve(self, name: str) -> tuple[str, str] | None:
        """Return (label, text) for a copybook name, or None if it cannot be found."""
        key = _key(name)
        if key in self._texts:
            return self._texts[key]
        entry = self._index.files.get(key)
        if entry is None:
            return None
        return os.path.basename(entry.path), read_copybook(entry.path)

    def available(self) -> list[str]:
        """Names this library can resolve, sorted."""
        return sorted(set(self._texts) | set(self._index.files))

    @property
    def shadowed(self) -> list[tuple[str, str]]:
        """(name, path) of files ignored because another file with the same name came first."""
        return list(self._index.shadowed)


def _key(name: str) -> str:
    return name.strip().upper()
