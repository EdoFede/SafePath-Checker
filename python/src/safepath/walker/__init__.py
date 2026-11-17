"""Attraversamento del filesystem e produzione delle entry da validare.

Tutta la divergenza fra sistemi operativi e' confinata qui: ``rules`` e
``planner`` non accedono al filesystem (Development guidelines §1).
"""

from .entry import TEMP_PREFIX, Entry, Status, is_bookkeeping
from .exclude import GLOB, REGEX, Matcher, Pattern, PatternError, glob_match
from .osdep import long_path
from .walk import DirHook, Options, WalkError, walk

__all__ = [
    "GLOB",
    "REGEX",
    "TEMP_PREFIX",
    "DirHook",
    "Entry",
    "Matcher",
    "Options",
    "Pattern",
    "PatternError",
    "Status",
    "WalkError",
    "glob_match",
    "is_bookkeeping",
    "long_path",
    "walk",
]
