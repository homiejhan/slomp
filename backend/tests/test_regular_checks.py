"""The helpers the regular-deals verification reads pages with. Each case here was a wrong verdict in a trial run."""
from datetime import date, time
from types import SimpleNamespace

from slomp.sources.venues import Venues
from slomp.verify import regular_checks as rc
from slomp.verify.checks import FAIL, PASS

FACTS = {"amounts": [], "percents": [], "half": False, "bogo": False, "words": []}


def test_an_amount_is_matched_whole():
    f = {**FACTS, "amounts": ["$6"]}
    assert rc.has_facts("wings for $6.75 on thursdays", f) == ["$6"]              # "$6" is not "$6.75"
    assert rc.has_facts("a $60 gift card", f) == ["$6"]
    assert rc.has_facts("$6 margaritas. every monday.", f) == []                   # a full stop after it is fine
    assert rc.has_facts("happy hour with $1.00 gulf oysters", {**FACTS, "amounts": ["$1"]}) == []      # "$1" is "$1.00"
    assert rc.has_facts("happy hour with $1.50 gulf oysters", {**FACTS, "amounts": ["$1"]}) == ["$1"]


def test_half_price_and_buy_one_get_one_in_their_wordings():
    assert rc.has_facts("burgers are half price on mondays", {**FACTS, "percents": ["50%"], "half": True}) == []
    assert rc.has_facts("burgers are 20% off", {**FACTS, "half": True}) == ["half price"]
    assert rc.has_facts("buy any sandwich, get one free", {**FACTS, "bogo": True}) == []
    assert rc.has_facts("sandwiches are $5 on wednesdays", {**FACTS, "bogo": True}) == ["buy one get one"]


def test_a_page_about_one_schedule():
    senior = "seniors day ... your 20% discount ... " + "x " * 1500 + "once a month on the first tuesday"
    assert rc.one_schedule(senior)
    assert rc.one_schedule("happy hour monday - friday 3-6 pm")                    # one span is one schedule
    assert not rc.one_schedule("monday: $5 burgers. tuesday: $2 tacos. wednesday: half-price wine.")


def test_only_the_chains_own_entries_on_a_list_page():
    page = """<html><body><h1>Tuesday deals</h1>
      <ul><li><a href="/x">Del Taco</a>: Three tacos for $2.99 through Oct. 3.</li>
          <li>Taco Bell: $5 Luxe box. Not the same chain as Del Taco.</li></ul>
      <h2>Cracker Barrel</h2><p>Kids eat free on Tuesdays.</p>
      <h2>Chili's</h2><p>$6 margarita of the month.</p></body></html>"""
    words = lambda name: [" ".join(e.split()) for e in rc.entries(page, name)]             # noqa: E731
    assert words("Del Taco") == ["del taco : three tacos for $2.99 through oct. 3."]
    assert words("Cracker Barrel") == ["cracker barrel: kids eat free on tuesdays."]
    assert rc.entries(page, "Whataburger") == []


def test_an_end_date_that_has_passed():
    oct5 = date(2026, 10, 5)
    assert rc.ended("three tacos for $2.99 through oct. 3.", oct5) == date(2026, 10, 3)
    assert rc.ended("valid through sept. 30", oct5) == date(2026, 9, 30)
    assert rc.ended("valid through dec. 31", oct5) is None                         # still running
    assert rc.ended("ends october 1, 2026 but returns through nov. 20", oct5) is None   # the latest date counts


def test_hours_read_back_from_the_card():
    assert rc.shown_windows("after 5 pm") == [(time(17, 0), None)]
    assert rc.shown_windows("until 4 pm") == [(None, time(16, 0))]
    assert rc.shown_windows("2–5 pm") == [(time(14, 0), time(17, 0))]              # the start borrows "pm"
    assert rc.shown_windows("11 am–9 pm") == [(time(11, 0), time(21, 0))]
    assert rc.shown_windows("3–6 pm and after 9 pm") == [(time(15, 0), time(18, 0)), (time(21, 0), None)]
    assert rc.shown_windows("whenever") == []


def test_the_answer_keys_days():
    assert rc.key_days({"days": ["Tuesday", "thursday"]}) == ({1, 3}, "")
    assert rc.key_days({"days": ["weekdays"]}) == ({0, 1, 2, 3, 4}, "")
    assert rc.key_days({"days": ["daily"]}) == (set(range(7)), "")
    assert rc.key_days({"days": ["monthly: first tuesday"]}) == (set(), "monthly: first tuesday")


def shown(merchant, title, days, monthly=""):
    return SimpleNamespace(merchant=merchant, title=title,
                           regular={"days": days, "monthly": monthly, "days_text": "/".join(days) or monthly})


def test_recall_wants_the_deal_itself_not_just_the_place_and_day():
    v, today = Venues(), date(2026, 10, 5)
    key = {"brand": "Dave & Buster's", "offer": "Half-price games every Wednesday and Sunday, in store only",
           "days": ["wednesday", "sunday"], "kind": "official", "scope": "chain"}
    happy = shown("Dave & Buster's", "Dave & Buster's has a Happy Hour every day but Saturday with drinks starting at $5",
                  ["sun", "mon", "tue", "wed", "thu", "fri"])
    games = shown("Dave & Buster's", "Half-price games all day every Wednesday", ["wed"])
    # run 1 passed this on the happy hour card: same place, a shared day, another deal
    verdict, detail = rc.regular_recall(key, [happy], v, today)
    assert verdict == FAIL and "not this deal" in detail["why"]
    verdict, detail = rc.regular_recall(key, [happy, games], v, today)
    assert verdict == PASS and detail["slomp"].startswith("Dave & Buster's: Half-price games")
    assert {"half", "game"} <= set(detail["shared"])


def test_recall_counts_a_deal_slomp_is_holding_back_this_week():
    # run 1: the Bullock Museum's free first Sunday was in Slomp's data, but Oct 4 had passed and Nov 1 was 27 days off
    v, today = Venues(), date(2026, 10, 5)
    key = {"brand": "Bullock Texas State History Museum", "offer": "Free exhibition admission on the first Sunday of every month",
           "days": ["monthly: first sunday"], "kind": "official", "scope": "local"}
    held = [("Bullock Texas State History Museum", "H-E-B Free First Sunday: free exhibition admission", set(), "1:6")]
    assert rc.regular_recall(key, [], v, today)[0] == FAIL
    verdict, detail = rc.regular_recall(key, [], v, today, held)
    assert verdict == PASS and "not shown this week" in detail["note"]


def test_the_judge_is_told_which_days_page_a_list_entry_is_from():
    page = "<html><head><title>x</title></head><body><h1>26 Monday Restaurant Deals &amp; Specials</h1></body></html>"
    assert rc.heading(page) == "26 monday restaurant deals & specials"
