"""Extraction from realistic page fixtures (no network)."""

from __future__ import annotations

import json
from datetime import date, time

from tourdesk_crawler.extract import extract_events
from tourdesk_crawler.extract.heuristics import lineup_names
from tourdesk_crawler.extract.html import TOUR_KEYWORDS, discover_links, parse_html
from tourdesk_crawler.extract.ical import extract_ical

TODAY = date(2026, 10, 6)
CITIES = {"saarbrücken", "esch-sur-alzette", "luxembourg", "metz", "trier", "paris", "amsterdam", "köln"}
COUNTRIES = {"de", "lu", "fr", "germany", "luxembourg", "france", "deutschland"}


def is_city(s: str) -> bool:
    return s.strip().casefold() in CITIES


def is_country(s: str) -> bool:
    return s.strip().casefold() in COUNTRIES


JSONLD_PAGE = """
<html lang="en"><head><title>Tour</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"MusicEvent","name":"Backstreet Boys - DNA World Tour","startDate":"2027-03-12T20:00:00+01:00",
  "doorTime":"19:00","eventStatus":"https://schema.org/EventScheduled",
  "location":{"@type":"Place","name":"Rockhal","address":{"@type":"PostalAddress","addressLocality":"Esch-sur-Alzette","addressCountry":"LU"}},
  "performer":[{"@type":"MusicGroup","name":"Backstreet Boys"}],
  "offers":{"@type":"Offer","url":"https://www.ticketmaster.lu/event/123","availability":"https://schema.org/SoldOut","price":"89.50","priceCurrency":"EUR"},
  "url":"https://backstreetboys.example/tour/rockhal"},
 {"@type":"MusicEvent","name":"Backstreet Boys","startDate":"2027-03-15","eventStatus":"EventCancelled",
  "location":{"@type":"Place","name":"Garage","address":"Bleichstraße 11, 66111 Saarbrücken, Germany"}},
 {"@type":"Organization","name":"Not an event"}
]}
</script></head><body></body></html>
"""


def test_jsonld_events() -> None:
    events, method = extract_events(JSONLD_PAGE, "https://backstreetboys.example/tour", today=TODAY)
    assert method == "jsonld" and len(events) == 2
    a, b = events
    assert a.start_date == date(2027, 3, 12) and a.start_time == time(20, 0) and a.doors_time == time(19, 0)
    assert a.venue_name == "Rockhal" and a.city == "Esch-sur-Alzette" and a.country == "LU"
    assert a.ticket_status == "sold_out" and a.ticket_url == "https://www.ticketmaster.lu/event/123"
    assert a.price_min == 89.5 and a.currency == "EUR"
    assert a.performers == ["Backstreet Boys"]
    assert b.status == "cancelled" and b.city == "Saarbrücken" and b.venue_name == "Garage"


MICRODATA_PAGE = """
<div itemscope itemtype="http://schema.org/MusicEvent">
  <span itemprop="name">Metallica: M72 World Tour</span>
  <meta itemprop="startDate" content="2027-06-01T19:30">
  <div itemprop="location" itemscope itemtype="http://schema.org/Place">
    <span itemprop="name">Olympiastadion</span>
    <div itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
      <span itemprop="addressLocality">Berlin</span><span itemprop="addressCountry">DE</span>
    </div>
  </div>
  <div itemprop="offers" itemscope itemtype="http://schema.org/Offer"><a itemprop="url" href="/tickets/1">Tickets</a></div>
</div>
"""


def test_microdata_events() -> None:
    events, method = extract_events(MICRODATA_PAGE, "https://metallica.example/tour", today=TODAY)
    assert method == "microdata" and len(events) == 1
    ev = events[0]
    assert ev.start_date == date(2027, 6, 1) and ev.start_time == time(19, 30)
    assert ev.venue_name == "Olympiastadion" and ev.city == "Berlin" and ev.country == "DE"
    assert ev.ticket_url == "https://metallica.example/tickets/1"


NEXT_PAGE = """<html><body><div id="__next"></div>
<script id="__NEXT_DATA__" type="application/json">""" + json.dumps({
    "props": {"pageProps": {"tour": {"dates": [
        {"id": "a1", "date": "2027-04-02T20:00:00", "venue": {"name": "Ziggo Dome", "city": "Amsterdam", "country": "Netherlands"},
         "ticketUrl": "https://tickets.example/a1", "soldOut": True},
        {"id": "a2", "date": "2027-04-05", "venue": {"name": "Lanxess Arena", "city": "Köln", "country": "Germany"}, "status": "postponed"},
    ]}}}
}) + """</script></body></html>"""


def test_embedded_next_data() -> None:
    events, method = extract_events(NEXT_PAGE, "https://band.example/tour", today=TODAY)
    assert method == "embedded" and len(events) == 2
    assert events[0].venue_name == "Ziggo Dome" and events[0].city == "Amsterdam" and events[0].ticket_status == "sold_out"
    assert events[1].status == "postponed" and events[1].external_id == "a2"


