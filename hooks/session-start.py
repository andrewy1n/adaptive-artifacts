#!/usr/bin/env python3
"""Session-start adapter: inject derived v0.2 views."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "runtime"))
from session_hooks import main

if __name__ == "__main__":
    argv = [sys.argv[0]]
    argv.append(sys.argv[1] if len(sys.argv) > 1 else "--cursor")
    argv.append("start")
    sys.argv = argv
    main()
