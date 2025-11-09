"""
Filter cleanup_report.json/csv by excluding paths listed in output/archive_candidates.txt
Writes output/cleanup_report.filtered.csv and output/cleanup_report.filtered.json

Usage (project root):
    python -m tools.filter_cleanup_report
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
REPORT_JSON = OUT / "cleanup_report.json"
REPORT_CSV = OUT / "cleanup_report.csv"
ARCH_LIST = OUT / "archive_candidates.txt"

if not REPORT_JSON.exists():
    print("Missing:", REPORT_JSON)
    raise SystemExit(1)

arch = set()
if ARCH_LIST.exists():
    for line in ARCH_LIST.read_text(encoding = "utf8").splitlines():
        s = line.strip()
        if s:
            # normalize path separators
            arch.add(s.replace("/", "\\"))

with REPORT_JSON.open("r", encoding = "utf8") as f:
    data = json.load(f)
rows = data.get("rows", [])

filtered = []
for r in rows:
    p = r.get("path", "")
    p_norm = p.replace("/", "\\")
    if p_norm in arch:
        continue
    # also skip anything under 'archive/' or '_site/' explicitly
    if p_norm.startswith("archive\\") or p_norm.startswith("_site\\"):
        continue
    filtered.append(r)

# write CSV
csvp = OUT / "cleanup_report.filtered.csv"
with csvp.open("w", encoding = "utf8", newline = "") as cf:
    writer = csv.DictWriter(
            cf, fieldnames = ["path", "size", "sha1", "category", "notes"]
            )
    writer.writeheader()
    for r in filtered:
        writer.writerow(
                {k: r.get(k, "") for k in ["path", "size", "sha1", "category", "notes"]}
                )

# write JSON
jsonp = OUT / "cleanup_report.filtered.json"
with jsonp.open("w", encoding = "utf8") as jf:
    json.dump({"rows": filtered, "meta": data.get("extra", {})}, jf, indent = 2)

print(f"Wrote filtered reports: {csvp} ({len(filtered)} rows)")
