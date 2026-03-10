"""Allow running as python -m jinja_reader."""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
