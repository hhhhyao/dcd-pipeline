"""Tests for audio and video element handling in the conversion pipeline."""

from __future__ import annotations

from lxml.html import document_fromstring, fragment_fromstring, tostring

from parse_html.html_tool import (
    PageMeta,
    make_cleaner,
    make_html_converter,
    make_md_converter,
)
from parse_html.html_tool.cleaner.page import (
    replace_audio_elements,
    replace_video_elements,
)

# -- replace_video_elements --------------------------------------------------


class TestReplaceVideoElements:
    def test_video_with_poster_becomes_linked_image(self) -> None:
        tree = fragment_fromstring(
            '<div><video poster="https://example.com/thumb.jpg">'
            '<source src="https://example.com/clip.mp4" type="video/mp4">'
            '</video></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<video" not in result
        assert '<a href="https://example.com/clip.mp4">' in result
        assert (
            '<img src="https://example.com/thumb.jpg" alt="video">'
            in result
        )

    def test_video_without_poster_becomes_text_link(self) -> None:
        tree = fragment_fromstring(
            '<div><video><source src="https://example.com/clip.mp4">'
            '</video></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<video" not in result
        assert '<a href="https://example.com/clip.mp4">(video)</a>' in result

    def test_video_with_multiple_sources_uses_first(self) -> None:
        tree = fragment_fromstring(
            '<div><video>'
            '<source src="https://example.com/v.webm" type="video/webm">'
            '<source src="https://example.com/v.mp4" type="video/mp4">'
            '</video></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "v.webm" in result
        assert "v.mp4" not in result

    def test_video_no_src_no_poster_removed(self) -> None:
        tree = fragment_fromstring(
            '<div><p>before</p><video></video><p>after</p></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<video" not in result
        assert "before" in result
        assert "after" in result

    def test_video_inside_figure_with_caption(self) -> None:
        tree = fragment_fromstring(
            '<div><figure>'
            '<video poster="https://example.com/thumb.jpg">'
            '<source src="https://example.com/clip.mp4">'
            '</video>'
            '<figcaption>Demo video</figcaption>'
            '</figure></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<figure" not in result
        assert "<video" not in result
        assert "thumb.jpg" in result
        assert "Demo video" in result

    def test_video_preserves_tail_text(self) -> None:
        tree = fragment_fromstring(
            '<div><video><source src="https://example.com/v.mp4">'
            '</video> trailing text</div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "trailing text" in result

    def test_video_poster_only_no_source(self) -> None:
        tree = fragment_fromstring(
            '<div><video poster="https://example.com/poster.jpg">'
            '</video></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<video" not in result
        assert '<a href="https://example.com/poster.jpg">' in result
        assert "poster.jpg" in result

    def test_video_href_prefers_src_over_poster(self) -> None:
        tree = fragment_fromstring(
            '<div><video poster="https://example.com/poster.jpg">'
            '<source src="https://example.com/video.mp4">'
            '</video></div>',
        )
        replace_video_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert 'href="https://example.com/video.mp4"' in result


# -- replace_audio_elements --------------------------------------------------


class TestReplaceAudioElements:
    def test_basic_audio_src(self) -> None:
        tree = fragment_fromstring(
            '<div><audio src="https://example.com/song.mp3"></audio></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<audio" not in result
        assert '<a href="https://example.com/song.mp3">(audio)</a>' in result

    def test_audio_with_source_child(self) -> None:
        tree = fragment_fromstring(
            '<div><audio><source src="https://example.com/podcast.ogg" '
            'type="audio/ogg"></audio></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<audio" not in result
        assert (
            '<a href="https://example.com/podcast.ogg">(audio)</a>'
            in result
        )

    def test_audio_with_multiple_sources_uses_first(self) -> None:
        tree = fragment_fromstring(
            '<div><audio>'
            '<source src="https://example.com/a.ogg" type="audio/ogg">'
            '<source src="https://example.com/a.mp3" type="audio/mpeg">'
            '</audio></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "a.ogg" in result
        assert "a.mp3" not in result

    def test_audio_no_src_removed(self) -> None:
        tree = fragment_fromstring(
            '<div><p>before</p><audio></audio><p>after</p></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<audio" not in result
        assert "before" in result
        assert "after" in result

    def test_audio_inside_figure(self) -> None:
        tree = fragment_fromstring(
            '<div><figure>'
            '<audio src="https://example.com/clip.mp3"></audio>'
            '<figcaption>My recording</figcaption>'
            '</figure></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "<figure" not in result
        assert "<audio" not in result
        assert '<a href="https://example.com/clip.mp3">(audio)</a>' in result
        assert "My recording" in result

    def test_audio_preserves_tail_text(self) -> None:
        tree = fragment_fromstring(
            '<div><audio src="https://example.com/a.mp3">'
            '</audio> some text</div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "some text" in result

    def test_audio_src_attribute_takes_priority_over_source(self) -> None:
        tree = fragment_fromstring(
            '<div><audio src="https://example.com/direct.mp3">'
            '<source src="https://example.com/child.mp3">'
            '</audio></div>',
        )
        replace_audio_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "direct.mp3" in result
        assert "child.mp3" not in result


# -- HTML converter ----------------------------------------------------------


class TestHtmlConverterMedia:
    def test_audio_tag_preserved(self) -> None:
        html = (
            "<html><body>"
            '<audio controls src="https://example.com/song.mp3">'
            '<source src="https://example.com/song.ogg" type="audio/ogg">'
            "</audio>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        _, content = cleaner.clean(tree)
        converter = make_html_converter(meta)
        result = converter.convert(content)
        assert "<audio" in result
        assert "song.mp3" in result

    def test_video_tag_preserved(self) -> None:
        html = (
            "<html><body>"
            '<video controls poster="https://example.com/thumb.jpg">'
            '<source src="https://example.com/clip.mp4" type="video/mp4">'
            "</video>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        _, content = cleaner.clean(tree)
        converter = make_html_converter(meta)
        result = converter.convert(content)
        assert "<video" in result
        assert "clip.mp4" in result


# -- Markdown converter ------------------------------------------------------


class TestMdConverterMedia:
    def test_audio_becomes_link(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            '<p>Listen here:</p>'
            '<audio src="https://example.com/song.mp3" controls></audio>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
        converter = make_md_converter(meta)
        result = converter.convert(content)
        assert "(audio)" in result
        assert "https://example.com/song.mp3" in result
        assert "<audio" not in result

    def test_video_with_poster_becomes_image_link(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            '<p>Watch:</p>'
            '<video poster="https://example.com/thumb.jpg">'
            '<source src="https://example.com/clip.mp4" type="video/mp4">'
            '</video>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
        converter = make_md_converter(meta)
        result = converter.convert(content)
        assert "thumb.jpg" in result
        assert "clip.mp4" in result
        assert "<video" not in result

    def test_video_without_poster_becomes_text_link(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            '<video><source src="https://example.com/clip.mp4"></video>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
        converter = make_md_converter(meta)
        result = converter.convert(content)
        assert "(video)" in result
        assert "clip.mp4" in result
        assert "<video" not in result
