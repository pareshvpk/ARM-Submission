"""Package execution entry point for PS3 Sentinel.

Invokes the command-line interface when running `python -m sentinel`.
Delegates all argument parsing and execution to sentinel.cli.main.
"""
from __future__ import annotations

import sys
from sentinel.cli import main

if __name__ == "__main__":
    sys.exit(main())
