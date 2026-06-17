#!/usr/bin/env python3
"""Sample portal URLs and audit whether static HTML appears complete."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import http.client
import io
import json
import random
import re
import sys
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_SUMMARY_URL = (
    "https://huggingface.co/datasets/racheltechie/202606_web_scan/raw/main/docs/summary.md"
)
DEFAULT_HF_RESOLVE_BASE = "https://huggingface.co/datasets/racheltechie/202606_web_scan/resolve/main"
DEFAULT_OUTPUT_DIR = Path("workspace/202606_web_scan_portal_completeness")
USER_AGENT = (
    "dcd-pipeline-portal-completeness-audit/0.1 "
    "(static HTML completeness sampling; +https://huggingface.co/datasets/racheltechie/202606_web_scan)"
)

SKIP_EXTENSIONS = (
    ".7z",
    ".avi",
    ".avif",
    ".bmp",
    ".bz2",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rss",
    ".svg",
    ".tar",
    ".tgz",
    ".tif",
    ".tiff",
    ".tsv",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}
LANGUAGE_PREFIXES = {
    "ar",
    "de",
    "en",
    "es",
    "fr",
    "pt",
    "ru",
    "zh",
}

REASON_LABELS = OrderedDict(
    [
        ("robots_disallowed", "robots 禁止抓取"),
        ("network_error", "网络或请求错误"),
        ("http_error", "HTTP 错误"),
        ("access_denied", "访问被拒绝"),
        ("bot_challenge", "机器人/验证码挑战"),
        ("login_required", "需要登录"),
        ("registration_required", "需要注册账号"),
        ("membership_or_subscription_required", "需要会员/订阅/购买"),
        ("javascript_render_required", "需要 JavaScript 渲染"),
        ("non_html_content", "非 HTML 内容"),
        ("low_text_content", "静态正文过短"),
    ]
)
LOGIN_MECHANISM_REASONS = {
    "login_required",
    "registration_required",
    "membership_or_subscription_required",
}

GENERIC_NON_CONTENT_LAST_SEGMENTS = {
    "about",
    "about-us",
    "advertising",
    "archive",
    "archives",
    "browse",
    "contact",
    "contacts",
    "download",
    "editors",
    "events",
    "explorers",
    "faq",
    "gallery",
    "help",
    "index",
    "journal-information",
    "login",
    "open-access",
    "privacy",
    "search",
    "sitemap",
    "subscribe",
    "support",
    "terms",
    "terms-of-use",
    "videos",
    "visit",
}
BRITANNICA_CONTENT_PREFIXES = {
    "animal",
    "art",
    "biography",
    "dictionary",
    "event",
    "list",
    "literature",
    "money",
    "place",
    "plant",
    "question",
    "science",
    "sports",
    "story",
    "technology",
    "topic",
}
WORLD_BANK_CONTENT_PREFIXES = {
    "country",
    "indicator",
    "income-level",
    "region",
    "topic",
}
WHO_CONTENT_PREFIXES = {
    "campaigns",
    "emergencies",
    "health-topics",
    "news",
    "news-room",
    "publications",
}
SMITHSONIAN_CONTENT_PREFIXES = {
    "article",
    "articles",
    "collection",
    "collections",
    "event",
    "events",
    "exhibition",
    "exhibitions",
    "object",
    "objects",
    "sidedoor",
    "spotlight",
    "stories",
    "story",
    "webcams",
}

CHALLENGE_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"attention required[^.]{0,80}cloudflare",
        r"checking your browser",
        r"verify you are human",
        r"cf-browser-verification",
        r"\bcaptcha\b",
        r"security check",
        r"please enable cookies",
    ]
]
LOGIN_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"\b(?:sign|log)\s*in\s+to\s+(?:continue|view|read|access|see)",
        r"\bto\s+(?:continue|view|read|access|see)[^.\n]{0,80}\b(?:sign|log)\s*in\b",
        r"\blogin\s+required\b",
        r"\bsign\s*in\s+required\b",
        r"\brequires?\s+(?:a\s+)?(?:login|sign\s*in|account)\b",
        r"登录后(?:查看|阅读|继续|访问)",
        r"请先登录",
    ]
]
REGISTRATION_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"\bregister\s+(?:for|to)\s+(?:continue|view|read|access|see)",
        r"\bcreate\s+(?:a\s+)?(?:free\s+)?account\s+to\s+(?:continue|view|read|access|see)",
        r"注册(?:会员|账号|账户).{0,20}(?:查看|阅读|继续|访问)",
        r"(?:查看|阅读|继续|访问).{0,20}注册(?:会员|账号|账户)",
    ]
]
PAYWALL_STRONG_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"\bsubscribe\s+to\s+(?:continue|view|read|access|see)",
        r"\bsubscription\s+required\b",
        r"\bfor\s+subscribers\s+only\b",
        r"\bavailable\s+to\s+subscribers\b",
        r"\bthis\s+article\s+is\s+(?:only\s+)?available\s+to\s+subscribers\b",
        r"\byou\s+have\s+reached\s+your\s+(?:free\s+)?article\s+limit\b",
        r"\bpremium\s+content\b",
        r"\bmember(?:ship)?\s+required\b",
        r"\bpreview\s+of\s+subscription\s+content\b",
        r"\baccess\s+options\b",
        r"\bget\s+full\s+access\b",
        r"\blog\s*in\s+via\s+(?:an\s+)?institution\b",
        r"\binstitutional\s+(?:login|access)\b",
        r"\bsubscribe\s+to\s+(?:this\s+)?journal\b",
        r"会员(?:专享|专属|内容|阅读)",
        r"订阅后(?:查看|阅读|继续|访问)",
        r"付费(?:阅读|内容)",
    ]
]
PAYWALL_WEAK_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"\baccess\s+through\s+your\s+institution\b",
        r"\baccess\s+via\s+your\s+institution\b",
        r"\bpurchase\s+access\b",
        r"\brent\s+or\s+buy\b",
        r"\bbuy\s+(?:article|this article|now)\b",
    ]
]
JAVASCRIPT_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"enable javascript",
        r"requires javascript",
        r"javascript is disabled",
        r"please turn javascript on",
        r"you need to enable javascript",
        r"id=[\"']__next[\"'][^>]*>\s*</div>",
        r"id=[\"']root[\"'][^>]*>\s*</div>",
    ]
]


@dataclass(frozen=True)
class Site:
    name: str
    base_url: str
    run_id: str
    status: str
    inventory_url_count: int
    manifest_record_count: int
    robots_status: str
    notes: str

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass(frozen=True)
class FetchResponse:
    url: str
    final_url: str
    status: int | None
    headers: dict[str, str]
    data: bytes
    error: str | None
    truncated: bool

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400 and self.error is None


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "canvas"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "area"}:
            return
        attrs_dict = {name.lower(): value for name, value in attrs if value}
        href = attrs_dict.get("href")
        if href:
            self.links.append(href)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "site"


def parse_count(value: str) -> int:
    value = value.replace(",", "").strip()
    return int(value) if value else 0


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_summary_sites(markdown_text: str) -> list[Site]:
    sites: list[Site] = []
    for line in markdown_text.splitlines():
        line = line.strip()
        if not line.startswith("| ["):
            continue
        cells = markdown_cells(line)
        if len(cells) < 8:
            continue
        site_match = re.match(r"\[([^\]]+)\]\((https?://[^)]+)\)", cells[0])
        run_match = re.search(r"`([^`]+)`", cells[2])
        if not site_match or not run_match:
            continue
        sites.append(
            Site(
                name=site_match.group(1).strip(),
                base_url=site_match.group(2).strip(),
                run_id=run_match.group(1).strip(),
                status=cells[3],
                inventory_url_count=parse_count(cells[4]),
                manifest_record_count=parse_count(cells[5]),
                robots_status=cells[6].strip("`"),
                notes=cells[7],
            )
        )
    return sites


def detect_charset(headers: dict[str, str]) -> str:
    content_type = ""
    for key, value in headers.items():
        if key.lower() == "content-type":
            content_type = value
            break
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if match:
        return match.group(1).strip("\"'")
    return "utf-8"


def decode_bytes(data: bytes, headers: dict[str, str]) -> str:
    charset = detect_charset(headers)
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def maybe_decompress(data: bytes, headers: dict[str, str]) -> bytes:
    encoding = ""
    for key, value in headers.items():
        if key.lower() == "content-encoding":
            encoding = value.lower()
            break
    if encoding == "gzip":
        try:
            return gzip.decompress(data)
        except OSError:
            return data
    return data


def fetch_url(
    url: str,
    *,
    timeout: float,
    retries: int,
    accept: str,
    max_bytes: int | None = None,
) -> FetchResponse:
    last: FetchResponse | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                    "User-Agent": USER_AGENT,
                },
            )
            with urlopen(request, timeout=timeout) as response:
                try:
                    raw = response.read(max_bytes + 1 if max_bytes else -1)
                    read_error = None
                except http.client.IncompleteRead as exc:
                    raw = exc.partial
                    read_error = f"IncompleteRead: expected_more_after_{len(raw)}_bytes"
                truncated = bool(max_bytes is not None and len(raw) > max_bytes)
                if truncated:
                    raw = raw[:max_bytes]
                headers = dict(response.headers.items())
                data = maybe_decompress(raw, headers)
                return FetchResponse(
                    url=url,
                    final_url=response.geturl(),
                    status=response.status,
                    headers=headers,
                    data=data,
                    error=read_error,
                    truncated=truncated,
                )
        except HTTPError as exc:
            raw = exc.read(max_bytes + 1 if max_bytes else -1)
            truncated = bool(max_bytes is not None and len(raw) > max_bytes)
            if truncated:
                raw = raw[:max_bytes]
            headers = dict(exc.headers.items()) if exc.headers else {}
            last = FetchResponse(
                url=url,
                final_url=exc.geturl(),
                status=exc.code,
                headers=headers,
                data=maybe_decompress(raw, headers),
                error=f"HTTPError: {exc.reason}",
                truncated=truncated,
            )
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                return last
        except (URLError, TimeoutError, OSError) as exc:
            last = FetchResponse(
                url=url,
                final_url=url,
                status=None,
                headers={},
                data=b"",
                error=repr(exc),
                truncated=False,
            )
        if attempt < retries:
            time.sleep(0.8 * (attempt + 1))
    assert last is not None
    return last


def fetch_text(url: str, *, timeout: float, retries: int, max_bytes: int = 1_500_000) -> str:
    response = fetch_url(
        url,
        timeout=timeout,
        retries=retries,
        accept="text/plain,text/markdown,text/html;q=0.8,*/*;q=0.1",
        max_bytes=max_bytes,
    )
    if response.status is None or response.status >= 400:
        raise RuntimeError(f"failed to fetch {url}: status={response.status} error={response.error}")
    return decode_bytes(response.data, response.headers)


def normalize_page_url(raw_url: str, *, keep_query: bool = True) -> str | None:
    raw_url = html.unescape(raw_url).strip()
    if not raw_url or raw_url.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "blob:")):
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path or "/"
    if path.lower().endswith(SKIP_EXTENSIONS):
        return None
    query = parsed.query if keep_query else ""
    if query:
        pairs = [
            (key, value)
            for key, value in parse_qsl(query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
        ]
        query = urlencode(pairs, doseq=True)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))


def same_site(url: str, base_url: str) -> bool:
    host = urlparse(url).netloc.lower()
    base_host = urlparse(base_url).netloc.lower()
    if host == base_host:
        return True
    stripped = base_host[4:] if base_host.startswith("www.") else base_host
    return host == stripped or host.endswith(f".{stripped}")


def path_segments(url: str) -> list[str]:
    return [segment for segment in urlparse(url).path.strip("/").split("/") if segment]


def path_last_segment(url: str) -> str:
    segments = path_segments(url)
    if not segments:
        return ""
    return segments[-1].lower().removesuffix(".html").removesuffix(".htm")


def hyphen_count(value: str) -> int:
    return value.count("-")


def looks_like_long_slug(value: str, *, min_hyphens: int = 2) -> bool:
    value = value.lower().removesuffix(".html").removesuffix(".htm")
    if value in GENERIC_NON_CONTENT_LAST_SEGMENTS:
        return False
    if re.match(r"^(?:index|page|node)_?\d*$", value):
        return False
    return hyphen_count(value) >= min_hyphens and len(value) >= 12


def china_daily_content_path(path: str) -> bool:
    lowered = path.lower()
    if "node_" in lowered or "/index" in lowered or re.search(r"/\d{2}(?:ad|index)_", lowered):
        return False
    if re.search(r"/a/\d{6}/\d{2}/ws[0-9a-z]+\.html?$", lowered):
        return True
    if re.search(r"/(?:19|20)\d{2}-\d{2}/\d{2}/content_\d+\.html?$", lowered):
        return True
    return False


def is_content_page_url(site: Site, url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"
    lowered_path = path.lower()
    segments = path_segments(url)
    if not segments:
        return False
    first = segments[0].lower()
    last = path_last_segment(url)
    if last in GENERIC_NON_CONTENT_LAST_SEGMENTS:
        return False
    if any(segment.lower() in {"sitemap", "search", "login", "signin", "register"} for segment in segments):
        return False

    slug = site.slug
    if slug == "nature":
        return bool(re.match(r"^/articles/[a-z0-9][a-z0-9._-]*$", lowered_path))

    if slug == "britannica":
        return first in BRITANNICA_CONTENT_PREFIXES and len(segments) >= 2

    if slug == "world_bank_data":
        return first in WORLD_BANK_CONTENT_PREFIXES and len(segments) >= 2

    if slug == "our_world_in_data":
        excluded = {
            "about",
            "donate",
            "explorers",
            "funding",
            "grapher",
            "sdg-tracker",
            "search",
            "team",
            "teaching-notes",
        }
        return first not in excluded and len(segments) == 1 and len(last) >= 5

    if slug == "china_daily":
        return china_daily_content_path(path)

    if slug == "who":
        if first in LANGUAGE_PREFIXES and len(segments) > 1:
            effective_path = "/" + "/".join(segments[1:]).lower()
        else:
            effective_path = lowered_path
        if effective_path.startswith("/news/item/"):
            return len(segments) >= 3
        if effective_path.startswith("/news-room/fact-sheets/detail/"):
            return len(segments) >= 4
        if effective_path.startswith("/news-room/questions-and-answers/item/"):
            return len(segments) >= 4
        if effective_path.startswith("/publications/i/item/"):
            return len(segments) >= 4
        if effective_path.startswith("/director-general/speeches/detail/"):
            return len(segments) >= 4
        if effective_path.startswith("/activities/") and len(segments) >= 2:
            return looks_like_long_slug(last, min_hyphens=1)
        if effective_path.startswith("/emergencies/disease-outbreak-news/item/"):
            return len(segments) >= 4
        if first in WHO_CONTENT_PREFIXES:
            if "/news/item/" in lowered_path and re.search(r"/\d{4}-\d{2}-\d{2}-", lowered_path):
                return True
        return False

    if slug == "smithsonian":
        host = parsed.netloc.lower()
        if host.startswith("secure."):
            return False
        if any(
            segment.lower() in {"donate", "membership", "overview", "passes", "support", "tickets"}
            for segment in segments
        ):
            return False
        if first in SMITHSONIAN_CONTENT_PREFIXES and len(segments) >= 2:
            return True
        if first in {"visit", "about", "support", "learn", "shop", "privacy", "contacts", "myvisit"}:
            return False
        if re.fullmatch(r"\d{6,}", last) and len(segments) >= 2:
            return True
        return len(segments) >= 2 and looks_like_long_slug(last, min_hyphens=1)

    if slug == "nasa":
        if any(fragment in lowered_path for fragment in {"downloadable-content", "resources-archive", "quiz-results"}):
            return False
        if first in {"about", "about-us", "contact", "missions", "mission", "galleries"} and len(segments) <= 2:
            return False
        if re.search(r"/(?:news|image-article|missions?|humans-in-space|science-research)/", lowered_path):
            return len(segments) >= 2
        return looks_like_long_slug(last, min_hyphens=2) or bool(re.search(r"(?:19|20)\d{2}", last))

    if slug == "noaa":
        if first in {"about", "contact", "contacts", "help", "photo-contest"} and len(segments) <= 2:
            return False
        if re.search(r"/(?:news|news-release|stories|our-impact)/", lowered_path):
            return len(segments) >= 2 and last not in {"news", "stories", "our-impact"}
        return looks_like_long_slug(last, min_hyphens=2)

    return looks_like_long_slug(last, min_hyphens=2)


def bucket_for_url(url: str) -> str:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    host = parsed.netloc.lower()
    if not segments:
        return f"{host}/"
    first = segments[0].lower()
    if first in LANGUAGE_PREFIXES and len(segments) > 1:
        return f"{host}/{first}/{segments[1].lower()}"
    if first == "a" and len(segments) > 1 and re.match(r"^\d{4,8}$", segments[1]):
        return f"{host}/a/{segments[1][:4]}"
    if re.match(r"^\d{4}$", first):
        return f"{host}/{first}"
    if first in {"article", "articles"}:
        return f"{host}/{first}"
    return f"{host}/{first}"


def balanced_draw(
    bucket_samples: dict[str, list[str]],
    *,
    sample_size: int,
    rng: random.Random,
) -> list[str]:
    buckets = [bucket for bucket, values in bucket_samples.items() if values]
    for values in bucket_samples.values():
        rng.shuffle(values)
    rng.shuffle(buckets)

    selected: list[str] = []
    selected_set: set[str] = set()
    while buckets and len(selected) < sample_size:
        next_buckets: list[str] = []
        for bucket in buckets:
            values = bucket_samples[bucket]
            while values and values[-1] in selected_set:
                values.pop()
            if not values:
                continue
            url = values.pop()
            selected.append(url)
            selected_set.add(url)
            if values:
                next_buckets.append(bucket)
            if len(selected) >= sample_size:
                break
        buckets = next_buckets
        rng.shuffle(buckets)
    return selected


def stratified_sample_urls(
    urls: Iterable[str],
    *,
    sample_size: int,
    seed: int,
    site: Site | None = None,
    require_content: bool = False,
    reservoir_per_bucket: int | None = None,
) -> tuple[list[str], Counter[str], int]:
    rng = random.Random(seed)
    per_bucket = reservoir_per_bucket or max(sample_size, 25)
    bucket_counts: Counter[str] = Counter()
    bucket_samples: dict[str, list[str]] = defaultdict(list)
    candidate_count = 0

    for raw_url in urls:
        normalized = normalize_page_url(raw_url)
        if not normalized:
            continue
        if require_content and site is not None and not is_content_page_url(site, normalized):
            continue
        candidate_count += 1
        bucket = bucket_for_url(normalized)
        bucket_counts[bucket] += 1
        seen_in_bucket = bucket_counts[bucket]
        reservoir = bucket_samples[bucket]
        if len(reservoir) < per_bucket:
            reservoir.append(normalized)
            continue
        replacement_index = rng.randrange(seen_in_bucket)
        if replacement_index < per_bucket:
            reservoir[replacement_index] = normalized

    return balanced_draw(bucket_samples, sample_size=sample_size, rng=rng), bucket_counts, candidate_count


def inventory_index_url(site: Site, hf_resolve_base: str) -> str:
    run_id = quote(site.run_id, safe="")
    return f"{hf_resolve_base}/outputs/{run_id}/urls/index.json"


def inventory_shard_url(site: Site, hf_resolve_base: str, filename: str) -> str:
    run_id = quote(site.run_id, safe="")
    filename = quote(filename, safe="")
    return f"{hf_resolve_base}/outputs/{run_id}/urls/{filename}"


def load_json_url(url: str, *, timeout: float, retries: int) -> dict[str, object]:
    text = fetch_text(url, timeout=timeout, retries=retries)
    return json.loads(text)


def iter_inventory_urls(
    site: Site,
    *,
    hf_resolve_base: str,
    timeout: float,
    retries: int,
) -> Iterator[str]:
    index = load_json_url(inventory_index_url(site, hf_resolve_base), timeout=timeout, retries=retries)
    for shard in index.get("shards", []):
        if not isinstance(shard, dict):
            continue
        filename = shard.get("filename")
        if not isinstance(filename, str):
            continue
        url = inventory_shard_url(site, hf_resolve_base, filename)
        request = Request(url, headers={"Accept": "application/gzip,*/*", "User-Agent": USER_AGENT})
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with urlopen(request, timeout=timeout) as response:
                    with gzip.GzipFile(fileobj=response) as gz_handle:
                        text_handle = io.TextIOWrapper(gz_handle, encoding="utf-8", errors="replace")
                        for line in text_handle:
                            value = line.strip()
                            if value:
                                yield value
                last_error = None
                break
            except (HTTPError, URLError, TimeoutError, OSError, EOFError, http.client.IncompleteRead) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(0.8 * (attempt + 1))
        if last_error is not None:
            raise RuntimeError(f"failed to fetch inventory shard {url}: {last_error!r}")


def sample_from_inventory(
    site: Site,
    *,
    sample_size: int,
    seed: int,
    hf_resolve_base: str,
    timeout: float,
    retries: int,
) -> dict[str, object]:
    urls, bucket_counts, candidate_count = stratified_sample_urls(
        iter_inventory_urls(site, hf_resolve_base=hf_resolve_base, timeout=timeout, retries=retries),
        sample_size=sample_size,
        seed=seed,
        site=site,
        require_content=True,
    )
    return {
        "site": site.slug,
        "source": "hf_inventory_content_pages",
        "urls": urls,
        "candidate_count": candidate_count,
        "bucket_count": len(bucket_counts),
        "top_buckets": bucket_counts.most_common(20),
    }


def load_robot_parser(base_url: str, *, timeout: float, retries: int) -> urllib.robotparser.RobotFileParser:
    parsed = urlparse(base_url)
    robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        text = fetch_text(robots_url, timeout=timeout, retries=retries, max_bytes=500_000)
        parser.parse(text.splitlines())
    except Exception:
        parser.parse([])
    return parser


def can_fetch(
    robots: urllib.robotparser.RobotFileParser | None,
    url: str,
    *,
    respect_robots: bool,
) -> bool:
    if not respect_robots or robots is None:
        return True
    try:
        return robots.can_fetch(USER_AGENT, url) or robots.can_fetch("*", url)
    except Exception:
        return True


def extract_links(page_url: str, html_text: str, base_url: str) -> list[str]:
    parser = LinkExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    links: list[str] = []
    for href in parser.links:
        absolute = urljoin(page_url, href)
        normalized = normalize_page_url(absolute, keep_query=False)
        if normalized and same_site(normalized, base_url):
            links.append(normalized)
    return list(OrderedDict.fromkeys(links))


def discover_live_urls(
    site: Site,
    *,
    sample_size: int,
    seed: int,
    timeout: float,
    retries: int,
    max_discovery_pages: int,
    respect_robots: bool,
) -> dict[str, object]:
    rng = random.Random(seed)
    robots = load_robot_parser(site.base_url, timeout=timeout, retries=retries)
    frontier: deque[str] = deque()
    base = normalize_page_url(site.base_url, keep_query=False) or site.base_url
    frontier.append(base)
    seen: set[str] = set()
    candidates: OrderedDict[str, None] = OrderedDict()
    pages_fetched = 0
    target_candidates = max(sample_size * 4, sample_size + 50)

    while frontier and pages_fetched < max_discovery_pages and len(candidates) < target_candidates:
        index = rng.randrange(len(frontier))
        current = frontier[index]
        del frontier[index]
        if current in seen:
            continue
        seen.add(current)
        if not can_fetch(robots, current, respect_robots=respect_robots):
            continue
        response = fetch_url(
            current,
            timeout=timeout,
            retries=retries,
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            max_bytes=2_500_000,
        )
        pages_fetched += 1
        content_type = response.headers.get("Content-Type") or response.headers.get("content-type") or ""
        if not response.ok or "html" not in content_type.lower():
            continue
        if is_content_page_url(site, current):
            candidates[current] = None
        text = decode_bytes(response.data, response.headers)
        for link in extract_links(response.final_url, text, site.base_url):
            if is_content_page_url(site, link):
                candidates.setdefault(link, None)
            if link not in seen:
                frontier.append(link)
        if pages_fetched == 1 or pages_fetched % 25 == 0:
            print(
                f"discovery {site.slug}: pages={pages_fetched} "
                f"candidates={len(candidates)} frontier={len(frontier)}",
                file=sys.stderr,
            )

    sample, bucket_counts, candidate_count = stratified_sample_urls(
        candidates.keys(),
        sample_size=sample_size,
        seed=seed,
    )
    return {
        "site": site.slug,
        "source": "live_link_discovery_content_pages",
        "urls": sample,
        "candidate_count": candidate_count,
        "bucket_count": len(bucket_counts),
        "top_buckets": bucket_counts.most_common(20),
        "discovery_pages_fetched": pages_fetched,
        "discovery_seen_url_count": len(seen),
    }


def sample_site(
    site: Site,
    *,
    sample_size: int,
    seed: int,
    hf_resolve_base: str,
    timeout: float,
    retries: int,
    max_discovery_pages: int,
    respect_robots: bool,
) -> dict[str, object]:
    site_seed = int(hashlib.sha256(f"{seed}:{site.slug}".encode("utf-8")).hexdigest()[:12], 16)
    inventory_error: str | None = None
    try:
        result = sample_from_inventory(
            site,
            sample_size=sample_size,
            seed=site_seed,
            hf_resolve_base=hf_resolve_base,
            timeout=timeout,
            retries=retries,
        )
        if result["urls"]:
            return result
    except Exception as exc:
        inventory_error = repr(exc)

    result = discover_live_urls(
        site,
        sample_size=sample_size,
        seed=site_seed,
        timeout=timeout,
        retries=retries,
        max_discovery_pages=max_discovery_pages,
        respect_robots=respect_robots,
    )
    if inventory_error:
        result["inventory_error"] = inventory_error
    return result


def extract_text_and_title(html_text: str) -> tuple[str, str]:
    parser = VisibleTextParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    return parser.text, parser.title


def match_any(patterns: list[re.Pattern[str]], text: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            matches.append(match.group(0)[:160])
    return matches


def classify_response(
    response: FetchResponse,
    *,
    min_text_chars: int,
    paywall_text_chars: int,
) -> dict[str, object]:
    headers = response.headers
    content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    html_text = decode_bytes(response.data, headers) if response.data else ""
    visible_text, title = extract_text_and_title(html_text)
    scan_text = f"{title}\n{visible_text}\n{html_text[:300000]}"

    reasons: list[str] = []
    indicators: dict[str, list[str]] = {}
    status = response.status

    if response.error and (status is None or response.error.startswith("IncompleteRead")):
        reasons.append("network_error")
    if status is not None and status >= 400:
        reasons.append("http_error")
        if status in {401, 403}:
            reasons.append("access_denied")
    if content_type and "html" not in content_type.lower() and response.data:
        reasons.append("non_html_content")

    final_path = urlparse(response.final_url).path.lower()
    if re.search(r"/(?:login|signin|sign-in|user/login|account/login)(?:/|$)", final_path):
        reasons.append("login_required")
        indicators["login_required"] = [response.final_url]

    pattern_groups = [
        ("bot_challenge", CHALLENGE_PATTERNS),
        ("login_required", LOGIN_PATTERNS),
        ("registration_required", REGISTRATION_PATTERNS),
        ("membership_or_subscription_required", PAYWALL_STRONG_PATTERNS),
        ("javascript_render_required", JAVASCRIPT_PATTERNS),
    ]
    for reason, patterns in pattern_groups:
        matches = match_any(patterns, scan_text)
        if matches:
            reasons.append(reason)
            indicators[reason] = matches

    weak_paywall_matches = match_any(PAYWALL_WEAK_PATTERNS, scan_text)
    if weak_paywall_matches and len(visible_text) < paywall_text_chars:
        reasons.append("membership_or_subscription_required")
        indicators.setdefault("membership_or_subscription_required", []).extend(weak_paywall_matches)

    if (
        status is not None
        and 200 <= status < 400
        and "html" in content_type.lower()
        and len(visible_text) < min_text_chars
    ):
        reasons.append("low_text_content")

    deduped_reasons = list(OrderedDict.fromkeys(reasons))
    return {
        "is_complete": status is not None and 200 <= status < 400 and not deduped_reasons,
        "status": status,
        "final_url": response.final_url,
        "content_type": content_type,
        "html_bytes": len(response.data),
        "text_chars": len(visible_text),
        "title": title,
        "incomplete_reasons": deduped_reasons,
        "indicators": indicators,
        "fetch_error": response.error,
        "truncated": response.truncated,
    }


def audit_one_url(
    *,
    site: Site,
    sample_index: int,
    url: str,
    timeout: float,
    retries: int,
    min_text_chars: int,
    paywall_text_chars: int,
    robots: urllib.robotparser.RobotFileParser | None,
    respect_robots: bool,
) -> dict[str, object]:
    started_at = utc_now()
    if not can_fetch(robots, url, respect_robots=respect_robots):
        return {
            "site": site.name,
            "site_slug": site.slug,
            "base_url": site.base_url,
            "sample_index": sample_index,
            "url": url,
            "bucket": bucket_for_url(url),
            "is_complete": False,
            "status": None,
            "final_url": url,
            "content_type": "",
            "html_bytes": 0,
            "text_chars": 0,
            "title": "",
            "incomplete_reasons": ["robots_disallowed"],
            "indicators": {},
            "fetch_error": None,
            "truncated": False,
            "started_at": started_at,
            "finished_at": utc_now(),
        }

    response = fetch_url(
        url,
        timeout=timeout,
        retries=retries,
        accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        max_bytes=5_000_000,
    )
    classification = classify_response(
        response,
        min_text_chars=min_text_chars,
        paywall_text_chars=paywall_text_chars,
    )
    return {
        "site": site.name,
        "site_slug": site.slug,
        "base_url": site.base_url,
        "sample_index": sample_index,
        "url": url,
        "bucket": bucket_for_url(url),
        **classification,
        "started_at": started_at,
        "finished_at": utc_now(),
    }


def interleave_sample_rows(sites: list[Site], samples: dict[str, dict[str, object]]) -> list[tuple[Site, int, str]]:
    rows: list[tuple[Site, int, str]] = []
    max_len = max((len(samples[site.slug].get("urls", [])) for site in sites), default=0)
    for sample_index in range(max_len):
        for site in sites:
            urls = samples[site.slug].get("urls", [])
            if isinstance(urls, list) and sample_index < len(urls):
                rows.append((site, sample_index, str(urls[sample_index])))
    return rows


def audit_samples(
    sites: list[Site],
    samples: dict[str, dict[str, object]],
    *,
    workers: int,
    timeout: float,
    retries: int,
    min_text_chars: int,
    paywall_text_chars: int,
    submit_sleep: float,
    respect_robots: bool,
) -> list[dict[str, object]]:
    robots_by_site = {
        site.slug: load_robot_parser(site.base_url, timeout=timeout, retries=retries)
        for site in sites
    }
    tasks = interleave_sample_rows(sites, samples)
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures: dict[object, tuple[Site, int, str]] = {}
        for site, sample_index, url in tasks:
            future = executor.submit(
                audit_one_url,
                site=site,
                sample_index=sample_index,
                url=url,
                timeout=timeout,
                retries=retries,
                min_text_chars=min_text_chars,
                paywall_text_chars=paywall_text_chars,
                robots=robots_by_site.get(site.slug),
                respect_robots=respect_robots,
            )
            futures[future] = (site, sample_index, url)
            if submit_sleep > 0:
                time.sleep(submit_sleep)

        total = len(futures)
        for completed, future in enumerate(as_completed(futures), start=1):
            site, sample_index, url = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - keep the rest of the audit batch.
                result = {
                    "site": site.name,
                    "site_slug": site.slug,
                    "base_url": site.base_url,
                    "sample_index": sample_index,
                    "url": url,
                    "bucket": bucket_for_url(url),
                    "is_complete": False,
                    "status": None,
                    "final_url": url,
                    "content_type": "",
                    "html_bytes": 0,
                    "text_chars": 0,
                    "title": "",
                    "incomplete_reasons": ["network_error"],
                    "indicators": {"exception": [repr(exc)]},
                    "fetch_error": repr(exc),
                    "truncated": False,
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                }
            results.append(result)
            if completed == 1 or completed % 50 == 0 or completed == total:
                print(
                    f"audited {completed}/{total}; site={result['site_slug']} "
                    f"complete={result['is_complete']} reasons={','.join(result['incomplete_reasons'])}",
                    file=sys.stderr,
                )

    return sorted(results, key=lambda row: (str(row["site_slug"]), int(row["sample_index"])))


def summarize_results(
    sites: list[Site],
    samples: dict[str, dict[str, object]],
    page_results: list[dict[str, object]],
) -> dict[str, object]:
    rows_by_site: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in page_results:
        rows_by_site[str(row["site_slug"])].append(row)

    site_summaries: list[dict[str, object]] = []
    for site in sites:
        rows = rows_by_site.get(site.slug, [])
        complete_count = sum(1 for row in rows if row.get("is_complete") is True)
        incomplete_count = len(rows) - complete_count
        status_2xx_count = sum(1 for row in rows if isinstance(row.get("status"), int) and 200 <= int(row["status"]) < 300)
        reason_counts: Counter[str] = Counter()
        http_error_count = 0
        login_mechanism_count = 0
        for row in rows:
            reasons = {str(reason) for reason in row.get("incomplete_reasons", [])}
            if "http_error" in reasons:
                http_error_count += 1
            if reasons & LOGIN_MECHANISM_REASONS:
                login_mechanism_count += 1
            for reason in reasons:
                reason_counts[str(reason)] += 1
        sample_info = samples.get(site.slug, {})
        site_summaries.append(
            {
                "site": site.name,
                "site_slug": site.slug,
                "base_url": site.base_url,
                "run_id": site.run_id,
                "summary_status": site.status,
                "inventory_url_count": site.inventory_url_count,
                "sample_source": sample_info.get("source"),
                "candidate_count": sample_info.get("candidate_count", 0),
                "bucket_count": sample_info.get("bucket_count", 0),
                "sampled_url_count": len(sample_info.get("urls", [])) if isinstance(sample_info.get("urls"), list) else 0,
                "audited_url_count": len(rows),
                "http_2xx_count": status_2xx_count,
                "complete_count": complete_count,
                "incomplete_count": incomplete_count,
                "incomplete_ratio": (incomplete_count / len(rows)) if rows else None,
                "http_error_incomplete_count": http_error_count,
                "http_error_incomplete_ratio": (http_error_count / len(rows)) if rows else None,
                "login_mechanism_incomplete_count": login_mechanism_count,
                "login_mechanism_incomplete_ratio": (login_mechanism_count / len(rows)) if rows else None,
                "reason_counts": dict(reason_counts.most_common()),
                "top_buckets": sample_info.get("top_buckets", []),
                "notes": site.notes,
            }
        )
    return {"sites": site_summaries}


def pct(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def top_reason_text(reason_counts: dict[str, int], *, limit: int = 4) -> str:
    if not reason_counts:
        return "-"
    parts = []
    for reason, count in Counter(reason_counts).most_common(limit):
        label = REASON_LABELS.get(reason, reason)
        parts.append(f"{label}: {count}")
    return "; ".join(parts)


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sample_rows(sites: list[Site], samples: dict[str, dict[str, object]]) -> Iterator[dict[str, object]]:
    for site in sites:
        sample = samples[site.slug]
        for index, url in enumerate(sample.get("urls", [])):
            yield {
                "site": site.name,
                "site_slug": site.slug,
                "sample_index": index,
                "url": url,
                "bucket": bucket_for_url(str(url)),
                "sample_source": sample.get("source"),
            }


def write_markdown_report(
    path: Path,
    *,
    metadata: dict[str, object],
    summary: dict[str, object],
    page_results: list[dict[str, object]],
) -> None:
    lines: list[str] = []
    lines.append("# 202606 Web Scan 门户完整性抽样报告")
    lines.append("")
    lines.append(f"生成时间：{metadata['finished_at']}")
    lines.append(f"summary 来源：{metadata['summary_url']}")
    lines.append(f"抽样口径：{metadata.get('url_scope', 'content_pages')}")
    lines.append("")
    lines.append(
        "判定说明：本报告只抽取各门户的实际内容页候选；完整性基于静态 HTML 抓取的启发式检测。登录、注册、订阅/会员、"
        "Cloudflare/验证码、JS-only 页面、HTTP 错误和静态正文过短都会被计为不完整原因。"
    )
    lines.append("")
    lines.append("| 站点 | 抽样来源 | 抽样数 | 2xx | 完整 | 不完整 | 不完整比例 | HTTP 错误比例 | 登录/注册/订阅机制比例 | 主要原因 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in summary["sites"]:
        lines.append(
            "| {site} | {source} | {sampled} | {ok} | {complete} | {incomplete} | {ratio} | {http_ratio} | {login_ratio} | {reasons} |".format(
                site=row["site"],
                source=row["sample_source"],
                sampled=row["audited_url_count"],
                ok=row["http_2xx_count"],
                complete=row["complete_count"],
                incomplete=row["incomplete_count"],
                ratio=pct(row["incomplete_ratio"]),
                http_ratio=pct(row["http_error_incomplete_ratio"]),
                login_ratio=pct(row["login_mechanism_incomplete_ratio"]),
                reasons=top_reason_text(row["reason_counts"]),
            )
        )
    lines.append("")
    lines.append("## 逐站不完整样例")
    for site_row in summary["sites"]:
        site_slug = site_row["site_slug"]
        incomplete_rows = [
            row for row in page_results if row["site_slug"] == site_slug and not row["is_complete"]
        ][:15]
        lines.append("")
        lines.append(f"### {site_row['site']}")
        lines.append("")
        lines.append(f"- 不完整比例：{pct(site_row['incomplete_ratio'])}")
        lines.append(f"- 主要原因：{top_reason_text(site_row['reason_counts'])}")
        if not incomplete_rows:
            lines.append("- 样本中未发现不完整页面。")
            continue
        lines.append("")
        lines.append("| URL | 状态 | 原因 | 标题 |")
        lines.append("|---|---:|---|---|")
        for row in incomplete_rows:
            title = str(row.get("title") or "").replace("|", "\\|")[:120]
            lines.append(
                f"| {row['url']} | {row.get('status') or ''} | "
                f"{', '.join(REASON_LABELS.get(reason, reason) for reason in row['incomplete_reasons'])} | "
                f"{title} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html_report(
    path: Path,
    *,
    metadata: dict[str, object],
    summary: dict[str, object],
    page_results: list[dict[str, object]],
) -> None:
    rows_html = []
    for row in summary["sites"]:
        rows_html.append(
            "<tr>"
            f"<td><a href=\"{html.escape(str(row['base_url']))}\">{html.escape(str(row['site']))}</a></td>"
            f"<td>{html.escape(str(row['sample_source']))}</td>"
            f"<td>{row['audited_url_count']}</td>"
            f"<td>{row['http_2xx_count']}</td>"
            f"<td>{row['complete_count']}</td>"
            f"<td>{row['incomplete_count']}</td>"
            f"<td>{pct(row['incomplete_ratio'])}</td>"
            f"<td>{pct(row['http_error_incomplete_ratio'])}</td>"
            f"<td>{pct(row['login_mechanism_incomplete_ratio'])}</td>"
            f"<td>{html.escape(top_reason_text(row['reason_counts']))}</td>"
            "</tr>"
        )

    details_html = []
    for site_row in summary["sites"]:
        site_slug = site_row["site_slug"]
        incomplete_rows = [
            row for row in page_results if row["site_slug"] == site_slug and not row["is_complete"]
        ][:25]
        item_rows = []
        for row in incomplete_rows:
            reasons = ", ".join(REASON_LABELS.get(reason, reason) for reason in row["incomplete_reasons"])
            item_rows.append(
                "<tr>"
                f"<td><a href=\"{html.escape(str(row['url']))}\">{html.escape(str(row['url']))}</a></td>"
                f"<td>{html.escape(str(row.get('status') or ''))}</td>"
                f"<td>{html.escape(reasons)}</td>"
                f"<td>{html.escape(str(row.get('title') or '')[:180])}</td>"
                "</tr>"
            )
        if not item_rows:
            item_rows.append("<tr><td colspan=\"4\">样本中未发现不完整页面。</td></tr>")
        details_html.append(
            f"<section><h2>{html.escape(str(site_row['site']))}</h2>"
            f"<p>不完整比例：{pct(site_row['incomplete_ratio'])}；主要原因："
            f"{html.escape(top_reason_text(site_row['reason_counts']))}</p>"
            "<table><thead><tr><th>URL</th><th>状态</th><th>原因</th><th>标题</th></tr></thead>"
            f"<tbody>{''.join(item_rows)}</tbody></table></section>"
        )

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>202606 Web Scan 门户完整性抽样报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ font-size: 26px; margin-bottom: 8px; }}
    h2 {{ font-size: 20px; margin-top: 32px; }}
    p {{ line-height: 1.55; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 24px; table-layout: fixed; }}
    th, td {{ border: 1px solid #d8dee9; padding: 8px 10px; vertical-align: top; font-size: 13px; word-break: break-word; }}
    th {{ background: #f3f6f8; text-align: left; }}
    tr:nth-child(even) td {{ background: #fbfcfd; }}
    .note {{ max-width: 1100px; color: #46515f; }}
  </style>
</head>
<body>
  <h1>202606 Web Scan 门户完整性抽样报告</h1>
  <p class="note">生成时间：{html.escape(str(metadata['finished_at']))}<br>
  summary 来源：<a href="{html.escape(str(metadata['summary_url']))}">{html.escape(str(metadata['summary_url']))}</a><br>
  抽样口径：{html.escape(str(metadata.get('url_scope', 'content_pages')))}</p>
  <p class="note">判定说明：本报告只抽取各门户的实际内容页候选；完整性基于静态 HTML 抓取的启发式检测。登录、注册、订阅/会员、
  Cloudflare/验证码、JS-only 页面、HTTP 错误和静态正文过短都会被计为不完整原因。</p>
  <table>
    <thead><tr><th>站点</th><th>抽样来源</th><th>抽样数</th><th>2xx</th><th>完整</th><th>不完整</th><th>不完整比例</th><th>HTTP 错误比例</th><th>登录/注册/订阅机制比例</th><th>主要原因</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  {''.join(details_html)}
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def write_outputs(
    *,
    output_dir: Path,
    sites: list[Site],
    samples: dict[str, dict[str, object]],
    page_results: list[dict[str, object]],
    metadata: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_results(sites, samples, page_results)
    metadata = dict(metadata)
    metadata["output_dir"] = str(output_dir)
    metadata["output_files"] = {
        "sample_urls_jsonl": str(output_dir / "sample_urls.jsonl"),
        "page_audit_jsonl": str(output_dir / "page_audit.jsonl"),
        "report_data_json": str(output_dir / "report_data.json"),
        "report_md": str(output_dir / "portal_completeness_report.md"),
        "report_html": str(output_dir / "portal_completeness_report.html"),
    }

    write_jsonl(output_dir / "sample_urls.jsonl", sample_rows(sites, samples))
    write_jsonl(output_dir / "page_audit.jsonl", page_results)
    with (output_dir / "report_data.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {"metadata": metadata, "summary": summary, "samples": samples},
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    write_markdown_report(
        output_dir / "portal_completeness_report.md",
        metadata=metadata,
        summary=summary,
        page_results=page_results,
    )
    write_html_report(
        output_dir / "portal_completeness_report.html",
        metadata=metadata,
        summary=summary,
        page_results=page_results,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the 202606_web_scan portal summary, sample URLs per site, "
            "fetch static HTML, and report likely completeness gates."
        )
    )
    parser.add_argument("--summary-url", default=DEFAULT_SUMMARY_URL)
    parser.add_argument("--hf-resolve-base", default=DEFAULT_HF_RESOLVE_BASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--submit-sleep", type=float, default=0.03)
    parser.add_argument("--max-discovery-pages", type=int, default=600)
    parser.add_argument("--min-text-chars", type=int, default=600)
    parser.add_argument("--paywall-text-chars", type=int, default=5000)
    parser.add_argument("--only-site", action="append", default=[])
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--ignore-robots", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_size <= 0:
        print("--sample-size must be positive", file=sys.stderr)
        return 2
    if args.workers <= 0:
        print("--workers must be positive", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("--retries must be non-negative", file=sys.stderr)
        return 2

    started_at = utc_now()
    summary_text = fetch_text(args.summary_url, timeout=args.timeout, retries=args.retries)
    sites = parse_summary_sites(summary_text)
    if args.only_site:
        requested = {slugify(value) for value in args.only_site}
        sites = [site for site in sites if site.slug in requested or slugify(site.name) in requested]
    if not sites:
        print("No sites parsed from summary.", file=sys.stderr)
        return 1

    samples: dict[str, dict[str, object]] = {}
    for site in sites:
        print(f"sampling {site.name} from {site.run_id}", file=sys.stderr)
        sample = sample_site(
            site,
            sample_size=args.sample_size,
            seed=args.seed,
            hf_resolve_base=args.hf_resolve_base,
            timeout=args.timeout,
            retries=args.retries,
            max_discovery_pages=args.max_discovery_pages,
            respect_robots=not args.ignore_robots,
        )
        samples[site.slug] = sample
        print(
            f"sampled {len(sample['urls'])}/{args.sample_size} for {site.slug}; "
            f"source={sample['source']} candidates={sample.get('candidate_count')}",
            file=sys.stderr,
        )

    if args.sample_only:
        page_results: list[dict[str, object]] = []
    else:
        page_results = audit_samples(
            sites,
            samples,
            workers=args.workers,
            timeout=args.timeout,
            retries=args.retries,
            min_text_chars=args.min_text_chars,
            paywall_text_chars=args.paywall_text_chars,
            submit_sleep=args.submit_sleep,
            respect_robots=not args.ignore_robots,
        )

    finished_at = utc_now()
    metadata: dict[str, object] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "summary_url": args.summary_url,
        "hf_resolve_base": args.hf_resolve_base,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "workers": args.workers,
        "timeout": args.timeout,
        "retries": args.retries,
        "respect_robots": not args.ignore_robots,
        "sample_only": args.sample_only,
        "url_scope": "content_pages",
        "site_count": len(sites),
        "heuristic": {
            "min_text_chars": args.min_text_chars,
            "paywall_text_chars": args.paywall_text_chars,
            "reason_labels": REASON_LABELS,
        },
    }
    write_outputs(
        output_dir=args.output_dir,
        sites=sites,
        samples=samples,
        page_results=page_results,
        metadata=metadata,
    )

    report_path = args.output_dir / "portal_completeness_report.html"
    print(f"Wrote portal completeness audit to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
