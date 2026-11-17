"""Risoluzione dei nomi di destinazione per la remediation.

Non accede al filesystem: le verifiche di disponibilita' sono iniettate dal
chiamante (Development guidelines §1).
"""

from .charmap import CHAR_MAP, replacement
from .plan import Action, Lookup, Operation, UnmappedReport, plan
from .remediate import remediate

__all__ = [
    "CHAR_MAP",
    "Action",
    "Lookup",
    "Operation",
    "UnmappedReport",
    "plan",
    "remediate",
    "replacement",
]
