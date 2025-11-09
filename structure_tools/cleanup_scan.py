"""
cleanup_scan.py

A lightweight scanner to identify candidate files for archival in the repository.
It does not delete anything. Instead, it writes a CSV and JSON report to `output/cleanup_report.*`.

Usage (project root):
    python -m tools.cleanup_scan

Report contents (CSV): path,size_bytes,sha1,category,notes
- category values: entrypoint, reachable, unreferenced_python, unreferenced_quarto_md_html, duplicate_same_basename

This script intentionally avoids touching any files; user reviews the CSV before running an archival/move script.

NOTE: Keep this file English (project files must be English).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {".venv", "venv", "__pycache__", "output", "archive", "backup", "packrat", "node_modules", ".git", }
# Optional file with explicit paths to exclude (one per line, relative to project root)
ARCHIVE_EXCLUDE_FILE = ROOT / "output" / "archive_candidates.txt"
ARCHIVE_EXCLUDES: set[str] = set()
if ARCHIVE_EXCLUDE_FILE.exists():
    try:
        for L in ARCHIVE_EXCLUDE_FILE.read_text(encoding = "utf8").splitlines():
            s = L.strip()
            if not s:
                continue
            # normalize separators to backslashes and remove leading ./ or / if present
            s2 = s.replace("/", "\\").lstrip(".\\/")
            ARCHIVE_EXCLUDES.add(s2)
    except Exception:
        ARCHIVE_EXCLUDES = set()

PY_EXT = ".py"
Q_EXTS = {".qmd", ".qmd.txt", ".md", ".markdown_docs"}

ENTRYPOINT_PATTERNS = ["run_", "runfull", "run-full", "run", "main.py", "cli.py", "flow_pipeline/run_",
                       "run_full_analysis.py", ]

IMPORT_RE = re.compile(r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")


def sha1_of_file(path: Path) -> str:
    """
    Compute the SHA1 hash of the given file.

    :param path: Path
        Path to file to compute hash of

    :returns: str
        SHA1 hash of the file as a hexadecimal string

    This function reads the file in 8192-byte chunks and updates the SHA1 hash
    object accordingly. The file is read in binary mode to avoid any text
    encoding issues.
    """
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_excluded(path: Path) -> bool:
    # Exclude by directory names (existing behavior)
    """
     Return True if the given path should be excluded from the cleanup scan.

     Exclusion happens in two steps:

     1. If the path contains any directory names listed in `EXCLUDE_DIRS`, the path is excluded.
     2. If the relative path (from the project root) matches any explicit paths listed in `ARCHIVE_EXCLUDES` (either
     exactly or as a prefix), the
    path is excluded.

     :param path: Path - Path to file to check for exclusion
     :returns: bool - True if the path should be excluded, False otherwise
    """
    parts = {p for p in path.parts}
    if bool(parts & EXCLUDE_DIRS):
        return True
    # Also exclude any explicit paths listed in ARCHIVE_EXCLUDES
    try:
        rel = str(path.relative_to(ROOT)).replace("/", "\\")
    except Exception:
        rel = str(path)
    # Exact match or prefix match (exclude directories listed)
    for ex in ARCHIVE_EXCLUDES:
        if rel == ex or rel.startswith(ex + "\\"):
            return True
    return False


def collect_files(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            if is_excluded(p):
                continue
            if p.suffix == ".py" or p.suffix in Q_EXTS:
                out.append(p)
    return out


def parse_imports_from_py(path: Path) -> set[str]:
    names = set()
    try:
        text = path.read_text(encoding = "utf8", errors = "ignore")
    except Exception:
        return names
    for line in text.splitlines():
        m = IMPORT_RE.match(line.strip())
        if m:
            mod = m.group(1) or m.group(2)
            if mod:
                base = mod.split(".")[0]
                names.add(base)
    return names


def map_module_to_file(py_files: list[Path]) -> dict[str, Path]:
    mapping = {}
    for p in py_files:
        name = p.stem
        if name == "__init__":
            # use parent package name
            name = p.parent.name
        if name in mapping:
            # keep first; duplicates ok
            continue
        mapping[name] = p
    return mapping


def find_entrypoints(all_files: list[Path]) -> set[Path]:
    eps = set()
    for p in all_files:
        # simple heuristics: file in project root with run_/main/cli or scripts in flow_pipeline/run_
        rel = p.relative_to(ROOT)
        rp = str(rel).lower()
        for pat in ENTRYPOINT_PATTERNS:
            if pat in rp:
                eps.add(p)
                break
    # also include top-level main.py if present
    m = ROOT / "main.py"
    if m.exists():
        eps.add(m)
    return eps


def build_import_graph(
        py_files: list[Path], mapping: dict[str, Path]
        ) -> dict[Path, set[Path]]:
    graph: dict[Path, set[Path]] = {p: set() for p in py_files}
    for p in py_files:
        imports = parse_imports_from_py(p)
        for mod in imports:
            if mod in mapping:
                graph[p].add(mapping[mod])
    return graph


def reachable_from(entrypoints: set[Path], graph: dict[Path, set[Path]]) -> set[Path]:
    visited = set()
    stack = list(entrypoints)
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for nxt in graph.get(cur, []):
            if nxt not in visited:
                stack.append(nxt)
    return visited


def find_duplicate_basenames(files: list[Path]) -> dict[str, list[Path]]:
    byname: dict[str, list[Path]] = {}
    for p in files:
        key = p.stem.lower()
        byname.setdefault(key, []).append(p)
    return {k: v for k, v in byname.items() if len(v) > 1}


def scan() -> tuple[list[dict], dict]:
    all_files = collect_files(ROOT)
    py_files = [p for p in all_files if p.suffix == PY_EXT]
    q_files = [p for p in all_files if p.suffix in Q_EXTS]

    mapping = map_module_to_file(py_files)
    graph = build_import_graph(py_files, mapping)
    entrypoints = find_entrypoints(all_files)
    reachable = reachable_from(entrypoints, graph)

    dup = find_duplicate_basenames(all_files)

    report_rows = []
    for p in all_files:
        rel = str(p.relative_to(ROOT))
        size = p.stat().st_size
        sha1 = sha1_of_file(p)
        category = "unknown"
        notes = ""
        if p in entrypoints:
            category = "entrypoint"
        elif p.suffix == PY_EXT and p in reachable:
            category = "reachable"
        elif p.suffix == PY_EXT and p not in reachable:
            category = "unreferenced_python"
        elif p.suffix in Q_EXTS:
            # search repo for references to this filename
            # quick search: check if filename appears in any .py file
            fname = p.name
            found = False
            for py in py_files:
                try:
                    if fname in py.read_text(encoding = "utf8", errors = "ignore"):
                        found = True
                        break
                except Exception:
                    continue
            category = ("referenced_quarto_md_html" if found else "unreferenced_quarto_md_html")
        if p.stem.lower() in dup:
            notes = "duplicate_basename"
            category = "duplicate_same_basename"
        report_rows.append(
                {"path": rel, "size": size, "sha1": sha1, "category": category, "notes": notes, }
                )

    meta = {"root": str(ROOT), "total_files_scanned": len(all_files), "total_python": len(py_files),
            "total_quarto_md_html": len(q_files), }
    return report_rows, {"meta": meta,
                         "duplicates": {k: [str(x.relative_to(ROOT)) for x in v] for k, v in dup.items()}, }


def write_reports(rows: list[dict], extra: dict):
    outdir = ROOT / "output"
    outdir.mkdir(exist_ok = True)
    csvp = outdir / "cleanup_report.csv"
    jsonp = outdir / "cleanup_report.json"
    with csvp.open("w", newline = "", encoding = "utf8") as f:
        writer = csv.DictWriter(
                f, fieldnames = ["path", "size", "sha1", "category", "notes"]
                )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    with jsonp.open("w", encoding = "utf8") as f:
        json.dump({"rows": rows, "extra": extra}, f, indent = 2)
    print(f"Wrote cleanup reports to: {csvp} and {jsonp}")


if __name__ == "__main__":
    # CLI: allow passing extra excludes via --exclude and/or --exclude-file
    import argparse

    parser = argparse.ArgumentParser(
            description = "Run cleanup scan with optional excludes"
            )
    parser.add_argument(
            "--exclude", "-e", action = "append",
            help = "Explicit path to exclude (relative to project root). Can be repeated.", )
    parser.add_argument(
            "--exclude-file", "-f", action = "append",
            help = "Path to file containing exclude paths (one per line). Can be repeated.", )
    parser.add_argument(
            "--exclude-folder", "-d", action = "append",
            help = "Path to folder to exclude (relative to project root). Can be repeated.", )
    args = parser.parse_args()


    def _add_exclude(s: str):
        s2 = s.replace("/", "\\").lstrip(".\\/")
        ARCHIVE_EXCLUDES.add(s2)


    # Load excludes provided on command line
    if args.exclude:
        for ex in args.exclude:
            if ex:
                _add_exclude(ex)
    # Load exclude-folders: ensure folder prefix form without trailing separator
    if args.exclude_folder:
        for df in args.exclude_folder:
            if not df:
                continue
            s = df.replace("/", "\\").lstrip(".\\/")
            # normalize to folder prefix (no trailing backslash)
            s = s.rstrip("\\/")
            if s:
                ARCHIVE_EXCLUDES.add(s)
    if args.exclude_file:
        for ef in args.exclude_file:
            try:
                pth = Path(ef)
                if not pth.is_absolute():
                    pth = ROOT / ef
                if pth.exists():
                    for L in pth.read_text(encoding = "utf8").splitlines():
                        if L.strip():
                            _add_exclude(L.strip())
            except Exception:
                # ignore problematic exclude-file entries
                continue

    rows, extra = scan()
    write_reports(rows, extra)
    print(
            "Scan complete. Review output/cleanup_report.csv before running any archival commands."
            )
