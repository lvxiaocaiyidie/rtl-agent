from __future__ import annotations

from pathlib import Path

from .models import DesignIndex, rel_path
from .parser import discover_rtl_files, parse_file


def build_index(root: Path, top: list[str] | None = None, top_file: Path | None = None) -> DesignIndex:
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
    candidate_top_modules = sorted(name for name in modules if name not in instantiated)
    explicit_tops = _resolve_explicit_tops(modules, root, top or [], top_file, diagnostics)
    top_modules = explicit_tops or candidate_top_modules
    reachable_modules = _collect_reachable(modules, top_modules)
    orphan_modules = sorted(name for name in modules if name not in set(reachable_modules))
    unresolved_modules = sorted(instantiated - set(modules))
    return DesignIndex(
        root=root.as_posix(),
        files=[rel_path(p, root) for p in files],
        modules=modules,
        top_modules=top_modules,
        candidate_top_modules=candidate_top_modules,
        reachable_modules=reachable_modules,
        orphan_modules=orphan_modules,
        unresolved_modules=unresolved_modules,
        diagnostics=diagnostics,
    )


def _resolve_explicit_tops(
    modules: dict,
    root: Path,
    top_names: list[str],
    top_file: Path | None,
    diagnostics: list[dict],
) -> list[str]:
    explicit: list[str] = []
    for name in top_names:
        if name in modules:
            explicit.append(name)
        else:
            diagnostics.append({"severity": "error", "type": "unknown_top", "message": f"top module {name} was not found", "source": name})
    if top_file:
        file_path = top_file if top_file.is_absolute() else root / top_file
        file_rel = rel_path(file_path, root)
        file_modules = [name for name, module in modules.items() if module.source.file == file_rel]
        if file_modules:
            explicit.extend(file_modules)
        else:
            diagnostics.append({"severity": "error", "type": "unknown_top_file", "message": f"no modules found in top file {file_rel}", "source": file_rel})
    return sorted(set(explicit))


def _collect_reachable(modules: dict, roots: list[str]) -> list[str]:
    seen: set[str] = set()
    stack = list(reversed(roots))
    while stack:
        name = stack.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        for inst in reversed(modules[name].instances):
            if inst.module in modules and inst.module not in seen:
                stack.append(inst.module)
    return sorted(seen)
