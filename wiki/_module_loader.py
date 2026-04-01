from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType


def load_pipe_package(pipe_dir: Path, *, alias: str | None = None) -> ModuleType:
    """Load a pipe package from an arbitrary directory name.

    This keeps local runners/tests working even when the directory starts with
    digits such as `0_...`, which is not importable via normal dotted syntax.
    """

    pipe_dir = pipe_dir.resolve()
    init_py = pipe_dir / "__init__.py"
    if not init_py.is_file():
        raise FileNotFoundError(f"Pipe package entrypoint not found: {init_py}")

    module_name = alias or f"wiki_pipe_{re.sub(r'\\W+', '_', pipe_dir.name)}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(
        module_name,
        init_py,
        submodule_search_locations=[str(pipe_dir)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load pipe package from {init_py}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
