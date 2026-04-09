"""Metadata writers for the output dataset."""

from __future__ import annotations

import getpass
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def yaml_quote(value: str) -> str:
    """Quote a scalar for YAML output."""
    return json.dumps(value, ensure_ascii=False)


def utc_now_iso() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_runtime_user() -> str:
    """Return the current OS username."""
    return getpass.getuser()


def run_git(args: Sequence[str], cwd: Path) -> str:
    """Run a git command and return stdout on success."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def discover_repo_metadata(script_path: Path) -> dict[str, str]:
    """Discover git repo metadata for the running script."""
    repo_root_str = run_git(["rev-parse", "--show-toplevel"], script_path.parent)
    if not repo_root_str:
        return {
            "repo_remote_url": "",
            "script_repo_relpath": script_path.name,
            "git_commit": "",
        }
    repo_root = Path(repo_root_str)
    remote_url = run_git(["remote", "get-url", "origin"], repo_root)
    if not remote_url:
        remotes = [line.strip() for line in run_git(["remote"], repo_root).splitlines() if line.strip()]
        if remotes:
            remote_url = run_git(["remote", "get-url", remotes[0]], repo_root)

    try:
        relpath = str(script_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        relpath = script_path.name

    return {
        "repo_remote_url": remote_url,
        "script_repo_relpath": relpath,
        "git_commit": run_git(["rev-parse", "HEAD"], repo_root),
    }


def write_run_info_yaml(
    path: Path,
    *,
    source_root: Path,
    text_source_path: Path,
    images_source_path: Path,
    image_labels_source_path: Path,
    output_dir: Path,
    text_output_path: Path,
    images_output_path: Path,
    image_labels_output_path: Path,
    missing_jsonl_path: Path,
    warning_jsonl_path: Path,
    command: str,
    extractor_spec: str,
    normalizer_spec: str,
    formatter_spec: str,
    rewriter_spec: str,
    compact_tables: Sequence[str],
    repo_metadata: dict[str, str],
    timings: dict[str, float],
) -> None:
    lines = [
        "source:",
        f"  dataset_root: {yaml_quote(str(source_root))}",
        f"  text_db: {yaml_quote(str(text_source_path))}",
        f"  images_db: {yaml_quote(str(images_source_path))}",
        f"  image_labels_db: {yaml_quote(str(image_labels_source_path))}",
        "target:",
        f"  output_dir: {yaml_quote(str(output_dir))}",
        f"  text_db: {yaml_quote(str(text_output_path))}",
        f"  images_db: {yaml_quote(str(images_output_path))}",
        f"  image_labels_db: {yaml_quote(str(image_labels_output_path))}",
        f"  missing_jsonl: {yaml_quote(str(missing_jsonl_path))}",
        f"  warning_jsonl: {yaml_quote(str(warning_jsonl_path))}",
        "pipeline:",
        f"  repo_remote_url: {yaml_quote(repo_metadata['repo_remote_url'])}",
        f"  script_repo_relpath: {yaml_quote(repo_metadata['script_repo_relpath'])}",
        f"  command: {yaml_quote(command)}",
        f"  git_commit: {yaml_quote(repo_metadata['git_commit'])}",
        f"  extractor: {yaml_quote(extractor_spec)}",
        f"  normalizer: {yaml_quote(normalizer_spec)}",
        f"  formatter: {yaml_quote(formatter_spec)}",
        f"  rewriter: {yaml_quote(rewriter_spec)}",
        f"  compact_tables: {yaml_quote(','.join(compact_tables))}",
        "timings:",
    ]
    for key, value in timings.items():
        lines.append(f"  {key}: {value:.3f}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_dataset_yaml(
    path: Path,
    *,
    dataset_name: str,
    description: str,
    owner: str,
    source_dataset_name: str,
    text_rows: int,
    text_fields: Sequence[str],
    image_rows: int,
    image_fields: Sequence[str],
    image_label_rows: int,
    image_label_fields: Sequence[str],
    source_root: Path,
    text_source_path: Path,
    images_source_path: Path,
    image_labels_source_path: Path,
    output_dir: Path,
    missing_jsonl_path: Path,
    warning_jsonl_path: Path,
    command: str,
    extractor_spec: str,
    normalizer_spec: str,
    formatter_spec: str,
    rewriter_spec: str,
    repo_metadata: dict[str, str],
) -> None:
    timestamp = utc_now_iso()
    lines = [
        f"name: {dataset_name}",
        f"description: {description}",
        "tags: []",
        f"created_at: {yaml_quote(timestamp)}",
        f"updated_at: {yaml_quote(timestamp)}",
        "owners:",
        f"- {owner}",
        "source:",
        "  upstream:",
        f"  - name: {source_dataset_name}",
        "    relationship: derived_from",
        "modalities:",
        "  text:",
        "    table: text.lance",
        f"    rows: {text_rows}",
        "    fields:",
    ]
    lines.extend(f"    - {field}" for field in text_fields)
    lines.extend(
        [
            "  image:",
            "    table: images.lance",
            f"    rows: {image_rows}",
            "    fields:",
        ]
    )
    lines.extend(f"    - {field}" for field in image_fields)
    lines.extend(
        [
            "    tables:",
            "    - image_labels.lance",
            "  image_labels:",
            "    table: image_labels.lance",
            f"    rows: {image_label_rows}",
            "    fields:",
        ]
    )
    lines.extend(f"    - {field}" for field in image_label_fields)
    lines.extend(
        [
            "artifacts:",
            f"  image_url_missing_jsonl: {yaml_quote(str(missing_jsonl_path))}",
            f"  image_id_unmatched_warning_jsonl: {yaml_quote(str(warning_jsonl_path))}",
            "pipeline:",
            "  steps:",
            "  - name: html_replace_image_url_and_dedup_id",
            "    description: Rewrite HTML image URLs to dataset image refs and dedup image tables",
            "    operation: transform",
            f"    user: {owner}",
            "    config:",
            f"      source_dataset_root: {source_root}",
            f"      source_text_db: {text_source_path}",
            f"      source_images_db: {images_source_path}",
            f"      source_image_labels_db: {image_labels_source_path}",
            f"      output_dir: {output_dir}",
            f"      missing_jsonl: {missing_jsonl_path}",
            f"      warning_jsonl: {warning_jsonl_path}",
            f"      repo_remote_url: {repo_metadata['repo_remote_url']}",
            f"      script_repo_relpath: {repo_metadata['script_repo_relpath']}",
            f"      command: {command}",
            f"      git_commit: {repo_metadata['git_commit']}",
            f"      extractor: {extractor_spec}",
            f"      normalizer: {normalizer_spec}",
            f"      formatter: {formatter_spec}",
            f"      rewriter: {rewriter_spec}",
            f"    inherited_from: {source_dataset_name}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
