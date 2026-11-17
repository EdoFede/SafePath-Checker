"""Accumulazione e serializzazione del report nei tre formati."""

from .console import DEFAULT_WIDTH, ConsoleOptions, detect_console_options, write_console
from .model import SCHEMA_VERSION, Action, Options, Outcome, Report, Row, Summary
from .writers import UTF8_BOM, write_csv, write_json, write_manifest

__all__ = [
    "DEFAULT_WIDTH",
    "SCHEMA_VERSION",
    "UTF8_BOM",
    "Action",
    "ConsoleOptions",
    "Options",
    "Outcome",
    "Report",
    "Row",
    "Summary",
    "detect_console_options",
    "write_console",
    "write_csv",
    "write_json",
    "write_manifest",
]
