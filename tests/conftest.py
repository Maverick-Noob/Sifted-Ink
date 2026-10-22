"""
Pytest conftest — makes the package importable.

The repository root IS the package directory (``novel_preactor/``), so the
*parent* directory has to be on sys.path for ``import novel_preactor.xxx``
to resolve. The parent is inserted first, otherwise ``novel_preactor.py``
inside the package shadows the package directory of the same name.
"""

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent.parent
_PARENT_DIR = _PKG_DIR.parent

for _p in (str(_PKG_DIR), str(_PARENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# The parent must win for the name "novel_preactor" itself
if str(_PARENT_DIR) in sys.path:
    sys.path.remove(str(_PARENT_DIR))
    sys.path.insert(0, str(_PARENT_DIR))
