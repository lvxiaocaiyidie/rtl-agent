from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


@dataclass(slots=True)
class TableRow:
    source: str
    row_number: int
    sheet: str
    kind: str
    values: dict[str, str]
    raw: dict[str, str]


@dataclass(slots=True)
class TableData:
    path: str
    kind: str
    rows: list[TableRow]
    headers: list[str]


HEADER_ALIASES = {
    "block": {"block", "blk", "module", "mod", "ip", "subsys", "subsystem", "owner", "component"},
    "base_address": {"base", "baseaddr", "base_addr", "baseaddress", "base_address", "base address", "addr_base", "address_base"},
    "offset": {"offset", "reg_offset", "reg offset", "address offset", "addr_offset"},
    "address": {"address", "addr", "absolute_address", "absolute address"},
    "register": {"register", "reg", "reg_name", "reg name", "register_name", "register name", "csr"},
    "field": {"field", "field_name", "field name", "bitfield", "bit field"},
    "bits": {"bit", "bits", "bit_range", "bit range", "range", "msb_lsb"},
    "access": {"access", "sw_access", "sw access", "type", "rw", "permission"},
    "reset": {"reset", "reset_value", "reset value", "default", "default_value"},
    "description": {"description", "desc", "comment", "comments", "note", "notes"},
    "interrupt": {"interrupt", "irq", "intr", "int", "int_name", "interrupt name", "irq_name", "source", "event"},
    "irq_number": {"irq_number", "irq number", "irq_num", "irq num", "irq_id", "int_id", "vector", "vector_id"},
    "signal": {"signal", "signal_name", "signal name", "rtl_signal", "rtl signal", "rtl_name", "rtl name"},
    "source": {"source", "src", "from", "from_signal", "from signal", "producer", "driver", "start"},
    "target": {"target", "dst", "dest", "destination", "to", "to_signal", "to signal", "consumer", "sink", "end"},
    "edge_kind": {"kind", "edge_kind", "edge kind", "relation", "relationship", "type"},
    "master": {"master", "initiator", "src_ip", "source_ip", "host", "requester"},
    "slave": {"slave", "target_ip", "dst_ip", "dest_ip", "device", "responder"},
    "endpoint": {"endpoint", "ep", "noc_endpoint", "noc endpoint", "port", "interface", "if", "intf"},
    "route_id": {"route", "route_id", "route id", "rid", "id", "node_id", "node id"},
    "qos": {"qos", "priority", "vc", "virtual_channel", "virtual channel"},
    "security": {"security", "secure", "sec_attr", "security_attr", "security attribute"},
    "clock": {"clock", "clk", "clk_name", "clock_name", "clock name"},
    "reset_signal": {"reset_signal", "reset signal", "reset_name", "reset name", "rst", "rst_n"},
    "domain": {"domain", "clock_domain", "clock domain", "reset_domain", "reset domain", "power_domain", "power domain"},
    "frequency": {"frequency", "freq", "mhz", "clock_freq", "clock frequency"},
    "polarity": {"polarity", "active", "active_level", "active level", "level"},
    "trigger": {"trigger", "trigger_type", "trigger type", "edge_level", "edge/level"},
    "width": {"width", "data_width", "data width", "bus_width", "bus width"},
    "protocol": {"protocol", "bus", "bus_protocol", "interface_protocol", "axi", "apb", "ahb"},
    "blackbox": {"blackbox", "black_box", "black box", "subsystem", "sub_system", "ip_name", "ip name"},
    "metadata": {"metadata", "meta", "attribute", "attributes", "property", "properties", "value"},
}


def read_table(path: Path, kind: str) -> TableData:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows, headers = _read_delimited(path, ",", kind)
    elif suffix in {".tsv", ".tab"}:
        rows, headers = _read_delimited(path, "\t", kind)
    elif suffix == ".xlsx":
        rows, headers = _read_xlsx(path, kind)
    else:
        raise ValueError(f"unsupported table format: {path}")
    return TableData(path=path.as_posix(), kind=kind, rows=rows, headers=headers)


def canonical_header(header: str) -> str:
    text = _norm_header(header)
    for canonical, aliases in HEADER_ALIASES.items():
        if text in {_norm_header(alias) for alias in aliases}:
            return canonical
    return text


