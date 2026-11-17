"""safepath — validazione e correzione dei nomi di un albero documentale.

    safepath scan        <path>...   cammina e valida            -> report
    safepath auto-rename <path>...   cammina, valida e rinomina  -> report + azioni

``scan`` e' in sola lettura ed e' il dry run: non esiste un ``--dry-run`` su
``auto-rename``, che duplicherebbe ``scan`` invitando all'errore di presumere il
default opposto (Development guidelines §1).
"""

from .version import VERSION

__all__ = ["VERSION"]
