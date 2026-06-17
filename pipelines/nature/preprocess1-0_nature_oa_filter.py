#!/usr/bin/env python3
"""Annotate Nature raw JSONL rows with Open Access compliance signals.

Filtering method
----------------
This helper reads raw crawl rows from one or more ``part*.jsonl`` files and
writes ``{name}_compliance_check.jsonl`` with a per-row ``open_access`` boolean.
The matching ``part*.tar`` is optional and is used only to verify that image
references in the JSONL still point to tar members; tar contents do not affect
the Open Access decision.

The filter is intentionally pattern-aware but not pattern-only. URL patterns are
emitted as ``url_pattern`` so downstream jobs can audit or aggregate the result,
but the same broad pattern can contain both Open Access and restricted Nature
articles. For example, modern ``/articles/s<journal>-<year>-<id>-<check>`` URLs
are often Open Access, yet some still show institution/subscription prompts.

A row is marked ``open_access=true`` only when all of these conditions hold:

1. The URL is on ``nature.com``.
2. The URL path starts with ``/articles/``. Non-article Nature pages such as
   ``/nature-index/...``, volume/issue pages, collections, or careers pages are
   marked false because the article Open Access rule is not applicable.
3. The HTML contains article-level Open Access evidence, such as the article
   metadata badge before the article title, ``publishingModel: Open Access``,
   a rights section headed ``Open Access``, or a Creative Commons license.
4. The HTML does not contain visible full-content restriction prompts such as
   ``Access through your institution``, ``This is a preview of subscription
   content``, ``Buy or subscribe``, ``Subscribe to this journal``, or related
   login/purchase wording.

Two common false positives are deliberately avoided:

- Generic header/footer links such as ``Open access funding`` or footer
  navigation are not treated as article-level Open Access evidence.
- CSS-only class names such as ``app-access-wall__title`` are not treated as
  restriction prompts. The script looks for user-visible access, subscription,
  buy, or login wording instead.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import tarfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


DEFAULT_INPUT = Path("/root/zhouyiren/data/interleaved/nature/web_eng_20260608_sample")

OPEN_ACCESS_SIGNAL_NAMES = (
    "article_identifier_open_access",
    "publishing_model_open_access",
    "rights_section_open_access",
    "creative_commons_license",
)
RESTRICTION_PROMPT_NAMES = (
    "subscription_preview",
    "institution_access",
    "buy_or_subscribe",
    "login_full_content",
)


@dataclass(frozen=True)
class InputJob:
    jsonl_path: Path
    tar_path: Path | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_nature_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "nature.com" or host.endswith(".nature.com")


def is_nature_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return is_nature_url(url) and parsed.path.startswith("/articles/")


def title_from_html(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def article_id(url: str) -> str:
    path = unquote(urlparse(url).path)
    return path.rstrip("/").split("/")[-1] or "/"


def path_family(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    parts = [part for part in path.split("/") if part]
    if is_nature_url(url) and len(parts) >= 2 and parts[0] == "articles":
        return "/articles/<id>"
    if is_nature_url(url) and len(parts) >= 3 and parts[1] == "volumes":
        return f"/{parts[0]}/volumes/..."
    if is_nature_url(url) and parts and parts[0] == "nature-index":
        return "/nature-index/..."
    if is_nature_url(url):
        if not parts:
            return "/"
        return "/" + "/".join(parts[:2]) + ("..." if len(parts) > 2 else "")
    return f"non-nature:{parsed.netloc.lower()}"


def url_pattern(url: str) -> str:
    """Return an auditable broad URL family; this is not the final filter."""
    if not is_nature_article_url(url):
        return path_family(url)

    value = article_id(url)
    if re.fullmatch(r"srep\d+", value):
        return "/articles/srep<digits>"
    if re.fullmatch(r"s\d{5}-\d{3}-\d{5}-\d", value):
        return "/articles/s<journal>-<year>-<id>-<check>"
    if re.fullmatch(r"nature\d+", value):
        return "/articles/nature<digits>"
    if re.fullmatch(r"d\d{5}-\d{3}-\d{5}-\w", value):
        return "/articles/d<news>-<year>-<id>-<check>"
    if re.fullmatch(r"pr\d+", value):
        return "/articles/pr<digits>"
    if re.fullmatch(r"[a-z]+\d+", value):
        return "/articles/<letters><digits>"
    if re.fullmatch(r"\d+[a-z]\d?", value):
        return "/articles/<old-number><letter><suffix>"
    if re.fullmatch(r"\d+", value):
        return "/articles/<digits>"
    if "." in value:
        return "/articles/<journal.code>"
    if "-" in value:
        return "/articles/<other-hyphenated>"
    return "/articles/<other>"


def open_access_signals(html_lower: str) -> list[str]:
    """Find article-level Open Access evidence in already-lowercased HTML.

    The checks intentionally focus on locations tied to the article itself:

    - ``data-test="open-access"`` only counts when it appears before the article
      title, which matches Nature's article identifier block and avoids
      recommendation cards or unrelated links later in the page.
    - ``publishingModel":"Open Access"`` comes from embedded article metadata.
    - ``<b>Open Access</b>`` and Creative Commons wording usually appear in the
      rights/license section for the current article.

    Generic occurrences of "open access" in the site header, footer, or journal
    publishing links are ignored because they do not prove the current article is
    complete and freely available.
    """
    signals: list[str] = []

    open_access_pos = html_lower.find('data-test="open-access"')
    title_positions = [
        html_lower.find('data-test="article-title"'),
        html_lower.find('class="c-article-title"'),
        html_lower.find("<h1"),
    ]
    title_positions = [pos for pos in title_positions if pos >= 0]
    title_pos = min(title_positions) if title_positions else -1
    if open_access_pos >= 0 and title_pos >= 0 and open_access_pos < title_pos:
        signals.append("article_identifier_open_access")

    if '"publishingmodel":"open access"' in html_lower:
        signals.append("publishing_model_open_access")

    if re.search(r"<b>\s*open access\s*</b>", html_lower):
        signals.append("rights_section_open_access")

    if "creative commons" in html_lower and (
        "the author(s)" in html_lower or "open access" in html_lower
    ):
        signals.append("creative_commons_license")

    return signals


def restriction_prompts(html_lower: str) -> list[str]:
    """Find visible prompts that indicate incomplete/full-content-gated pages.

    These phrases are stronger than template artifacts because they are rendered
    user-facing access options or messages. We do not flag bare CSS identifiers
    like ``access-wall`` here; those appeared in many complete Open Access pages
    as shared stylesheet selectors.
    """
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "subscription_preview",
            (
                "this is a preview of subscription content",
                "this is a preview of subscription",
            ),
        ),
        (
            "institution_access",
            (
                "access through your institution",
                "access via your institution",
                "log in via an institution",
            ),
        ),
        (
            "buy_or_subscribe",
            (
                "rent or buy article",
                "buy article pdf",
                "subscribe to this journal",
                "institutional subscriptions",
                "purchase on springerlink",
                "buy or subscribe",
            ),
        ),
        (
            "login_full_content",
            (
                "log in to check access",
                "log in to view this article",
                "sign in to view this article",
                "login to view this article",
            ),
        ),
    )

    found: list[str] = []
    for name, phrases in checks:
        if any(phrase in html_lower for phrase in phrases):
            found.append(name)
    return found


def compliance_status(
    url: str,
    signals: list[str],
    prompts: list[str],
) -> tuple[bool, str]:
    """Combine URL scope, Open Access evidence, and restriction prompts.

    The ordering matters:

    1. Non-Nature rows are false because this helper only models Nature pages.
    2. Nature non-article rows are false because the article Open Access signals
       do not apply to index, volume, collection, or landing pages.
    3. Any visible full-content restriction prompt makes the row false, even if
       an Open Access-looking phrase also appears elsewhere in the HTML.
    4. Missing article-level Open Access evidence makes the row false.
    5. Only Nature article rows with evidence and no restriction prompts become
       ``open_access=true``.
    """
    if not is_nature_url(url):
        return False, "non_nature_url"
    if not is_nature_article_url(url):
        return False, "nature_non_article_url"
    if prompts:
        return False, "full_content_restriction_prompt"
    if not signals:
        return False, "missing_article_open_access_signal"
    return True, "article_open_access_without_restriction_prompt"


def normalize_tar_member(image_file: str, part_name: str) -> str:
    member = image_file.removeprefix("images/")
    prefix = f"{part_name}/"
    if member.startswith(prefix):
        member = member[len(prefix) :]
    return member


def load_tar_members(tar_path: Path | None) -> set[str] | None:
    if tar_path is None or not tar_path.exists():
        return None
    names: set[str] = set()
    with tarfile.open(tar_path) as tar:
        for member in tar:
            if member.isfile():
                names.add(member.name.removeprefix("images/"))
    return names


def iter_jsonl_rows(jsonl_path: Path) -> Iterator[dict[str, object]]:
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{jsonl_path}:{line_number}: invalid JSONL") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{jsonl_path}:{line_number}: expected JSON object")
            yield row


def classify_row(
    row: dict[str, object],
    *,
    source_index: int,
    jsonl_path: Path,
    tar_members: set[str] | None,
) -> dict[str, object]:
    url = str(row.get("url", ""))
    final_url = str(row.get("final_url", ""))
    html = str(row.get("html", ""))
    html_lower = html.lower()

    signals = open_access_signals(html_lower) if is_nature_url(url) else []
    prompts = restriction_prompts(html_lower) if is_nature_url(url) else []
    open_access, status = compliance_status(url, signals, prompts)

    images = row.get("images", [])
    if not isinstance(images, list):
        images = []
    part_name = str(row.get("part", "")) or jsonl_path.stem

    missing_members: list[str] = []
    if tar_members is not None:
        for image in images:
            if not isinstance(image, dict):
                continue
            image_file = str(image.get("image_file", ""))
            if not image_file:
                continue
            member = normalize_tar_member(image_file, part_name)
            if member not in tar_members:
                missing_members.append(image_file)

    parsed = urlparse(url)
    return {
        "source_jsonl": str(jsonl_path),
        "source_index": source_index,
        "url": url,
        "final_url": final_url,
        "domain": parsed.netloc.lower(),
        "title": title_from_html(html),
        "open_access": open_access,
        "status": status,
        "is_nature_url": is_nature_url(url),
        "is_nature_article_url": is_nature_article_url(url),
        "path_family": path_family(url),
        "url_pattern": url_pattern(url),
        "open_access_signals": signals,
        "restriction_prompts": prompts,
        "html_bytes": len(html.encode("utf-8")),
        "image_count": len(images),
        "tar_checked": tar_members is not None,
        "missing_tar_member_count": len(missing_members) if tar_members is not None else None,
        "missing_tar_members": missing_members[:20],
    }


def discover_jobs(input_path: Path, explicit_tar_path: Path | None) -> list[InputJob]:
    input_path = input_path.expanduser()
    if input_path.is_file():
        if input_path.suffix != ".jsonl":
            raise ValueError(f"input file must be JSONL: {input_path}")
        tar_path = explicit_tar_path or input_path.with_suffix(".tar")
        return [InputJob(input_path, tar_path)]

    if not input_path.is_dir():
        raise FileNotFoundError(f"input path does not exist: {input_path}")

    jsonl_paths = sorted(input_path.glob("part*.jsonl"))
    if not jsonl_paths:
        jsonl_paths = sorted(input_path.glob("*.jsonl"))
    if not jsonl_paths:
        raise FileNotFoundError(f"no JSONL files found under {input_path}")
    if explicit_tar_path is not None and len(jsonl_paths) > 1:
        raise ValueError("--tar can only be used with one JSONL input")

    jobs: list[InputJob] = []
    for jsonl_path in jsonl_paths:
        tar_path = explicit_tar_path or jsonl_path.with_suffix(".tar")
        jobs.append(InputJob(jsonl_path, tar_path))
    return jobs


def default_output_name(input_path: Path) -> str:
    if input_path.is_dir():
        return input_path.name
    return input_path.stem


def write_csv_copy(jsonl_output_path: Path, csv_output_path: Path) -> None:
    fields = [
        "source_jsonl",
        "source_index",
        "url",
        "final_url",
        "domain",
        "title",
        "open_access",
        "status",
        "is_nature_url",
        "is_nature_article_url",
        "path_family",
        "url_pattern",
        "open_access_signals",
        "restriction_prompts",
        "html_bytes",
        "image_count",
        "tar_checked",
        "missing_tar_member_count",
        "missing_tar_members",
    ]
    with csv_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in iter_jsonl_rows(jsonl_output_path):
            csv_row = dict(row)
            for key in ("open_access_signals", "restriction_prompts", "missing_tar_members"):
                value = csv_row.get(key, [])
                if isinstance(value, list):
                    csv_row[key] = ";".join(str(item) for item in value)
            writer.writerow(csv_row)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create {name}_compliance_check.jsonl for Nature raw JSONL/TAR data "
            "with an open_access boolean per row."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input directory or part*.jsonl file.",
    )
    parser.add_argument(
        "--tar",
        dest="tar_path",
        type=Path,
        default=None,
        help="Optional tar path for a single JSONL input. Defaults to matching .tar.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to the input directory or JSONL parent.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Output name prefix. Defaults to input directory name or JSONL stem.",
    )
    parser.add_argument(
        "--no-tar-check",
        action="store_true",
        help="Skip checking image_file references against the matching tar.",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Do not write a CSV companion file.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    input_path = args.input.expanduser()
    jobs = discover_jobs(input_path, args.tar_path.expanduser() if args.tar_path else None)
    output_dir = args.output_dir.expanduser() if args.output_dir else (
        input_path if input_path.is_dir() else input_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    output_name = args.name or default_output_name(input_path)
    jsonl_output_path = output_dir / f"{output_name}_compliance_check.jsonl"
    csv_output_path = output_dir / f"{output_name}_compliance_check.csv"
    summary_output_path = output_dir / f"{output_name}_compliance_summary.json"

    status_counts: Counter[str] = Counter()
    pattern_counts: Counter[str] = Counter()
    open_pattern_counts: Counter[str] = Counter()
    restriction_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    total_rows = 0
    tar_checked_jobs = 0
    tar_missing_jobs: list[str] = []

    with jsonl_output_path.open("w", encoding="utf-8") as out:
        for job in jobs:
            tar_members = None
            if not args.no_tar_check:
                tar_members = load_tar_members(job.tar_path)
                if tar_members is None:
                    tar_missing_jobs.append(str(job.tar_path) if job.tar_path else "")
                else:
                    tar_checked_jobs += 1

            for source_index, row in enumerate(iter_jsonl_rows(job.jsonl_path)):
                classified = classify_row(
                    row,
                    source_index=source_index,
                    jsonl_path=job.jsonl_path,
                    tar_members=tar_members,
                )
                out.write(json.dumps(classified, ensure_ascii=False) + "\n")

                total_rows += 1
                status = str(classified["status"])
                pattern = str(classified["url_pattern"])
                status_counts[status] += 1
                pattern_counts[pattern] += 1
                source_counts[str(job.jsonl_path)] += 1
                domain_counts[str(classified["domain"])] += 1
                if classified["open_access"]:
                    open_pattern_counts[pattern] += 1
                for prompt in classified["restriction_prompts"]:
                    restriction_counts[str(prompt)] += 1
                for signal in classified["open_access_signals"]:
                    signal_counts[str(signal)] += 1

    if not args.no_csv:
        write_csv_copy(jsonl_output_path, csv_output_path)

    summary = {
        "created_at": utc_now(),
        "input": str(input_path),
        "jobs": [
            {
                "jsonl_path": str(job.jsonl_path),
                "tar_path": str(job.tar_path) if job.tar_path else None,
            }
            for job in jobs
        ],
        "output_jsonl": str(jsonl_output_path),
        "output_csv": None if args.no_csv else str(csv_output_path),
        "classification_rule": {
            "open_access": (
                "Nature /articles/ URL with article-level Open Access signal "
                "and no visible full-content restriction prompt."
            ),
            "open_access_signals": list(OPEN_ACCESS_SIGNAL_NAMES),
            "restriction_prompts": list(RESTRICTION_PROMPT_NAMES),
            "url_pattern_note": (
                "url_pattern is emitted for audit and downstream filtering; "
                "it is not sufficient by itself because patterns are mixed."
            ),
        },
        "counts": {
            "rows": total_rows,
            "open_access_true": status_counts["article_open_access_without_restriction_prompt"],
            "open_access_false": total_rows
            - status_counts["article_open_access_without_restriction_prompt"],
            "nature_article_rows": sum(
                count
                for status, count in status_counts.items()
                if status
                in {
                    "article_open_access_without_restriction_prompt",
                    "full_content_restriction_prompt",
                    "missing_article_open_access_signal",
                }
            ),
            "tar_checked_jobs": tar_checked_jobs,
            "tar_missing_jobs": tar_missing_jobs,
        },
        "status_counts": dict(status_counts.most_common()),
        "domain_counts": dict(domain_counts.most_common()),
        "all_url_pattern_counts": dict(pattern_counts.most_common()),
        "open_access_url_pattern_counts": dict(open_pattern_counts.most_common()),
        "restriction_prompt_counts": dict(restriction_counts.most_common()),
        "open_access_signal_counts": dict(signal_counts.most_common()),
        "source_row_counts": dict(source_counts.most_common()),
    }
    summary_output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
