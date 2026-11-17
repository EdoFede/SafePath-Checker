"""Entry point del comando ``safepath``."""

import sys

from .cli import run


def main() -> int:
    """Esegue il comando e restituisce l'exit code al processo chiamante."""
    return run(sys.argv[1:], sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
