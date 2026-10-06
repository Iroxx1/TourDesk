"""Regression tests: an error in one step of a crawler job must not break the rest of the job.

On the first crawl of an artist, the API sources (Ticketmaster, …) are created on the fly.
They used to be only flushed: when the official website failed afterwards (e.g. HTTP 403
from Cloudflare), the per-source rollback discarded the new Ticketmaster source and the
next source raised ``ObjectDeletedError`` – the whole job failed on every retry.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import func, select

import tourdesk_crawler.jobs.context as job_context
import tourdesk_crawler.jobs.enrich as enrich_job
from tourdesk.core.db import get_engine, get_session_factory
from tourdesk.core.text import normalize_name
from tourdesk.models import Artist, ArtistAlias, CrawlerError, CrawlerJob, CrawlerRun, Event, EventSource, Source
from tourdesk.services.app_settings import update_crawler_settings
from tourdesk_crawler.jobs.runner import run_job_inline
from tourdesk_crawler.pipeline.models import ProviderResult, RawEvent
from tourdesk_crawler.providers.apis import TicketmasterProvider
from tourdesk_crawler.providers.web import ArtistWebsiteProvider

EVENT_DAY = date.today() + timedelta(days=60)


def cloudflare_block(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(403, text="<html><title>Just a moment...</title></html>", headers={"server": "cloudflare"})


def ticketmaster_one_event(self, ctx, source, artist) -> ProviderResult:
    raw = RawEvent(
        start_date=EVENT_DAY,
        title="Testband – World Tour",
        performers=["Testband"],
        venue_name="Garage",
        city="Saarbrücken",
        country="DE",
        url="https://www.ticketmaster.de/event/0815",
        ticket_url="https://www.ticketmaster.de/event/0815",
        ticket_provider="Ticketmaster",
        ticket_status="available",
        external_id="0815",
        method="api",
        confidence=0.95,
    )
    return ProviderResult(events=[raw], method="api", pages=1, http_status=200)


def broken_website(self, ctx, source, artist) -> ProviderResult:
    raise RuntimeError("Parser abgestürzt")


@pytest.mark.parametrize("website_failure", ["http_403", "provider_exception"])
def test_failing_website_keeps_new_ticketmaster_source(db, monkeypatch, make_user, website_failure) -> None:
    monkeypatch.setattr(job_context, "TRANSPORT_OVERRIDE", httpx.MockTransport(cloudflare_block))
    monkeypatch.setattr("tourdesk_crawler.http.client.PoliteHttpClient._wait_for_slot", lambda self, d, i: None)
    monkeypatch.setattr("tourdesk_crawler.http.client.time.sleep", lambda s: None)
    monkeypatch.setattr(TicketmasterProvider, "fetch", ticketmaster_one_event)
    if website_failure == "provider_exception":
        monkeypatch.setattr(ArtistWebsiteProvider, "fetch", broken_website)
    update_crawler_settings(db, {"api_keys": {"ticketmaster": "test-key"}}, None)
    db.commit()

    alice = make_user("alice")
    resp = alice.post("/api/artists", json={"name": "Testband", "official_website": "https://testband.test"})
    assert resp.status_code == 201, resp.text
    artist_id = resp.json()["id"]

    result = run_job_inline("artist_crawl", artist_id=artist_id)

    # before the fix: {"error": "ObjectDeletedError: Instance '<Source at …>' has been deleted, …"}
    assert "error" not in result, result
    assert result["status"] == "partial"
    assert (result["sources_ok"], result["sources_failed"], result["events_new"]) == (1, 1, 1)

    with get_session_factory()() as fresh:  # a new session only sees committed data
        sources = {s.provider: s for s in fresh.execute(select(Source).where(Source.artist_id == artist_id)).scalars()}
        assert set(sources) == {"official_website", "ticketmaster"}
        website, ticketmaster = sources["official_website"], sources["ticketmaster"]
        assert ticketmaster.is_auto and ticketmaster.status == "ok" and ticketmaster.last_event_count == 1
        assert website.status == "error" and website.consecutive_failures == 1 and website.next_attempt_at is not None
        if website_failure == "http_403":
            assert website.last_http_status == 403 and website.last_error_type == "http_error"
        else:
            assert website.last_error_type == "parse_error" and "Parser abgestürzt" in (website.last_error or "")

        events = list(fresh.execute(select(Event).where(Event.artist_id == artist_id)).unique().scalars())
        assert [e.event_date for e in events] == [EVENT_DAY]
        observed_by = fresh.execute(select(EventSource.source_id).where(EventSource.event_id == events[0].id)).scalars().all()
        assert observed_by == [ticketmaster.id]
        assert fresh.execute(select(CrawlerError.source_id)).scalars().all() == [website.id]
        job = fresh.execute(select(CrawlerJob).where(CrawlerJob.artist_id == artist_id, CrawlerJob.worker_id == "inline")).scalar_one()
        assert job.status == "partial"

    # the next run reuses the committed source instead of creating another one
    again = run_job_inline("artist_crawl", artist_id=artist_id)
    assert again["status"] == "partial" and again["events_new"] == 0, again
    with get_session_factory()() as fresh:
        count = fresh.scalar(select(func.count()).select_from(Source).where(Source.artist_id == artist_id, Source.provider == "ticketmaster"))
        assert count == 1


def test_enrich_survives_db_error_while_applying_musicbrainz(db, monkeypatch, make_user) -> None:
    """A failed flush in the MusicBrainz step (here: alias added concurrently) must not fail the job."""
    monkeypatch.setattr(job_context, "TRANSPORT_OVERRIDE", httpx.MockTransport(lambda request: httpx.Response(404)))
    monkeypatch.setattr(enrich_job.musicbrainz, "search_artists",
                        lambda name, ua, limit=5: [{"mbid": "mbid-testband", "name": "Testband", "score": 100}])
    monkeypatch.setattr(enrich_job.musicbrainz, "lookup_artist", lambda mbid, ua: {
        "mbid": mbid, "aliases": ["The Testband"], "urls": {"official homepage": ["https://testband.test"]},
    })
    monkeypatch.setattr(enrich_job, "find_and_store_image", lambda http, artist, order: None)
    real_add_aliases = enrich_job.add_aliases

    def add_aliases_with_concurrent_insert(session, artist, aliases, origin) -> None:
        artist.aliases  # noqa: B018 - loaded before another request stores the same alias
        with get_engine().begin() as conn:
            conn.execute(ArtistAlias.__table__.insert().values(
                artist_id=artist.id, alias="The Testband", alias_norm=normalize_name("The Testband"), origin="user"))
        real_add_aliases(session, artist, aliases, origin)  # flush → unique violation

    monkeypatch.setattr(enrich_job, "add_aliases", add_aliases_with_concurrent_insert)

    alice = make_user("alice")
    artist_id = alice.post("/api/artists", json={"name": "Testband"}).json()["id"]
    result = run_job_inline("artist_enrich", artist_id=artist_id)

    # before the fix: {"error": "PendingRollbackError: This Session's transaction has been rolled back …"}
    assert "error" not in result, result
    assert result["musicbrainz"] is False
    with get_session_factory()() as fresh:
        artist = fresh.get(Artist, artist_id)
        assert artist.enriched_at is not None  # the image step still ran
        assert artist.official_website is None and "musicbrainz" not in (artist.external_ids or {})  # nothing half-applied
        assert fresh.execute(select(Source).where(Source.artist_id == artist_id)).first() is None
        assert [a.origin for a in artist.aliases] == ["user"]
        run = fresh.execute(select(CrawlerRun).where(CrawlerRun.job_type == "artist_enrich", CrawlerRun.artist_id == artist_id)).scalar_one()
        assert run.status == "partial" and run.errors_count == 1
