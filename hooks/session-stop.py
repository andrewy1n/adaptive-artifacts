#!/usr/bin/env python3
"""Session-stop adapter: validate the v0.2 store if one exists."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "runtime"))
from session_hooks import main

if __name__ == "__main__":
    argv = [sys.argv[0]]
    argv.append(sys.argv[1] if len(sys.argv) > 1 else "--cursor")
    argv.append("stop")
    sys.argv = argv
    main()