HEURISTIC_PAGE = """
<html lang="de"><body>
<nav><a href="/">Home</a> <a href="/tour">Tour</a></nav>
<h1>Tourdaten 2027</h1>
<ul class="tour-dates">
  <li><span class="date">Fr, 12.03.2027</span> <span class="venue">Rockhal</span> – <span class="city">Esch-sur-Alzette, LU</span>
      <a href="https://www.eventim.de/event/1">Tickets</a></li>
  <li><span class="date">15. März 2027</span> | Garage | Saarbrücken | 20:00 Uhr <strong>Ausverkauft</strong></li>
  <li><span>18.03.2027</span> Europahalle, Trier – ABGESAGT</li>
  <li><span>20.03.2027</span> <span>BAM</span> <span>Metz</span> <span>FR</span> Einlass 19:00 Beginn 20:00</li>
</ul>
<p>Newsletter abonnieren</p>
</body></html>
"""


def test_heuristic_list_page() -> None:
    events, method = extract_events(HEURISTIC_PAGE, "https://band.example/tour", today=TODAY, is_city=is_city, is_country=is_country)
    assert method == "heuristic"
    assert [e.start_date for e in events] == [date(2027, 3, 12), date(2027, 3, 15), date(2027, 3, 18), date(2027, 3, 20)]
    rockhal, garage, trier, metz = events
    assert rockhal.venue_name == "Rockhal" and rockhal.city == "Esch-sur-Alzette" and rockhal.country == "LU"
    assert rockhal.ticket_url == "https://www.eventim.de/event/1" and rockhal.ticket_provider == "Eventim"
    assert garage.venue_name == "Garage" and garage.city == "Saarbrücken" and garage.ticket_status == "sold_out"
    assert garage.start_time == time(20, 0)
    assert trier.status == "cancelled" and trier.city == "Trier"
    assert metz.city == "Metz" and metz.start_time == time(20, 0) and metz.doors_time == time(19, 0)


TABLE_PAGE = """
<table class="events">
 <tr><th>Datum</th><th>Ort</th><th>Location</th></tr>
 <tr><td>05.06.2027</td><td>Paris</td><td>Accor Arena</td></tr>
 <tr><td>07.06.2027</td><td>Amsterdam</td><td>Ziggo Dome</td></tr>
</table>
"""


def test_heuristic_table() -> None:
    events, _ = extract_events(TABLE_PAGE, "https://band.example/live", today=TODAY, is_city=is_city, is_country=is_country)
    assert [(e.city, e.venue_name) for e in events] == [("Paris", "Accor Arena"), ("Amsterdam", "Ziggo Dome")]


def test_news_page_without_locations_is_ignored() -> None:
    page = "<div><p>Gepostet am 12.03.2026 – Wir haben ein neues Album aufgenommen und freuen uns sehr.</p></div>"
    events, _ = extract_events(page, "https://band.example/news", today=TODAY, is_city=is_city, is_country=is_country)
    assert events == []


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1@venue
DTSTART;TZID=Europe/Luxembourg:20270312T200000
SUMMARY:Backstreet Boys
LOCATION:Rockhal, Esch-sur-Alzette, Luxembourg
URL:https://rockhal.example/agenda/1
END:VEVENT
BEGIN:VEVENT
UID:evt-2@venue
DTSTART;VALUE=DATE:20270320
DTEND;VALUE=DATE:20270323
SUMMARY:Festival Weekend
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_ical() -> None:
    events = extract_ical(ICS)
    assert len(events) == 2
    a, b = events
    assert a.start_date == date(2027, 3, 12) and a.start_time == time(20, 0)
    assert a.venue_name == "Rockhal" and a.city == "Esch-sur-Alzette" and a.country == "Luxembourg"
    assert b.status == "cancelled" and b.end_date == date(2027, 3, 22)


def test_tour_link_discovery() -> None:
    page = parse_html('<a href="/news">News</a><a href="/live/">Live</a><a href="https://other.example/tour">Tour</a><a href="/tour-dates">Tour Dates</a>')
    links = discover_links(page, "https://band.example/", TOUR_KEYWORDS)
    assert links[0] in ("https://band.example/tour-dates", "https://band.example/live/")
    assert all("other.example" not in u for u in links)


def test_lineup_names() -> None:
    soup = parse_html("""<ul class="lineup"><li><a>Linkin Park</a></li><li><a>Backstreet Boys</a></li></ul>
    <div class="artist-name">Die Toten Hosen</div><div>Impressum</div>""")
    names = lineup_names(soup)
    assert {"Linkin Park", "Backstreet Boys", "Die Toten Hosen"} <= set(names)
    assert "Impressum" not in names
