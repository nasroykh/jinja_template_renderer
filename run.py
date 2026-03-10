#!/usr/bin/env python3
"""
jinja_reader – standalone runner, no install required.

Usage:
    python run.py [template.jinja] [options]

Requires: pip install jinja2
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import jinja2  # noqa: F401
except ImportError:
    print("Error: jinja2 is required.  Run: pip install jinja2", file=sys.stderr)
    sys.exit(1)

from jinja_reader.main import main

if __name__ == "__main__":
    sys.exit(main())
