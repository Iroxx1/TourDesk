"""Ticket provider recognition and ticket/event status vocabulary."""

from __future__ import annotations

import re

from tourdesk.core.text import url_domain

# domain suffix -> (label, is_resale)
TICKET_DOMAINS: dict[str, tuple[str, bool]] = {
    "eventim.de": ("Eventim", False), "eventim.com": ("Eventim", False), "eventim.lu": ("Eventim", False),
    "eventim.at": ("Eventim", False), "eventim.ch": ("Eventim", False), "eventim.nl": ("Eventim", False),
    "eventim.be": ("Eventim", False), "oeticket.com": ("oeticket", False),
    "ticketmaster.de": ("Ticketmaster", False), "ticketmaster.com": ("Ticketmaster", False),
    "ticketmaster.fr": ("Ticketmaster", False), "ticketmaster.be": ("Ticketmaster", False),
    "ticketmaster.nl": ("Ticketmaster", False), "ticketmaster.co.uk": ("Ticketmaster", False),
    "ticketmaster.at": ("Ticketmaster", False), "ticketmaster.ch": ("Ticketmaster", False),
    "ticketmaster.lu": ("Ticketmaster", False), "ticketmaster.it": ("Ticketmaster", False),
    "ticketmaster.es": ("Ticketmaster", False), "ticketmaster.dk": ("Ticketmaster", False),
    "ticketmaster.se": ("Ticketmaster", False), "ticketmaster.no": ("Ticketmaster", False),
    "ticketmaster.pl": ("Ticketmaster", False), "ticketmaster.ie": ("Ticketmaster", False),
    "livenation.de": ("Live Nation", False), "livenation.com": ("Live Nation", False),
    "seetickets.com": ("See Tickets", False), "seetickets.de": ("See Tickets", False),
    "dice.fm": ("DICE", False), "reservix.de": ("Reservix", False), "adticket.de": ("ADticket", False),
    "myticket.de": ("MyTicket", False), "ticket-regional.de": ("Ticket Regional", False),
    "ticketcorner.ch": ("Ticketcorner", False), "ticketino.com": ("Ticketino", False),
    "fnacspectacles.com": ("Fnac Spectacles", False), "ticketnet.fr": ("Ticketnet", False),
    "ticketone.it": ("TicketOne", False), "axs.com": ("AXS", False), "eventbrite.com": ("Eventbrite", False),
    "eventbrite.de": ("Eventbrite", False), "luxembourg-ticket.lu": ("Luxembourg Ticket", False),
    "tixforgigs.com": ("tixforgigs", False), "ticketswap.com": ("TicketSwap", True), "ticketswap.de": ("TicketSwap", True),
    "viagogo.com": ("viagogo", True), "viagogo.de": ("viagogo", True), "stubhub.com": ("StubHub", True),
    "stubhub.de": ("StubHub", True), "fansale.de": ("fanSALE", True), "seatgeek.com": ("SeatGeek", True),
    "bandsintown.com": ("Bandsintown", False), "songkick.com": ("Songkick", False),
    "ticketportal.de": ("Ticketportal", False), "kartenhaus.de": ("Kartenhaus", False),
    "tickets.lu": ("Tickets.lu", False), "proticket.de": ("ProTicket", False),
}

TICKET_WORDS = re.compile(
    r"\b(tickets?|karten|billets?|billetterie|kaarten|biglietti|entradas|kaufen|buy|book now|réserver|reservieren|"
    r"vorverkauf|vvk|jetzt sichern|get tickets)\b",
    re.I,
)

STATUS_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(abgesagt|cancel+ed|annulé|annule|afgelast|gecanceld|cancelado|annullato|entfällt|fällt aus)\b", re.I), "status", "cancelled"),
    (re.compile(r"\b(verschoben|postponed|reporté|reporte|uitgesteld|rinviato|aplazado)\b", re.I), "status", "postponed"),
    (re.compile(r"\b(neuer termin|new date|nouvelle date|nieuwe datum|rescheduled|ersatztermin|nachholtermin)\b", re.I), "status", "rescheduled"),
    (re.compile(r"\b(ausverkauft|sold[\s-]?out|complet|uitverkocht|esaurito|agotado|restlos ausverkauft)\b", re.I), "ticket", "sold_out"),
    (re.compile(r"\b(wenige tickets|restkarten|few tickets|low tickets|limited tickets|dernières places|laatste kaarten|nur noch wenige)\b", re.I), "ticket", "limited"),
    (re.compile(r"\b(eintritt frei|free entry|free admission|entrée libre|gratis|freier eintritt)\b", re.I), "ticket", "free"),
    (re.compile(r"\b(abendkasse|box office only|tickets an der abendkasse)\b", re.I), "ticket", "box_office"),
    (re.compile(r"\b(presale|vorverkauf startet|vvk startet|on sale soon|bientôt en vente|coming soon)\b", re.I), "ticket", "not_on_sale"),
]


def ticket_provider_for(url: str | None) -> tuple[str | None, bool]:
    domain = url_domain(url)
    if not domain:
        return None, False
    for suffix, (label, resale) in TICKET_DOMAINS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return label, resale
    return None, False


def detect_statuses(text: str) -> tuple[str | None, str | None]:
    """Return ``(event_status, ticket_status)`` mentioned in ``text``."""
    status = ticket = None
    for pattern, kind, value in STATUS_PATTERNS:
        if pattern.search(text):
            if kind == "status" and status is None:
                status = value
            elif kind == "ticket" and ticket is None:
                ticket = value
    return status, ticket


_TICKET_STATUS_ALIASES = {
    "available": "available", "onsale": "available", "on_sale": "available", "on sale": "available", "instock": "available",
    "buy": "available", "tickets": "available", "limited": "limited", "few_left": "limited", "low": "limited",
    "sold_out": "sold_out", "soldout": "sold_out", "sold out": "sold_out", "offsale": "sold_out",
    "not_on_sale": "not_on_sale", "notonsale": "not_on_sale", "presale": "presale", "free": "free",
    "box_office": "box_office", "cancelled": "cancelled", "canceled": "cancelled",
}


def normalize_ticket_status(value: str | None) -> str:
    if not value:
        return "unknown"
    return _TICKET_STATUS_ALIASES.get(value.strip().casefold(), "unknown")


def normalize_event_status(value: str | None) -> str:
    if not value:
        return "scheduled"
    v = value.strip().casefold()
    if "cancel" in v or v in ("abgesagt", "annulé"):
        return "cancelled"
    if "postpon" in v or v == "verschoben":
        return "postponed"
    if "reschedul" in v:
        return "rescheduled"
    return "scheduled"
