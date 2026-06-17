from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pipelines.web_scan.portal_completeness_audit import (
    FetchResponse,
    Site,
    classify_response,
    is_content_page_url,
    parse_summary_sites,
    stratified_sample_urls,
)


SUMMARY_SNIPPET = """
| 站点 | 简介 | Run ID | 状态 | URL 数 | Manifest 记录 | robots | 备注 |
|---|---|---|---|---:|---:|---|---|
| [NASA](https://www.nasa.gov/) | 美国航天局官网。 | `nasa_full-20260521T104201Z` | 已产出 | 92,761 | 208,426 | `http_200` | 去重。 |
| [Smithsonian](https://www.si.edu/) | 史密森尼机构门户。 | `smithsonian_full-20260521T104705Z` | 已跳过 | 0 | 0 | `http_200` | 缺少 API key。 |
"""


def test_parse_summary_sites() -> None:
    sites = parse_summary_sites(SUMMARY_SNIPPET)
    assert [site.name for site in sites] == ["NASA", "Smithsonian"]
    assert sites[0].base_url == "https://www.nasa.gov/"
    assert sites[0].run_id == "nasa_full-20260521T104201Z"
    assert sites[0].inventory_url_count == 92761
    assert sites[1].inventory_url_count == 0


def test_stratified_sample_urls_draws_across_buckets() -> None:
    urls = [
        *(f"https://example.org/news/{index}" for index in range(50)),
        *(f"https://example.org/science/{index}" for index in range(50)),
        *(f"https://example.org/about/{index}" for index in range(50)),
    ]
    sample, buckets, candidates = stratified_sample_urls(urls, sample_size=9, seed=7)
    assert candidates == 150
    assert set(buckets) == {
        "example.org/news",
        "example.org/science",
        "example.org/about",
    }
    assert len(sample) == 9
    assert {url.split("/")[3] for url in sample} == {"news", "science", "about"}


def test_content_page_filter_for_nature_and_china_daily() -> None:
    nature = Site("Nature", "https://www.nature.com/", "run", "ok", 0, 0, "ok", "")

    assert is_content_page_url(nature, "https://www.nature.com/articles/s43247-024-01436-1")
    assert not is_content_page_url(nature, "https://www.nature.com/nature-index")
    assert not is_content_page_url(nature, "https://www.nature.com/nature/volumes/620/issues/7974")

    china_daily = Site("China Daily", "https://www.chinadaily.com.cn/", "run", "ok", 0, 0, "ok", "")
    assert is_content_page_url(
        china_daily,
        "https://www.chinadaily.com.cn/a/202605/21/WS682d4f5da310a04af22c0c39.html",
    )
    assert is_content_page_url(
        china_daily,
        "http://www.chinadaily.com.cn/business/2012-08/31/content_15723034.htm",
    )
    assert not is_content_page_url(china_daily, "http://www.chinadaily.com.cn/node_1011125.htm")


def test_content_page_filter_excludes_smithsonian_transaction_pages() -> None:
    site = Site("Smithsonian", "https://www.si.edu/", "run", "ok", 0, 0, "ok", "")
    assert is_content_page_url(site, "https://airandspace.si.edu/explore/stories/artemis-program")
    assert not is_content_page_url(site, "https://nationalzoo.si.edu/membership/circle-council")
    assert not is_content_page_url(site, "https://secure.nationalzoo.si.edu/overview/walk-in-group")


def test_content_page_filter_prefers_modern_who_content() -> None:
    site = Site("WHO", "https://www.who.int/", "run", "ok", 0, 0, "ok", "")
    assert is_content_page_url(
        site,
        "https://www.who.int/news/item/31-12-2013-world-malaria-report-2013-shows-major-progress-in-fight-against-malaria-calls-for-sustained-financing",
    )
    assert is_content_page_url(
        site,
        "https://www.who.int/news-room/fact-sheets/detail/malaria",
    )
    assert is_content_page_url(
        site,
        "https://www.who.int/publications/i/item/9789240064898",
    )
    assert not is_content_page_url(
        site,
        "http://www.who.int/healthacademy/news/Archive-HA-News/en/",
    )


def test_classify_login_required_page() -> None:
    response = FetchResponse(
        url="https://example.org/article",
        final_url="https://example.org/article",
        status=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        data=(
            b"<html><title>Members only</title><body>"
            b"<main>Please sign in to continue reading this article.</main>"
            b"</body></html>"
        ),
        error=None,
        truncated=False,
    )
    result = classify_response(response, min_text_chars=20, paywall_text_chars=5000)
    assert result["is_complete"] is False
    assert "login_required" in result["incomplete_reasons"]


def test_classify_subscription_gate_even_with_long_page() -> None:
    body = " ".join(["ordinary article shell"] * 500)
    response = FetchResponse(
        url="https://example.org/article",
        final_url="https://example.org/article",
        status=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        data=(
            "<html><title>Research article</title><body>"
            "<main>Access options. Log in via an institution. "
            f"{body}</main></body></html>"
        ).encode("utf-8"),
        error=None,
        truncated=False,
    )
    result = classify_response(response, min_text_chars=20, paywall_text_chars=5000)
    assert result["is_complete"] is False
    assert "membership_or_subscription_required" in result["incomplete_reasons"]


def test_classify_does_not_count_generic_nav_sign_in_or_event_registration() -> None:
    body = " ".join(["complete visible article text"] * 300)
    response = FetchResponse(
        url="https://example.org/article",
        final_url="https://example.org/article",
        status=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        data=(
            "<html><title>Complete article</title><body>"
            "<nav>Please Sign In</nav>"
            "<main>Registration required for the live event. Access this article. "
            f"{body}</main></body></html>"
        ).encode("utf-8"),
        error=None,
        truncated=False,
    )
    result = classify_response(response, min_text_chars=20, paywall_text_chars=5000)
    assert result["is_complete"] is True
    assert result["incomplete_reasons"] == []
