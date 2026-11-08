"""COPY statement expansion.

    from src.copybooks import CopybookLibrary, expand_copybooks
"""
from .expander import ExpansionResult, CopybookUse, expand_copybooks, parse_copy_statement
from .library import CopybookLibrary
from .reader import SUPPORTED_EXTENSIONS, decode_bytes, index_directory, read_copybook

__all__ = [
    "CopybookLibrary", "CopybookUse", "ExpansionResult", "SUPPORTED_EXTENSIONS", "decode_bytes",
    "expand_copybooks", "index_directory", "parse_copy_statement", "read_copybook",
]