def _read_delimited(path: Path, delimiter: str, kind: str) -> tuple[list[TableRow], list[str]]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    raw_rows = [[cell.strip() for cell in row] for row in reader]
    return _rows_from_matrix(path, kind, path.stem, raw_rows)


def _read_xlsx(path: Path, kind: str) -> tuple[list[TableRow], list[str]]:
    with zipfile.ZipFile(path) as zf:
        shared = _read_shared_strings(zf)
        sheets = _workbook_sheets(zf)
        rows: list[TableRow] = []
        headers: list[str] = []
        for sheet_name, sheet_path in sheets:
            matrix = _read_sheet_matrix(zf, sheet_path, shared)
            sheet_rows, sheet_headers = _rows_from_matrix(path, kind, sheet_name, matrix)
            rows.extend(sheet_rows)
            headers.extend(header for header in sheet_headers if header not in headers)
    return rows, headers


def _rows_from_matrix(path: Path, kind: str, sheet: str, matrix: list[list[str]]) -> tuple[list[TableRow], list[str]]:
    header_index = _find_header_row(matrix)
    if header_index is None:
        return [], []
    headers = [cell.strip() for cell in matrix[header_index]]
    canonical = [canonical_header(header) for header in headers]
    rows: list[TableRow] = []
    for row_offset, row in enumerate(matrix[header_index + 1 :], header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        raw = {headers[idx]: padded[idx].strip() for idx in range(len(headers)) if headers[idx].strip()}
        values: dict[str, str] = {}
        for idx, key in enumerate(canonical):
            if idx >= len(padded):
                continue
            value = padded[idx].strip()
            if value and key:
                values[key] = value
        rows.append(TableRow(path.as_posix(), row_offset, sheet, kind, values, raw))
    return rows, headers


def _find_header_row(matrix: list[list[str]]) -> int | None:
    best_idx = None
    best_score = 0
    known = set().union(*({_norm_header(alias) for alias in aliases} for aliases in HEADER_ALIASES.values()))
    for idx, row in enumerate(matrix[:20]):
        cells = [_norm_header(cell) for cell in row if cell.strip()]
        score = sum(1 for cell in cells if cell in known)
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx if best_score >= 2 else None


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall(".//{*}si"):
        strings.append("".join(t.text or "" for t in si.findall(".//{*}t")))
    return strings


def _workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("{*}Relationship")}
    sheets = []
    for sheet in workbook.findall(".//{*}sheet"):
        name = sheet.attrib.get("name", "Sheet")
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        target = rel_map.get(rel_id, "")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("/")
        sheets.append((name, path.replace("\\", "/")))
    return sheets


def _read_sheet_matrix(zf: zipfile.ZipFile, sheet_path: str, shared: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//{*}sheetData/{*}row"):
        values: dict[int, str] = {}
        for cell in row.findall("{*}c"):
            ref = cell.attrib.get("r", "")
            col_idx = _column_index(ref)
            values[col_idx] = _cell_value(cell, shared)
        if values:
            max_col = max(values)
            rows.append([values.get(idx, "") for idx in range(max_col + 1)])
    return rows


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    if cell.attrib.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//{*}t")).strip()
    value = cell.find("{*}v")
    if value is None or value.text is None:
        return ""
    text = value.text.strip()
    if cell.attrib.get("t") == "s":
        try:
            return shared[int(text)].strip()
        except (ValueError, IndexError):
            return text
    return text


def _column_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref.upper())
    if not letters:
        return 0
    idx = 0
    for char in letters.group(1):
        idx = idx * 26 + (ord(char) - ord("A") + 1)
    return idx - 1


def _norm_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def row_source(row: TableRow) -> str:
    return f"{row.source}:{row.sheet}:row{row.row_number}"


def row_value(row: TableRow, *keys: str) -> str:
    for key in keys:
        value = row.values.get(key, "").strip()
        if value:
            return value
    return ""


def parse_int(value: str) -> int | None:
    text = value.strip().replace("_", "")
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def to_hex(value: int | None) -> str:
    return "" if value is None else f"0x{value:X}"


def table_summary(table: TableData) -> dict[str, Any]:
    return {"path": table.path, "kind": table.kind, "rows": len(table.rows), "headers": table.headers}
