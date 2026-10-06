from __future__ import annotations

from datetime import date, timedelta

from tourdesk.services.tour_status import TourEvent, compute_tour_status

TODAY = date(2026, 10, 6)


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


def test_on_tour_when_today_inside_cluster() -> None:
    events = [TourEvent(d(-5), tour_name="World Tour"), TourEvent(d(-2)), TourEvent(d(3)), TourEvent(d(8))]
    status = compute_tour_status(events, TODAY)
    assert status.state == "on_tour"
    assert status.emoji == "🟢"
    assert status.tour_name == "World Tour"
    assert status.upcoming_count == 2


def test_tour_with_only_two_filtered_dates_is_still_a_tour() -> None:
    # 15 official dates around today – status uses all of them
    events = [TourEvent(d(i * 3 - 12)) for i in range(15)]
    assert compute_tour_status(events, TODAY).state == "on_tour"


def test_announced_when_cluster_in_future() -> None:
    events = [TourEvent(d(60)), TourEvent(d(62)), TourEvent(d(70))]
    status = compute_tour_status(events, TODAY)
    assert status.state == "announced"
    assert status.emoji == "🔵"
    assert status.next_date == d(60)


def test_not_on_tour_without_upcoming() -> None:
    status = compute_tour_status([TourEvent(d(-30))], TODAY)
    assert status.state == "not_on_tour"
    assert status.emoji == "⚪"
    assert "Letzter bekannter Termin" in status.detail
    assert compute_tour_status([], TODAY).detail == "Keine bekannten Termine"


def test_cancelled_and_unconfirmed_ignored() -> None:
    events = [TourEvent(d(5), status="cancelled"), TourEvent(d(6), is_confirmed=False)]
    assert compute_tour_status(events, TODAY).state == "not_on_tour"


def test_gap_splits_clusters() -> None:
    events = [TourEvent(d(-10)), TourEvent(d(-3)), TourEvent(d(100)), TourEvent(d(105))]
    # last show 3 days ago, next leg in 100 days -> announced (not currently touring)
    assert compute_tour_status(events, TODAY).state == "announced"


def test_same_tour_bridges_gap() -> None:
    events = [TourEvent(d(-10), tour_id=1), TourEvent(d(-3), tour_id=1), TourEvent(d(100), tour_id=1)]
    assert compute_tour_status(events, TODAY).state == "on_tour"


def test_single_show_today() -> None:
    status = compute_tour_status([TourEvent(TODAY, city_name="Saarbrücken")], TODAY)
    assert status.state == "announced"
    assert status.detail == "Heute live in Saarbrücken"
