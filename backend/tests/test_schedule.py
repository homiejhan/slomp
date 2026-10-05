"""Schedules: reading days, times and end dates from the wording deal pages use, and the dates a deal runs on."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from slomp.schedule import Schedule, last_day, parse_days, says_recurring, single_dates, time_windows, weekdays_in

CT = ZoneInfo("America/Chicago")
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


def test_weekdays_named_ranged_and_excepted():
    assert weekdays_in("buy one order of wings, get one free on Tuesdays and Thursdays") == [TUE, THU]
    assert weekdays_in("Typical happy hours at Chuy's are 3-6 pm Mondays through Fridays") == [MON, TUE, WED, THU, FRI]
    assert weekdays_in("a Happy Hour every day but Saturday with drinks starting at $5") == [MON, TUE, WED, THU, FRI, SUN]
    assert weekdays_in("half-priced games on Sundays-Thursdays and more deals") == [MON, TUE, WED, THU, SUN]
    assert weekdays_in("Enjoy Half-Off Golf all day Monday-Thursday when you book online") == [MON, TUE, WED, THU]
    assert weekdays_in("$5 margaritas and house drinks, Mon-Fri 3-7pm") == [MON, TUE, WED, THU, FRI]
    assert weekdays_in("brunch specials on Saturdays and Sundays from open – 3 PM") == [SAT, SUN]
    assert weekdays_in("$5 small cheeseburger weekdays 2–6 pm") == [MON, TUE, WED, THU, FRI]
    assert weekdays_in("specials available all day, every day") == list(range(7))
    assert weekdays_in("a great deal mid-week") == []


def test_weekday_names_that_are_not_schedules():
    assert weekdays_in("Cheeseburgers and select sandwiches are $6.99 at Ruby Tuesday") == []
    assert weekdays_in("TGI Fridays has $5 appetizers on Mondays") == [MON]
    assert weekdays_in('"I don\'t celebrate joy, but I do acknowledge exceptional tacos." Wednesday Addams') == []
    assert weekdays_in("He sat down and wed her under the sun") == []        # short forms only count inside a range


def test_registry_day_words():
    assert parse_days(["tue"]) == ([TUE], "")
    assert parse_days(["tuesday", "wed"]) == ([TUE, WED], "")
    assert parse_days(["weekdays"]) == ([MON, TUE, WED, THU, FRI], "")
    assert parse_days(["daily"]) == (list(range(7)), "")
    assert parse_days(["first tue"]) == ([], "1:1")
    assert parse_days(["last fri"]) == ([], "-1:4")
    assert parse_days(["7th"]) == ([], "d:7")


def test_time_windows_need_am_or_pm():
    assert time_windows("After 5 p.m. local time on Wednesdays, rewards members can enjoy a BOGO") == ([(time(17), None)], "")
    assert time_windows("every day from 2-5PM, Sonic rewards members can get one of these snacks") == ([(time(14), time(17))], "")
    assert time_windows("Endless Garden Bar Salad for $7.99 until 4 p.m. on Wednesdays") == ([(None, time(16))], "")
    assert time_windows("Typical happy hours at Chuy's are 3-6 pm pm Mondays through Fridays") == ([(time(15), time(18))], "")
    assert time_windows("hamburgers for $1 each from 2 p.m. until close") == ([(time(14), None)], "")
    assert time_windows("brunch menu on Saturdays and Sundays from open – 3 PM") == ([(None, time(15))], "")
    assert time_windows("From 10:30 AM – 8 PM, double up on your protein") == ([(time(10, 30), time(20))], "")
    assert time_windows("EVERY MONDAY 11AM–9PM Half off all burgers") == ([(time(11), time(21))], "")
    assert time_windows("lunch special 11-2 pm") == ([(time(11), time(14))], "")
    assert time_windows("Monday – Thursday from 4-7 pm and 10 pm – midnight") == ([(time(16), time(19)), (time(22), time(23, 59))], "")
    # numbers that are not times
    assert time_windows("buy one 6, 10 or 15 piece order of traditional wings") == ([], "")
    assert time_windows("Kids 12 and under also eat free with a $6 adult entree (reg. $9.99)") == ([], "")
    assert time_windows("two Two-Meat Plates for $29") == ([], "")


def test_time_in_another_zone_is_converted_for_the_city():
    w, zone = time_windows("codes are only available after 2 p.m. PT (5 p.m. ET) in the Taco Bell app")
    assert (w, zone) == ([(time(14), None)], "America/Los_Angeles")
    s = Schedule(days=[TUE], windows=w, zone=zone)
    assert s.local_windows(date(2026, 10, 6), CT) == [(time(16), None)]
    assert s.time_text(date(2026, 10, 6), CT) == "after 4 pm"


def test_last_day_from_wording():
    ref = date(2026, 9, 30)
    assert last_day("half-price Sonic cheeseburgers after 5 p.m. local. Offer valid through Dec. 31.", ref) == date(2026, 12, 31)
    assert last_day("an in-app offer at Cicis Pizza every Monday through Dec. 30, 2026.", ref) == date(2026, 12, 30)
    assert last_day("Get four chili dogs for $4 at Wienerschnitzel every Wednesday in September.", ref) == date(2026, 9, 30)
    assert last_day("any 20-ounce specialty beverage for $5 every Friday at Biggby Coffee through Oct. 30.", ref) == date(2026, 10, 30)
    assert last_day("BOGO bowls for Seacret Society members all October", ref) == date(2026, 10, 31)
    assert last_day("deals valid thru 10/6/26", ref) == date(2026, 10, 6)
    assert last_day("Get BOGO traditional wings. Offer is available for online and dine-in orders.", ref) is None
    assert last_day("Kids eat free through January 5", date(2026, 12, 20)) == date(2027, 1, 5)       # the nearest year
    assert last_day("you may get a coupon", ref) is None                                           # "may" the verb
    # it12 trial: a month is not the end date when one is stated, and the first stated date is the offer's
    assert last_day("This October, Del Taco is celebrating Tacoberfest with a BOGO free deal. Offer valid through Oct. 4.",
                    ref) == date(2026, 10, 4)
    assert last_day("Through Oct. 3, get a reward for a free pretzel. Reward redeemable through Oct. 31.", ref) == date(2026, 10, 3)


def test_one_off_dates_are_not_regular():
    ref = date(2026, 9, 29)
    text = "On Tuesday, Sept. 29, get classic hamburgers for $1 each at Jack's from 2 p.m. until close."
    assert single_dates(text, ref) == [date(2026, 9, 29)] and not says_recurring(text)
    assert single_dates("free coffee for National Coffee Day on Sept. 29. No purchase necessary.", ref) == [date(2026, 9, 29)]
    assert single_dates("$1.49 Mozzarella Sticks when ordered online on Sept. 22 and 29.", ref) == [date(2026, 9, 22)]
    every = "Every Tuesday, rewards members can grab half-price cheeseburgers after 5 p.m. Offer valid through Dec. 31."
    assert single_dates(every, ref) == [] and says_recurring(every)
    assert says_recurring("Get 8 tenders and four dipping sauces for $10 at KFC on Thursdays.")
    assert not says_recurring("Cheeseburgers are $6.99 at Ruby Tuesday.")


def test_runs_on_weekly_monthly_and_within_its_dates():
    assert Schedule(days=[WED]).runs_on(date(2026, 10, 7)) and not Schedule(days=[WED]).runs_on(date(2026, 10, 8))
    first_tue = Schedule(monthly="1:1")
    assert first_tue.runs_on(date(2026, 10, 6)) and not first_tue.runs_on(date(2026, 10, 13))
    assert Schedule(monthly="-1:4").runs_on(date(2026, 10, 30)) and not Schedule(monthly="-1:4").runs_on(date(2026, 10, 23))
    assert Schedule(monthly="d:7").runs_on(date(2026, 10, 7))
    ended = Schedule(days=[WED], until=date(2026, 9, 30))
    assert ended.runs_on(date(2026, 9, 30)) and not ended.runs_on(date(2026, 10, 7))


def test_occurrences_in_a_seven_day_window():
    mon_10am = datetime(2026, 10, 5, 10, 0, tzinfo=CT)
    end = datetime(2026, 10, 12, 10, 0, tzinfo=CT)
    assert Schedule(days=[WED]).occurrences(mon_10am, end) == [date(2026, 10, 7)]
    # today's weekday falls in the window twice: today, and the same day next week
    assert Schedule(days=[MON]).occurrences(mon_10am, end) == [date(2026, 10, 5), date(2026, 10, 12)]
    assert Schedule(days=list(range(7))).occurrences(mon_10am, end)[0] == date(2026, 10, 5)
    assert len(Schedule(days=list(range(7))).occurrences(mon_10am, end)) == 8
    # past its last day
    assert Schedule(days=[WED], until=date(2026, 9, 30)).occurrences(mon_10am, end) == []
    assert Schedule(days=[TUE, FRI], until=date(2026, 10, 6)).occurrences(mon_10am, end) == [date(2026, 10, 6)]


def test_todays_window_already_over_or_next_weeks_not_begun():
    wed_5pm = datetime(2026, 10, 7, 17, 0, tzinfo=CT)
    end = datetime(2026, 10, 14, 17, 0, tzinfo=CT)
    until_4 = Schedule(days=[WED], windows=[(None, time(16))])
    assert until_4.occurrences(wed_5pm, end) == [date(2026, 10, 14)]                 # today's is over; next week's counts
    after_5 = Schedule(days=[WED], windows=[(time(17), None)])
    assert after_5.occurrences(wed_5pm, end) == [date(2026, 10, 7)]                  # next week's starts as the window ends
    assert after_5.occurrences(datetime(2026, 10, 7, 9, 0, tzinfo=CT), datetime(2026, 10, 14, 9, 0, tzinfo=CT)) == \
        [date(2026, 10, 7)]
    happy = Schedule(days=[WED], windows=[(time(15), time(18))])
    assert happy.occurrences(wed_5pm, end) == [date(2026, 10, 7), date(2026, 10, 14)]


def test_the_clocks_changing_inside_the_window():
    # Central time falls back on Nov 1, 2026: the window still holds each weekday once (plus today's twin)
    start = datetime(2026, 10, 29, 12, 0, tzinfo=CT)
    from datetime import timedelta
    end = start + timedelta(days=7)
    assert Schedule(days=[SUN]).occurrences(start, end) == [date(2026, 11, 1)]
    assert Schedule(days=[THU]).occurrences(start, end) == [date(2026, 10, 29), date(2026, 11, 5)]


def test_wording():
    assert Schedule(days=[TUE]).days_text() == "Every Tuesday"
    assert Schedule(days=[TUE, THU]).days_text() == "Tuesdays and Thursdays"
    assert Schedule(days=[MON, TUE, WED, THU, FRI]).days_text() == "Monday to Friday"
    assert Schedule(days=[SUN, MON, TUE, WED, THU]).days_text() == "Sunday to Thursday"
    assert Schedule(days=[SAT, SUN]).days_text() == "Saturdays and Sundays"
    assert Schedule(days=[MON, WED, FRI]).days_text() == "Mondays, Wednesdays and Fridays"
    assert Schedule(days=list(range(7))).days_text() == "Every day"
    assert Schedule(monthly="1:1").days_text() == "First Tuesday of the month"
    assert Schedule(monthly="d:7").days_text() == "The 7th of each month"
    assert Schedule(windows=[(time(17), None)]).time_text() == "after 5 pm"
    assert Schedule(windows=[(None, time(16))]).time_text() == "until 4 pm"
    assert Schedule(windows=[(time(14), time(17))]).time_text() == "2–5 pm"
    assert Schedule(windows=[(time(11), time(21))]).time_text() == "11 am–9 pm"
    assert Schedule(windows=[(time(10, 30), time(20))]).time_text() == "10:30 am–8 pm"
    assert Schedule(windows=[(time(22), time(23, 59))]).time_text() == "10 pm–midnight"
    assert Schedule(windows=[(time(11), time(12))]).time_text() == "11 am–noon"
