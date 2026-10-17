"""slomp replay: deal-site posts through Slomp's own feed parsers and filters, offline (slomp/verify/replay.py)."""
import json
from datetime import datetime

import pytest

from slomp.verify.replay import main, post_of, replay

NOW = datetime.fromisoformat("2026-10-17T12:00:00-05:00")
POSTED = "2026-10-16T09:00:00-05:00"


def test_a_sale_post_is_read_by_dealnews_parser_with_its_stated_end():
    sale = {"source": "dealnews", "kind": "sale", "title": "adidas Fall Favorites Sale: Up to 50% off + extra 30% off",
            "text": 'Use code "FALL" to get the extra discount.', "seller": "adidas", "deal_type": "sale",
            "posted": POSTED, "expires": "2026-10-19"}
    v, = replay([sale], NOW)
    assert (v["kept"], v["store"], v["code"], v["ends"]) == (True, "adidas", "FALL", "2026-10-19")
    assert v["ends_how"] == "dealnews gives this end date"
    # no end given: dealnews' placeholder end, which Slomp knows is not the sale's
    v, = replay([{**sale, "expires": None}], NOW)
    assert v["kept"] and v["ends"] is None
    assert post_of({**sale, "expires": None}, 0, NOW).expires_stated is False


def test_an_online_post_and_a_promotion():
    dog_bed = {"source": "hip2save", "kind": "online",
               "title": "Orthopedic Dog Bed Only $19.99 on Amazon (Reg. $39.99)",
               "text": "Hop over to Amazon where this dog bed is on sale.", "posted": POSTED, "categories": ["Pets"]}
    no_reference = {"source": "slickdeals", "kind": "online", "title": "Bose QuietComfort Ultra Headphones $299",
                    "text": "Amazon has them for $299.", "posted": POSTED}
    taco = {"source": "dealnews", "kind": "promo", "title": "Taco Bell $4 Usual: through October 19",
            "text": "Taco Bell is offering its $4 Usual box through October 19.", "seller": "Taco Bell",
            "category": "Restaurants", "posted": POSTED}
    bed, bose, promo = replay([dog_bed, no_reference, taco], NOW)
    assert (bed["kept"], bed["price"], bed["reference"], bed["pct"], bed["industries"]) == \
        (True, 19.99, 39.99, 50.0, ["pets"])
    assert (bose["kept"], bose["price"], bose["why"]) == (False, 299.0, "no reference price: never ranked")
    assert (promo["kept"], promo["chain"], promo["to"]) == (True, "Taco Bell", "2026-10-19")


def test_a_post_from_a_site_slomp_does_not_read_is_an_error():
    with pytest.raises(ValueError, match="unknown source"):
        replay([{"source": "groupon", "title": "x"}], NOW)
    with pytest.raises(ValueError, match="unknown kind"):
        replay([{"source": "dealnews", "kind": "coupon", "title": "x"}], NOW)


def test_the_command_prints_a_line_per_post_and_the_totals(tmp_path, capsys):
    posts = tmp_path / "posts.json"
    posts.write_text(json.dumps([{"source": "dealnews", "kind": "sale", "title": "Ends tonight", "posted": POSTED}]))
    assert main(posts, NOW.isoformat()) == 0
    out = capsys.readouterr().out
    assert "[sale] dealnews: Ends tonight\n    left out: " in out and "sale: 0 kept, 1 left out" in out
