"""SQLAlchemy models. Importing this package registers all tables on ``Base.metadata``."""

from tourdesk.models.artist import Artist, ArtistAlias, UserArtist
from tourdesk.models.base import Base
from tourdesk.models.crawler import (
    AppSetting,
    CrawlerDomain,
    CrawlerError,
    CrawlerJob,
    CrawlerRun,
    GeocodeCache,
    HttpCacheEntry,
    SystemHeartbeat,
)
from tourdesk.models.event import Event, EventSource, Festival, TicketSource, Tour
from tourdesk.models.filters import UserCity, UserCountry, UserFilter, UserRegion, UserVenue
from tourdesk.models.geo import City, Country, Region, Venue
from tourdesk.models.notification import Notification, NotificationChannel, NotificationDelivery
from tourdesk.models.source import Source
from tourdesk.models.user import AuditLog, Role, User, UserSession, UserSettings

__all__ = [
    "AppSetting",
    "Artist",
    "ArtistAlias",
    "AuditLog",
    "Base",
    "City",
    "Country",
    "CrawlerDomain",
    "CrawlerError",
    "CrawlerJob",
    "CrawlerRun",
    "Event",
    "EventSource",
    "Festival",
    "GeocodeCache",
    "HttpCacheEntry",
    "Notification",
    "NotificationChannel",
    "NotificationDelivery",
    "Region",
    "Role",
    "Source",
    "SystemHeartbeat",
    "TicketSource",
    "Tour",
    "User",
    "UserArtist",
    "UserCity",
    "UserCountry",
    "UserFilter",
    "UserRegion",
    "UserSession",
    "UserSettings",
    "UserVenue",
    "Venue",
]
