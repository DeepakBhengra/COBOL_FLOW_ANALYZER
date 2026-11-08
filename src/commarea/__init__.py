"""COMMAREA understanding for CICS COBOL programs.

Entry points:
    analyze_commarea(program, analyzer, data_entries) -> CommareaReport
    to_dict(report) / to_text(report)
"""
from .analyzer import analyze_commarea
from .models import COMMAREA_LIMIT, CommareaReport
from .report import to_dict, to_text

__all__ = ["COMMAREA_LIMIT", "CommareaReport", "analyze_commarea", "to_dict", "to_text"]
