"""Project-root conftest — adds the project directory to sys.path before any
test module is imported, so top-level packages (`app`, `utils`) are importable
regardless of how pytest is invoked."""

import os
import sys

_project_root = os.path.dirname(os.path.abspath(__file__))
_app_dir = os.path.join(_project_root, "app")
print(f"DEBUG conftest: project root = {_project_root}")
print(f"DEBUG conftest: sys.path = {sys.path[:5]}")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _app_dir not in sys.path:
    sys.path.insert(1, _app_dir)
