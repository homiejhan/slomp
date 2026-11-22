"""A dealnews feed is read past its first page while pages come back full and recent (slomp/sources/feeds.py)."""
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

from slomp.sources.feeds import DealFeeds, FeedPlan


def rss(ids, age_days=1.0):
    when = format_datetime(datetime.now(timezone.utc) - timedelta(days=age_days))
    items = "".join(f"<item><title>Store Sale {i}: Up to 50% off</title><link>https://www.dealnews.com/x/{i}.html</link>"
                    f"<guid>https://www.dealnews.com/x/{i}.html</guid><pubDate>{when}</pubDate><description>d</description></item>"
                    for i in ids)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()


class Http:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    async def get(self, url, ttl_s=0, **kw):
        self.asked.append(url)
        body = self.pages.get(url)
        return SimpleNamespace(status=200 if body is not None else 404, body=body or b"")


def read(pages, url="https://www.dealnews.com/s1/Store/?rss=1", source="dealnews"):
    http = Http(pages)
    posts, err = asyncio.run(DealFeeds(http).read(FeedPlan(source, "store", url, [])))
    return posts, err, http.asked


def test_a_full_first_page_is_followed_by_the_next_ones():
    u = "https://www.dealnews.com/s1/Store/?rss=1"
    posts, err, asked = read({u: rss(range(20)), u + "&start=20": rss(range(20, 40)), u + "&start=40": rss(range(40, 45))})
    assert (len(posts), err) == (45, "") and asked == [u, u + "&start=20", u + "&start=40"]
    # no more than two further pages, however many there are
    posts, _, asked = read({u: rss(range(20)), u + "&start=20": rss(range(20, 40)), u + "&start=40": rss(range(40, 60)),
                            u + "&start=60": rss(range(60, 80))})
    assert len(posts) == 60 and len(asked) == 3


def test_a_short_page_an_old_page_or_a_failed_one_ends_the_reading():
    u = "https://www.dealnews.com/s1/Store/?rss=1"
    assert read({u: rss(range(12))})[2] == [u]                                    # not full: nothing behind it
    assert read({u: rss(range(20), age_days=45)})[2] == [u]                       # nothing recent enough to show
    posts, err, asked = read({u: rss(range(20))})                                 # the second page fails: the first stands
    assert (len(posts), err, len(asked)) == (20, "", 2)
    posts, _, asked = read({u: rss(range(20)), u + "&start=20": rss(range(20))})  # the same posts again: stop
    assert len(posts) == 20 and len(asked) == 2


def test_hip2save_pages_by_number_and_a_site_with_no_pages_is_read_once():
    u = "https://hip2save.com/sales-deals/women/feed/"
    posts, err, asked = read({u: rss(range(100)), u + "?paged=2": rss(range(100, 200)), u + "?paged=3": rss(range(200, 230))},
                             url=u, source="hip2save")
    assert (len(posts), err) == (230, "") and asked == [u, u + "?paged=2", u + "?paged=3"]
    assert read({u: rss(range(60))}, url=u, source="hip2save")[2] == [u]          # under a page of 100: nothing behind it
    s = "https://slickdeals.net/newsearch.php?rss=1&q=sitewide"
    assert read({s: rss(range(25))}, url=s, source="slickdeals")[2] == [s]
    d = "https://www.dealnews.com/x/"                                             # not a dealnews feed address
    assert read({d: rss(range(30))}, url=d)[2] == [d]
