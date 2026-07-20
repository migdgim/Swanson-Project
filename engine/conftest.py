"""Rende importabili i pacchetti in `src/` durante i test, senza install editable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
