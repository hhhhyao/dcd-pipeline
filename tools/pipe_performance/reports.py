"""Simple compare report generation for local pipe performance runs."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Sequence


def load_profiles(paths: Sequence[Path]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for path in paths:
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile.setdefault("profile_path", str(path))
        profiles.append(profile)
    return profiles


def leaderboard(profiles: Sequence[dict[str, Any]], *, baseline_name: str | None = None) -> list[dict[str, Any]]:
    if not profiles:
        return []
    baseline = next((item for item in profiles if item.get("run_name") == baseline_name), profiles[0])
    baseline_seconds = float(baseline.get("total_seconds", 0.0) or 0.0)
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        total = float(profile.get("total_seconds", 0.0) or 0.0)
        improved = baseline_seconds - total
        rows.append({
            "run_name": profile.get("run_name", ""),
            "total_seconds": total,
            "improvement_seconds": improved,
            "improvement_percent": (improved / baseline_seconds * 100.0) if baseline_seconds else 0.0,
            "speedup": (baseline_seconds / total) if total else 0.0,
            "profile_path": profile.get("profile_path", ""),
        })
    rows.sort(key=lambda row: row["total_seconds"])
    return rows


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["run_name", "total_seconds"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_html_report(path: Path, rows: Sequence[dict[str, Any]], *, title: str = "Pipe Performance Compare") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys()) if rows else ["run_name", "total_seconds"]
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers)
        body_rows.append(f"<tr>{cells}</tr>")
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 40px; color: #172033; background: #f7f3ea; }}
    h1 {{ font-size: 28px; margin-bottom: 20px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; box-shadow: 0 18px 60px rgba(23, 32, 51, 0.12); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e8e1d5; text-align: left; }}
    th {{ background: #243447; color: white; position: sticky; top: 0; }}
    tr:hover td {{ background: #fff8e8; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <table>
    <thead><tr>{header_html}</tr></thead>
    <tbody>{"".join(body_rows)}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
