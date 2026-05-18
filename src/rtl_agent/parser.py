from __future__ import annotations

import re
from pathlib import Path

from .models import Instance, Module, Parameter, Port, ProceduralBlock, Signal, SourceRange, rel_path

RTL_SUFFIXES = {".v", ".sv", ".vh", ".svh"}
KEYWORDS = {
    "assign", "always", "always_comb", "always_ff", "always_latch", "and", "begin",
    "case", "default", "else", "end", "endcase", "endgenerate", "endmodule",
    "for", "generate", "if", "initial", "input", "inout", "interface", "logic",
    "assert", "assume", "cover", "genvar", "integer", "module", "not", "or",
    "output", "parameter", "property", "reg", "restrict", "wire",
}
PRIMITIVES = {
    "and", "buf", "bufif0", "bufif1", "cmos", "nand", "nmos", "nor", "not",
    "notif0", "notif1", "or", "pmos", "pullup", "pulldown", "rcmos", "rnmos",
    "rpmos", "rtran", "rtranif0", "rtranif1", "tran", "tranif0", "tranif1",
    "xnor", "xor",
}


def discover_rtl_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in RTL_SUFFIXES)


def strip_comments_preserve_lines(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//.*", "", text)


def parse_file(path: Path, root: Path) -> list[Module]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    clean = strip_comments_preserve_lines(raw)
    rel = rel_path(path, root)
    modules: list[Module] = []
    module_re = re.compile(
        r"\bmodule\s+([a-zA-Z_][\w$]*)\b(?P<header>.*?);(?P<body>.*?)\bendmodule\b",
        re.S,
    )
    for match in module_re.finditer(clean):
        name = match.group(1)
        start = clean[: match.start()].count("\n") + 1
        end = clean[: match.end()].count("\n") + 1
        source = SourceRange(rel, start, end)
        header = match.group("header")
        body = match.group("body")
        module = Module(name=name, source=source)
        module.includes = _extract_includes(clean, rel)
        module.imports = _extract_imports(header + "\n" + body)
        module.parameters = _extract_parameters(header + "\n" + body, rel, start)
        module.ports = _extract_ports(header, body, rel, start)
        module.signals = _extract_signals(body, rel, start + header.count("\n"))
        module.instances = _extract_instances(body, rel, start + header.count("\n"))
        module.assigns = _extract_assigns(body, rel, start + header.count("\n"))
        module.procedural_blocks = _extract_procedural(body, rel, start + header.count("\n"))
        module.clocks = _detect_names(module, ("clk", "clock", "aclk"))
        module.resets = _detect_names(module, ("rst", "reset", "aresetn", "rst_n"))
        module.subsystem = _infer_subsystem(rel, module.name)
        module.role = _infer_role(module)
        modules.append(module)
    return modules


def _extract_includes(text: str, rel: str) -> list[str]:
    return sorted(set(re.findall(r"`include\s+\"([^\"]+)\"", text)))


def _extract_imports(text: str) -> list[str]:
    return sorted(set(re.findall(r"\bimport\s+([^;]+);", text)))


def _extract_parameters(text: str, rel: str, base_line: int) -> list[Parameter]:
    params: list[Parameter] = []
    for match in re.finditer(r"\bparameter\s+(?:\w+\s+)?([a-zA-Z_][\w$]*)\s*(?:=\s*([^,;\)\n]+))?", text):
        line = base_line + text[: match.start()].count("\n")
        params.append(Parameter(match.group(1), (match.group(2) or "").strip(), SourceRange(rel, line, line)))
    return _unique_by_name(params)


def _extract_ports(header: str, body: str, rel: str, base_line: int) -> list[Port]:
    ports: list[Port] = []
    port_re = re.compile(
        r"^\s*(input|output|inout)\b\s*(?P<rest>.*?)(?:[,;]?\s*)$",
    )
    for region, offset in ((header, 0), (body, header.count("\n"))):
        for idx, line_text in enumerate(region.splitlines()):
            match = port_re.match(line_text)
            if not match:
                continue
            direction = match.group(1)
            rest = match.group("rest").strip().rstrip(",;)")
            width_match = re.search(r"\[[^\]]+\]", rest)
            width = width_match.group(0) if width_match else ""
            without_width = re.sub(r"\[[^\]]+\]", " ", rest)
            type_tokens = [
                token
                for token in re.findall(r"[a-zA-Z_][\w$]*", without_width)
                if token in {"wire", "reg", "logic", "signed", "unsigned"} or token.endswith("_t") or "::" in token
            ]
            for name in _split_names(without_width):
                if name and name not in KEYWORDS and name not in {"wire", "reg", "logic", "signed", "unsigned"}:
                    ports.append(Port(name, direction, " ".join(type_tokens), width, SourceRange(rel, base_line + offset + idx, base_line + offset + idx)))
    return _unique_by_name(ports)


def _extract_signals(body: str, rel: str, base_line: int) -> list[Signal]:
    signals: list[Signal] = []
    sig_re = re.compile(r"\b(wire|reg|logic)\b\s*(?P<width>\[[^\]]+\])?\s*(?P<names>[^;]+);")
    for match in sig_re.finditer(body):
        kind = match.group(1)
        width = (match.group("width") or "").strip()
        line = base_line + body[: match.start()].count("\n")
        for name in _split_names(match.group("names")):
            if name and name not in KEYWORDS:
                signals.append(Signal(name, kind, width, SourceRange(rel, line, line)))
    return _unique_by_name(signals)


def _extract_instances(body: str, rel: str, base_line: int) -> list[Instance]:
    instances: list[Instance] = []
    inst_re = re.compile(
        r"(?<!\w)([a-zA-Z_][\w$]*)\s*(?:#\s*\((?P<params>.*?)\))?\s+([a-zA-Z_][\w$]*)\s*\((?P<ports>.*?)\)\s*;",
        re.S,
    )
    for match in inst_re.finditer(body):
        mod, name = match.group(1), match.group(3)
        if mod in KEYWORDS or mod in PRIMITIVES or name in KEYWORDS:
            continue
        line = base_line + body[: match.start()].count("\n")
        port_text = match.group("ports") or ""
        instances.append(
            Instance(
                module=mod,
                name=name,
                parameters=_extract_named_map(match.group("params") or ""),
                connections=_extract_named_map(port_text),
                connection_style=_connection_style(port_text),
                source=SourceRange(rel, line, line),
            )
        )
    return instances


def _extract_assigns(body: str, rel: str, base_line: int) -> list[SourceRange]:
    ranges: list[SourceRange] = []
    for match in re.finditer(r"\bassign\b[^;]*;", body, re.S):
        start = base_line + body[: match.start()].count("\n")
        end = base_line + body[: match.end()].count("\n")
        ranges.append(SourceRange(rel, start, end))
    return ranges


def _extract_procedural(body: str, rel: str, base_line: int) -> list[ProceduralBlock]:
    blocks: list[ProceduralBlock] = []
    proc_re = re.compile(r"\b(always_ff|always_comb|always_latch|always|initial)\b\s*(?:@\s*\((?P<sens>.*?)\))?", re.S)
    for match in proc_re.finditer(body):
        line = base_line + body[: match.start()].count("\n")
        blocks.append(ProceduralBlock(match.group(1), " ".join((match.group("sens") or "").split()), SourceRange(rel, line, line)))
    return blocks


def _extract_named_map(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"\.([a-zA-Z_][\w$]*)\s*\(\s*([^\)]*)\)", text, re.S):
        result[match.group(1)] = " ".join(match.group(2).split())
    return result


def _connection_style(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    if re.search(r"\.[a-zA-Z_][\w$]*\s*\(", stripped):
        return "named"
    return "positional"


def _split_names(text: str) -> list[str]:
    names = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        chunk = re.sub(r"=.*", "", chunk).strip()
        chunk = re.sub(r"\[[^\]]+\]", "", chunk).strip()
        parts = re.findall(r"[a-zA-Z_][\w$]*", chunk)
        if parts:
            names.append(parts[-1])
    return names


def _unique_by_name(items):
    seen = set()
    out = []
    for item in items:
        name = item.name
        if name not in seen:
            seen.add(name)
            out.append(item)
    return out


def _detect_names(module: Module, needles: tuple[str, ...]) -> list[str]:
    names = [p.name for p in module.ports] + [s.name for s in module.signals]
    found = []
    for name in names:
        if _looks_like_clock(name) if "clk" in needles else _looks_like_reset(name):
            found.append(name)
    return sorted(set(found))


def _looks_like_clock(name: str) -> bool:
    low = name.lower()
    if (
        low.endswith("_clk_en")
        or low.endswith("clk_en")
        or low.endswith("_clock_en")
        or low.endswith("clock_en")
        or low.endswith("_gateclk_en")
        or low.endswith("gateclk_en")
        or low.endswith("_for_gateclk")
        or low.endswith("_for_clk")
    ):
        return False
    if low in {"clk", "clock", "aclk", "hclk", "pclk", "cpuclk", "sck", "tck"}:
        return True
    return (
        low.endswith("_clk")
        or low.endswith("_clock")
        or low.endswith("clk")
        or low.startswith("clk_")
        or low.startswith("clock_")
    )


def _looks_like_reset(name: str) -> bool:
    low = name.lower()
    if low in {"rst", "reset", "resetn", "rst_n", "rst_b", "aresetn", "hrst_b", "cpurst_b"}:
        return True
    return (
        low.endswith("_rst")
        or low.endswith("_reset")
        or low.endswith("_rst_n")
        or low.endswith("_rst_b")
        or low.endswith("rst_b")
        or low.endswith("rst_n")
        or low.startswith("rst_")
        or low.startswith("reset_")
    )


def _infer_subsystem(rel_path_text: str, module_name: str) -> str:
    low = (rel_path_text + "/" + module_name).lower()
    for token in ("biu", "ciu", "clk", "cpu", "falu", "fpu", "had", "idu", "ifu", "iu", "l2c", "lsu", "mmu", "pad", "plic", "pmu", "rmu", "rtu", "rst", "sysio", "tdt", "vfalu", "vector"):
        if f"/{token}/" in low or module_name.lower().startswith(f"ct_{token}_") or module_name.lower().startswith(f"{token}_"):
            return token
    if "axi" in low:
        return "axi"
    if "apb" in low:
        return "apb"
    if "ahb" in low:
        return "ahb"
    if "uart" in low:
        return "uart"
    return "unknown"


def _infer_role(module: Module) -> str:
    name_text = " ".join([module.name, module.subsystem] + [i.module for i in module.instances] + [i.name for i in module.instances]).lower()
    port_text = " ".join(p.name for p in module.ports).lower()
    module_low = module.name.lower()
    if module.subsystem in {"clk"} or "gated_clk" in module_low or "clk_gen" in module_low or "clock" in module_low:
        return "clocking"
    if module.subsystem in {"rst"} or "reset" in module_low or re.search(r"(^|_)rst(_|$)", module_low):
        return "reset_logic"
    if "axi" in name_text or "ahb" in name_text or "apb" in name_text or any(proto in port_text for proto in ("awvalid", "arvalid", "haddr", "psel", "pready")):
        return "bus_or_protocol_logic"
    if "plic" in name_text or module.subsystem == "plic":
        return "interrupt_logic"
    if module.subsystem in {"l2c"} or "cache" in name_text or "icache" in name_text or "dcache" in name_text or "spsram" in name_text or re.search(r"(^|_)ram(_|$)", name_text):
        return "memory_or_cache"
    if module.instances:
        return "integration_wrapper"
    return "leaf_rtl"
