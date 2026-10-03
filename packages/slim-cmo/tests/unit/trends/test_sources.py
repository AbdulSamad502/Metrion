"""trends.sources: what counts as ONE source. The key is deliberately coarse - when ownership is
unknowable it merges, so independence can be under-counted but never over-counted."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo.trends import sources as s
from slim_cmo.trends.sources import SourceClass, SourceType

from .helpers import item


class TestRegistrableDomain:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.amazon.in/some/page", "amazon.in"),
            ("https://sellercentral.amazon.in/x", "amazon.in"),
            ("HTTPS://WWW.AMAZON.IN/", "amazon.in"),
            ("https://amazon.in./", "amazon.in"),  # FQDN trailing dot
            ("https://news.bbc.co.uk/story", "bbc.co.uk"),  # multi-label public suffix
            ("https://www.bbc.co.uk/story", "bbc.co.uk"),
            ("https://shop.example.co.in/", "example.co.in"),
            ("https://a.blogspot.com/post", "a.blogspot.com"),  # private suffix: each blog is its own site
            ("https://b.blogspot.com/post", "b.blogspot.com"),
            ("https://someone.github.io/x", "someone.github.io"),
            ("https://medium.com/@one/post", "medium.com"),  # one domain: authors merge (conservative)
            ("https://medium.com/@two/post", "medium.com"),
            ("https://example.com:8443/p?q=1#frag", "example.com"),
            ("http://user:pw@example.com/p", "example.com"),
            ("https://xn--mnchen-3ya.de/", "xn--mnchen-3ya.de"),
            ("https://münchen.de/", "xn--mnchen-3ya.de"),  # IDNA normalised
            ("https://youtu.be/abc", "youtube.com"),
            ("https://www.youtube.com/watch?v=abc", "youtube.com"),
            ("https://m.youtube.com/watch?v=abc", "youtube.com"),
            ("https://www.youtube-nocookie.com/embed/abc", "youtube.com"),
        ],
    )
    def test_cases(self, url, expected):
        assert s.registrable_domain(url) == expected

    def test_lookalike_hosts_do_not_collapse_into_the_real_domain(self):
        assert s.registrable_domain("https://amazon.in.evil.com/") == "evil.com"
        assert s.registrable_domain("https://notamazon.in/") == "notamazon.in"
        assert s.registrable_domain("http://amazon.in@evil.com/") == "evil.com"  # userinfo trick

    @pytest.mark.parametrize("url,expected", [("http://192.168.1.1/x", "192.168.1.1"), ("http://[::1]:8080/", "::1"), ("http://localhost/x", "localhost")])
    def test_ip_literals_and_single_label_hosts_are_their_own_key(self, url, expected):
        assert s.registrable_domain(url) == expected

    @pytest.mark.parametrize(
        "url", ["", "   ", "not a url", "ftp://example.com/x", "javascript:alert(1)", "//example.com/x", "https://", "mailto:a@b.com",
                "file:///etc/passwd", "data:text/html,hi", None, 5, b"https://x.com",
                "http://[unclosed", "http://./", "http://" + "a" * 64 + ".com/"],  # bad IPv6, empty host after trimming the dot, IDNA label too long
    )
    def test_unusable_urls_are_none(self, url):
        assert s.registrable_domain(url) is None  # type: ignore[arg-type]

    @given(st.text(max_size=80))
    @settings(max_examples=300, deadline=None)
    def test_never_raises(self, url):
        s.registrable_domain(url)


class TestCitable:
    def test_needs_a_real_http_url(self):
        assert s.is_citable(item("https://example.com/a"))
        assert not s.is_citable(item("ftp://example.com/a"))
        assert not s.is_citable(item(""))


class TestIndependenceKey:
    def test_web_items_on_one_domain_share_a_key(self):
        a, b = item("https://www.example.com/a"), item("https://blog.example.com/b")
        assert s.independence_key(a) == s.independence_key(b) == "web:example.com"

    def test_different_domains_differ(self):
        assert s.independence_key(item("https://one.com/a")) != s.independence_key(item("https://two.com/a"))

    def test_video_by_channel_id_regardless_of_host_alias(self):
        a = item("https://www.youtube.com/watch?v=1", kind=SourceType.VIDEO, channel_id="UC123")
        b = item("https://youtu.be/2", kind=SourceType.VIDEO, channel_id="UC123")
        c = item("https://youtu.be/3", kind=SourceType.VIDEO, channel_id="UC999")
        assert s.independence_key(a) == s.independence_key(b) == "video:youtube.com:channel:UC123"
        assert s.independence_key(c) != s.independence_key(a)

    def test_video_falls_back_to_normalised_channel_title(self):
        a = item("https://youtu.be/1", kind=SourceType.VIDEO, channel_title="Steel  Bottle Reviews!")
        b = item("https://youtu.be/2", kind=SourceType.VIDEO, channel_title="steel bottle reviews")
        assert s.independence_key(a) == s.independence_key(b)

    def test_anonymous_videos_merge_conservatively(self):
        a = item("https://youtu.be/1", kind=SourceType.VIDEO)
        b = item("https://youtu.be/2", kind=SourceType.VIDEO, channel_title="   ")
        assert s.independence_key(a) == s.independence_key(b) == "video:youtube.com:unknown"

    def test_a_video_and_an_article_are_never_the_same_key(self):
        v = item("https://www.youtube.com/watch?v=1", kind=SourceType.VIDEO, channel_id="UC1")
        w = item("https://www.youtube.com/about", kind=SourceType.WEB)
        assert s.independence_key(v) != s.independence_key(w)

    def test_an_uncitable_item_has_no_key(self):
        with pytest.raises(ValueError):
            s.independence_key(item("not a url"))


class TestClassifySource:
    OFFICIAL = frozenset({"amazon.in", "flipkart.com"})

    @pytest.mark.parametrize("url", ["https://amazon.in/a", "https://www.amazon.in/a", "https://sellercentral.amazon.in/news", "https://FLIPKART.com/x"])
    def test_official(self, url):
        assert s.classify_source(item(url), self.OFFICIAL) is SourceClass.OFFICIAL_MARKETPLACE

    @pytest.mark.parametrize("url", ["https://notamazon.in/", "https://amazon.in.evil.com/", "https://evil.com/amazon.in", "https://example.com/", "ftp://amazon.in/", "garbage"])
    def test_lookalikes_and_unusable_urls_are_third_party(self, url):
        assert s.classify_source(item(url), self.OFFICIAL) is SourceClass.THIRD_PARTY

    def test_nothing_is_official_when_no_domains_are_configured(self):
        assert s.classify_source(item("https://amazon.in/a"), frozenset()) is SourceClass.THIRD_PARTY

    def test_a_subdomain_entry_restricts_to_that_subdomain(self):
        only = frozenset({"sellercentral.amazon.in"})
        assert s.classify_source(item("https://sellercentral.amazon.in/x"), only) is SourceClass.OFFICIAL_MARKETPLACE
        assert s.classify_source(item("https://www.amazon.in/x"), only) is SourceClass.THIRD_PARTY


class TestParsePublishedDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-10-01T10:30:00Z", datetime(2026, 10, 1, 10, 30, tzinfo=UTC)),
            ("2026-10-01T10:30:00+05:30", datetime(2026, 10, 1, 5, 0, tzinfo=UTC)),
            ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
            ("2026-10-01T10:30:00", datetime(2026, 10, 1, 10, 30, tzinfo=UTC)),  # naive -> UTC
            ("  2026-10-01  ", datetime(2026, 10, 1, tzinfo=UTC)),
            ("Thu, 01 Oct 2026 10:30:00 +0000", datetime(2026, 10, 1, 10, 30, tzinfo=UTC)),
            ("Thu, 01 Oct 2026 16:00:00 +0530", datetime(2026, 10, 1, 10, 30, tzinfo=UTC)),
        ],
    )
    def test_understood_formats(self, raw, expected):
        assert s.parse_published_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "yesterday", "2026-13-45", "not a date", "01/02/03", "2026-10-01T25:00:00", 5, b"2026-10-01"])
    def test_everything_else_is_none_never_guessed(self, raw):
        assert s.parse_published_date(raw) is None  # type: ignore[arg-type]

    def test_result_is_always_aware_utc(self):
        out = s.parse_published_date("2026-10-01T10:30:00+09:00")
        assert out is not None and out.utcoffset() == timedelta(0)

    @given(st.text(max_size=40))
    @settings(max_examples=300, deadline=None)
    def test_never_raises_and_is_none_or_aware(self, raw):
        out = s.parse_published_date(raw)
        assert out is None or out.tzinfo is not None


class TestNormaliseTitle:
    def test_collapses_case_punctuation_spacing(self):
        assert s.normalise_title("GST Council: New Rules!") == s.normalise_title("gst council  new rules")

    def test_empty_when_nothing_comparable(self):
        assert s.normalise_title(None) == "" and s.normalise_title("  !!! ") == ""
