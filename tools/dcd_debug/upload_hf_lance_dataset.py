#!/usr/bin/env python3
"""Upload a local Lance dataset to Hugging Face and create a DCD import job."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


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


def git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def dcd_json(
    host: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "codex-dcd-debug/1.0",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(host + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DCD {method} {path} failed: HTTP {exc.code}: {body}") from exc


def upload_to_hf(
    local_dataset: Path,
    hf_repo: str,
    *,
    private: bool,
    path_in_repo: str,
    commit_message: str,
) -> str:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(
        repo_id=hf_repo,
        repo_type="dataset",
        private=private,
        exist_ok=True,
    )
    api.upload_folder(
        repo_id=hf_repo,
        repo_type="dataset",
        folder_path=str(local_dataset),
        path_in_repo=path_in_repo,
        commit_message=commit_message,
    )
    return hf_repo


def create_import_job(
    host: str,
    token: str,
    *,
    hf_repo: str,
    output_dataset: str,
    pipe_slug: str,
    pipe_version: int | None,
    runner_type: str,
    dataset_subdir: str,
    revision: str,
    image_pairing_mode: str,
    include_text: bool,
    include_images: bool,
    validate_duplicate_image_ids: bool,
    text_batch_rows: int,
    image_batch_rows: int,
    image_batch_bytes_mb: int,
    max_text_rows: int,
    max_image_rows: int,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "pipe_slug": pipe_slug,
        "config": {
            "hf_repo": hf_repo,
            "dataset_subdir": dataset_subdir,
            "revision": revision,
            "image_pairing_mode": image_pairing_mode,
            "include_text": include_text,
            "include_images": include_images,
            "validate_duplicate_image_ids": validate_duplicate_image_ids,
            "text_batch_rows": text_batch_rows,
            "image_batch_rows": image_batch_rows,
            "image_batch_bytes_mb": image_batch_bytes_mb,
            "max_text_rows": max_text_rows,
            "max_image_rows": max_image_rows,
        },
    }
    if pipe_version is not None:
        step["pipe_version"] = pipe_version
    payload = {
        "input_dataset": "",
        "output_dataset": output_dataset,
        "runner_type": runner_type,
        "runner_config": {},
        "steps": [step],
    }
    return dcd_json(host, token, "/api/jobs", method="POST", payload=payload)


def poll_job(host: str, token: str, job_id: int, timeout_s: int) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = dcd_json(host, token, f"/api/jobs/runs/{job_id}")
        status = str(last.get("status") or "")
        print(json.dumps({
            "job_id": job_id,
            "status": status,
            "items_in": last.get("items_in"),
            "items_out": last.get("items_out"),
            "error": last.get("error"),
        }, ensure_ascii=False))
        if status in {"done", "error", "cancelled"}:
            return last
        time.sleep(15)
    return last


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a Lance dataset to HF and create a DCD import job.",
    )
    parser.add_argument("--local-dataset", type=Path, required=True)
    parser.add_argument("--hf-repo", required=True)
    parser.add_argument("--dcd-output-dataset", required=True)
    parser.add_argument("--server-info", type=Path, default=ROOT / ".server_info")
    parser.add_argument("--pipe-slug", default="stage0_5_import_hf_lance_dataset")
    parser.add_argument("--pipe-version", type=int, default=1)
    parser.add_argument("--no-pipe-version", action="store_true")
    parser.add_argument("--runner-type", default="local")
    parser.add_argument("--dataset-subdir", default="")
    parser.add_argument("--revision", default="main")
    parser.add_argument(
        "--image-pairing-mode",
        default="id_join",
        choices=["id_join", "row_order"],
    )
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--text-only", action="store_true")
    parser.add_argument("--images-only", action="store_true")
    parser.add_argument("--no-duplicate-image-validation", action="store_true")
    parser.add_argument("--text-batch-rows", type=int, default=1024)
    parser.add_argument("--image-batch-rows", type=int, default=256)
    parser.add_argument("--image-batch-bytes-mb", type=int, default=256)
    parser.add_argument("--max-text-rows", type=int, default=0)
    parser.add_argument("--max-image-rows", type=int, default=0)
    parser.add_argument("--path-in-repo", default=".")
    parser.add_argument("--commit-message", default="upload DCD Lance review dataset")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-job", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=1800)
    parser.add_argument(
        "--result-json",
        type=Path,
        default=None,
        help="Optional path to write the upload/job response JSON.",
    )
    args = parser.parse_args()

    if args.text_only and args.images_only:
        raise ValueError("--text-only and --images-only cannot both be set")

    local_dataset = args.local_dataset.resolve()
    if not (local_dataset / "text.lance").is_dir() and not args.images_only:
        raise FileNotFoundError(f"text.lance not found in {local_dataset}")
    if not args.text_only:
        missing = [
            name
            for name in ("images.lance", "image_labels.lance")
            if not (local_dataset / name).is_dir()
        ]
        if missing:
            raise FileNotFoundError(
                f"{', '.join(missing)} not found in {local_dataset}; use --text-only if intended",
            )

    if not args.skip_upload:
        upload_to_hf(
            local_dataset,
            args.hf_repo,
            private=not args.public,
            path_in_repo=args.path_in_repo,
            commit_message=args.commit_message,
        )

    result: dict[str, Any] = {
        "local_dataset": str(local_dataset),
        "hf_repo": args.hf_repo,
        "dcd_output_dataset": args.dcd_output_dataset,
        "pipe_slug": args.pipe_slug,
        "pipe_version": None if args.no_pipe_version else args.pipe_version,
        "git_hash": git_hash(),
        "uploaded_at_unix": int(time.time()),
    }
    if not args.skip_job:
        host, token = load_server_info(args.server_info)
        result["dcd_host"] = host
        job = create_import_job(
            host,
            token,
            hf_repo=args.hf_repo,
            output_dataset=args.dcd_output_dataset,
            pipe_slug=args.pipe_slug,
            pipe_version=None if args.no_pipe_version else args.pipe_version,
            runner_type=args.runner_type,
            dataset_subdir=args.dataset_subdir,
            revision=args.revision,
            image_pairing_mode=args.image_pairing_mode,
            include_text=not args.images_only,
            include_images=not args.text_only,
            validate_duplicate_image_ids=not args.no_duplicate_image_validation,
            text_batch_rows=args.text_batch_rows,
            image_batch_rows=args.image_batch_rows,
            image_batch_bytes_mb=args.image_batch_bytes_mb,
            max_text_rows=args.max_text_rows,
            max_image_rows=args.max_image_rows,
        )
        result["job"] = job
        if args.poll:
            result["final_job"] = poll_job(
                host,
                token,
                int(job["id"]),
                args.poll_timeout,
            )

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result_json is not None:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
