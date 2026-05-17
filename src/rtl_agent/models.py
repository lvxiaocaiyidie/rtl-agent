from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SourceRange:
    file: str
    start_line: int
    end_line: int

    def label(self) -> str:
        return f"{self.file}:{self.start_line}-{self.end_line}"


@dataclass(slots=True)
class Port:
    name: str
    direction: str
    data_type: str = ""
    width: str = ""
    source: SourceRange | None = None


@dataclass(slots=True)
class Parameter:
    name: str
    value: str = ""
    source: SourceRange | None = None


@dataclass(slots=True)
class Signal:
    name: str
    kind: str
    width: str = ""
    source: SourceRange | None = None


@dataclass(slots=True)
class Instance:
    module: str
    name: str
    parameters: dict[str, str] = field(default_factory=dict)
    connections: dict[str, str] = field(default_factory=dict)
    connection_style: str = "unknown"
    source: SourceRange | None = None


@dataclass(slots=True)
class ProceduralBlock:
    kind: str
    sensitivity: str
    source: SourceRange


@dataclass(slots=True)
class Module:
    name: str
    source: SourceRange
    ports: list[Port] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    assigns: list[SourceRange] = field(default_factory=list)
    procedural_blocks: list[ProceduralBlock] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    clocks: list[str] = field(default_factory=list)
    resets: list[str] = field(default_factory=list)
    role: str = "leaf_rtl"
    subsystem: str = "unknown"


@dataclass(slots=True)
class DesignIndex:
    root: str
    files: list[str]
    modules: dict[str, Module]
    top_modules: list[str]
    candidate_top_modules: list[str] = field(default_factory=list)
    reachable_modules: list[str] = field(default_factory=list)
    orphan_modules: list[str] = field(default_factory=list)
    unresolved_modules: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
