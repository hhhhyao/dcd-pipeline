from __future__ import annotations

import sys
from pathlib import Path


PIPE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPE_PARENT))
