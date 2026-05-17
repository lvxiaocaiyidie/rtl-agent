from __future__ import annotations

from pathlib import Path

from .models import DesignIndex, rel_path
from .parser import discover_rtl_files, parse_file


def build_index(root: Path) -> DesignIndex:
    root = root.resolve()
    files = discover_rtl_files(root)
    modules = {}
    diagnostics = []
    for file in files:
        try:
            for module in parse_file(file, root):
                if module.name in modules:
                    diagnostics.append(
                        {
                            "severity": "warning",
                            "type": "duplicate_module",
                            "message": f"module {module.name} is defined more than once",
                            "source": module.source.label(),
                        }
                    )
                modules[module.name] = module
        except OSError as exc:
            diagnostics.append({"severity": "error", "type": "read_error", "message": str(exc), "source": rel_path(file, root)})
    instantiated = {inst.module for module in modules.values() for inst in module.instances}
    top_modules = sorted(name for name in modules if name not in instantiated)
    return DesignIndex(
        root=root.as_posix(),
        files=[rel_path(p, root) for p in files],
        modules=modules,
        top_modules=top_modules,
        diagnostics=diagnostics,
    )
