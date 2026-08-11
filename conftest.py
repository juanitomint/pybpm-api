"""Project-root conftest — adds the project directory to sys.path before any
test module is imported, so top-level packages (`app`, `utils`) are importable
regardless of how pytest is invoked."""

import os
import sys

_project_root = os.path.dirname(os.path.abspath(__file__))
_app_dir = os.path.join(_project_root, "app")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _app_dir not in sys.path:
    sys.path.insert(1, _app_dir)


def pytest_configure(config):
    """Configure pytest to exclude non-test directories."""
    # Exclude pgdata directory which may have permission issues
    config.addinivalue_line("norecursedirs", "pgdata")

