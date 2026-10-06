"""Enumerations used by models, API and crawler (stored as strings)."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class RoleKey(StrEnum):
    USER = "user"
    ADMIN = "admin"


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class EventType(StrEnum):
    CONCERT = "concert"
    FESTIVAL = "festival"
    SUPPORT = "support"
    SPECIAL = "special"


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    RESCHEDULED = "rescheduled"


class TicketStatus(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    LIMITED = "limited"
    SOLD_OUT = "sold_out"
    NOT_ON_SALE = "not_on_sale"
    PRESALE = "presale"
    BOX_OFFICE = "box_office"
    FREE = "free"
    CANCELLED = "cancelled"


class TrustLevel(IntEnum):
    """Lower value = more trustworthy."""

    OFFICIAL_ARTIST = 1
    OFFICIAL_VENUE = 2
    PROMOTER = 3
    OFFICIAL_TICKETING = 4
    PLATFORM = 5
    OTHER = 6


TRUST_LABELS = {
    1: "Offizielle Künstlerwebsite",
    2: "Offizieller Veranstaltungsort",
    3: "Veranstalter / Festival",
    4: "Offizieller Ticketanbieter",
    5: "Ticketbörse / Plattform",
    6: "Sonstige Quelle",
}


class SourceScope(StrEnum):
    ARTIST = "artist"
    VENUE = "venue"
    FESTIVAL = "festival"
    GLOBAL = "global"


class SourceStatus(StrEnum):
    NEW = "new"
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"


class CrawlStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    DISABLED = "disabled"


class JobType(StrEnum):
    ARTIST_CRAWL = "artist_crawl"
    SOURCE_CRAWL = "source_crawl"
    ARTIST_ENRICH = "artist_enrich"
    SOURCE_CHECK = "source_check"
    MAINTENANCE = "maintenance"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class LocationLevel(StrEnum):
    COUNTRY = "country"
    REGION = "region"
    CITY = "city"
    VENUE = "venue"


class FestivalMode(StrEnum):
    ARTIST = "artist"  # per-artist switch decides
    ALWAYS = "always"
    NEVER = "never"


class FestivalScope(StrEnum):
    FILTERS = "filters"  # festivals must match location rules too
    ANYWHERE = "anywhere"


class DateMode(StrEnum):
    UPCOMING = "upcoming"
    MONTHS = "months"
    RANGE = "range"


class NotificationType(StrEnum):
    NEW_EVENTS = "new_events"
    EVENT_IN_REGION = "event_in_region"
    TICKETS_ON_SALE = "tickets_on_sale"
    EVENT_CHANGED = "event_changed"
    EVENT_CANCELLED = "event_cancelled"
    FESTIVAL_CONFIRMED = "festival_confirmed"
    SYSTEM = "system"


NOTIFICATION_LABELS = {
    "new_events": "Neue Konzerttermine",
    "event_in_region": "Konzert in bevorzugter Region",
    "tickets_on_sale": "Ticketverkauf gestartet",
    "event_changed": "Termin geändert",
    "event_cancelled": "Konzert abgesagt / verschoben",
    "festival_confirmed": "Festivalauftritt bestätigt",
    "system": "Systemmeldungen",
}


class TourState(StrEnum):
    ON_TOUR = "on_tour"
    ANNOUNCED = "announced"
    NOT_ON_TOUR = "not_on_tour"
