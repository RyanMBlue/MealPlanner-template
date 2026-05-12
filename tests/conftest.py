"""Shared pytest configuration.

Puts scripts/ on sys.path so tests can import modules like
`from item_normalizer import normalize` without packaging.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
