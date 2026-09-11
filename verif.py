"""Backwards-compatible entry point.

Existing deployments run ``python verif.py``; the implementation now lives in the
``verification_bot`` package.
"""

from verification_bot.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
