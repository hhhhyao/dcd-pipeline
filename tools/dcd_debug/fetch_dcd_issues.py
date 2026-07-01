#!/usr/bin/env python3
"""Fetch DCD issues into a local debug cache."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "workspace/dcd_issues_latest"


def load_server_info(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""

    def from_file(name: str) -> str:
        match = re.search(rf"^{name}=\"?([^\"\n]+)\"?", text, re.M)
        return match.group(1).strip() if match else ""

    host = os.environ.get("DCD_HOST") or from_file("DCD_HOST")
    token = (
        os.environ.get("DCD_TOKEN")
        or os.environ.get("DCD_SECRET")
        or from_file("DCD_TOKEN")
        or from_file("DCD_SECRET")
    )
    if not host or not token:
        raise RuntimeError("DCD_HOST and DCD_TOKEN/DCD_SECRET are required")
    return host.rstrip("/"), token


def get_json(host: str, token: str, path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        host + path,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "codex-dcd-debug/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DCD GET {path} failed: HTTP {exc.code}: {body}") from exc


def build_list_path(endpoint: str, params: list[str]) -> str:
    if not params:
        return endpoint
    query = urllib.parse.urlencode(
        [tuple(item.split("=", 1)) for item in params if "=" in item],
    )
    if not query:
        return endpoint
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{query}"


def issue_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if isinstance(payload.get("issues"), list):
        return [item for item in payload["issues"] if isinstance(item, dict)]
    if isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch DCD issues.")
    parser.add_argument("--server-info", type=Path, default=ROOT / ".server_info")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--issues-endpoint", default="/api/issues")
    parser.add_argument("--detail-template", default="/api/issues/{id}")
    parser.add_argument(
        "--query-param",
        action="append",
        default=[],
        help="Query parameter as key=value. May be repeated.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-details", action="store_true")
    args = parser.parse_args()

    host, token = load_server_info(args.server_info)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    list_path = build_list_path(args.issues_endpoint, args.query_param)
    issues = get_json(host, token, list_path)
    items = issue_items(issues)
    if args.limit > 0:
        items = items[: args.limit]
        if isinstance(issues.get("items"), list):
            issues = {**issues, "items": items}

    (output_dir / "issues.json").write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    detail_count = 0
    detail_errors: list[dict[str, str]] = []
    if not args.skip_details:
        for item in items:
            issue_id = str(item.get("id") or "")
            if not issue_id:
                continue
            detail_path = args.detail_template.format(
                id=urllib.parse.quote(issue_id, safe=""),
            )
            try:
                detail = get_json(host, token, detail_path)
            except RuntimeError as exc:
                detail_errors.append({"id": issue_id, "error": str(exc)})
                continue
            (output_dir / f"{issue_id}.json").write_text(
                json.dumps(detail, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            detail_count += 1

    summary = {
        "host": host,
        "output_dir": str(output_dir),
        "issues_endpoint": args.issues_endpoint,
        "detail_template": args.detail_template,
        "query_params": args.query_param,
        "issue_count": len(items),
        "detail_count": detail_count,
        "detail_errors": detail_errors,
        "fetched_at_unix": int(time.time()),
    }
    (output_dir / "fetch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
