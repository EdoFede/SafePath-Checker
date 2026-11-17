"""Validazione dei nomi secondo il Profilo B.

Nessuna funzione di questo package accede al filesystem: e' cio' che rende i
risultati identici su ogni piattaforma (Development guidelines §1).
"""

from . import codes
from .charset import (
    UNICODE_VERSION,
    collision_key,
    device_segment,
    fold_pattern,
    is_allowed,
    is_alnum,
    is_combining_mark,
    is_nfc,
    is_reserved_basename,
    is_reserved_extension,
    is_windows_device,
    split_extension,
    to_nfc,
    to_nfd,
)
from .codes import (
    DESCRIPTIONS,
    RULESET_VERSION,
    UNQ_001,
    describe,
    describe_codes,
)
from .constants import (
    COMPONENT_MAX_BYTES,
    DIR_NAME_MAX_CHARS,
    DIR_PATH_MAX_CHARS,
    FILE_NAME_MAX_CHARS,
    MAX_DEPTH,
    REL_PATH_MAX_CHARS,
)
from .validate import Kind, Target, check_collisions, validate_component, validate_path

__all__ = [
    "COMPONENT_MAX_BYTES",
    "DESCRIPTIONS",
    "DIR_NAME_MAX_CHARS",
    "DIR_PATH_MAX_CHARS",
    "FILE_NAME_MAX_CHARS",
    "MAX_DEPTH",
    "REL_PATH_MAX_CHARS",
    "RULESET_VERSION",
    "UNICODE_VERSION",
    "UNQ_001",
    "Kind",
    "Target",
    "check_collisions",
    "codes",
    "collision_key",
    "describe",
    "describe_codes",
    "device_segment",
    "fold_pattern",
    "is_allowed",
    "is_alnum",
    "is_combining_mark",
    "is_nfc",
    "is_reserved_basename",
    "is_reserved_extension",
    "is_windows_device",
    "split_extension",
    "to_nfc",
    "to_nfd",
    "validate_component",
    "validate_path",
]
