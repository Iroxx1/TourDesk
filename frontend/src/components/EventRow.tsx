// Event list entries (tile + window variants).
import type { MouseEvent, ReactNode } from "react";
import { EyeOff, MapPin, Ticket } from "lucide-react";
import type { TourEvent } from "../api/types";
import { eventHeadline, eventSubline, fmtDate, fmtMonthShort, fmtMonthYear, fmtTime, fmtWeekdayShort, parseDay } from "../lib/format";
import { safeHref } from "../lib/urls";
import { openEvent } from "../state/windows";
import { ConfirmationBadge, EventStatusBadge, EventTypeBadge, TicketBadge } from "./badges";
import { cx } from "./ui";

export function canBuyTickets(e: Pick<TourEvent, "ticket_url" | "status" | "ticket_status">): boolean {
  return Boolean(safeHref(e.ticket_url)) && e.status !== "cancelled" && !["sold_out", "cancelled"].includes(e.ticket_status);
}

function DateBlock({ day, cancelled }: { day: string; cancelled?: boolean }) {
  const d = parseDay(day);
  const otherYear = d.getFullYear() !== new Date().getFullYear();
  return (
    <div className={cx("date-block", cancelled && "is-cancelled")} aria-hidden>
      <span className="date-block-wd">{fmtWeekdayShort(day)}</span>
      <span className="date-block-day">{d.getDate()}</span>
      <span className="date-block-mon">
        {fmtMonthShort(day)}
        {otherYear ? ` ${String(d.getFullYear()).slice(2)}` : ""}
      </span>
    </div>
  );
}

interface EventRowProps {
  event: TourEvent;
  showArtist?: boolean;
  showYear?: boolean;
  onOpen?: (e: TourEvent) => void;
  extra?: ReactNode;
}

export function EventRow({ event, showArtist, onOpen, extra }: EventRowProps) {
  const outside = event.matches === false;
  const cancelled = event.status === "cancelled";
  const ticketHref = canBuyTickets(event) ? safeHref(event.ticket_url) : undefined;
  const open = () => (onOpen ? onOpen(event) : openEvent(event.id, { title: `${event.artist_name} – ${eventHeadline(event)}` }));
  const stop = (e: MouseEvent) => e.stopPropagation();
  const time = fmtTime(event.start_time);
  return (
    <div
      className={cx("event-row", outside && "is-outside", cancelled && "is-cancelled", event.event_type === "festival" && "is-festival")}
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      title={outside && event.hidden_reason ? `Nicht in deinen Filtern: ${event.hidden_reason}` : undefined}
    >
      <DateBlock day={event.date} cancelled={cancelled} />
      <div className="event-row-main">
        <div className="event-row-title">
          {showArtist && <span className="event-row-artist">{event.artist_name}</span>}
          <span className="event-row-place">{eventHeadline(event)}</span>
        </div>
        <div className="event-row-sub" title={fmtDate(event.date)}>
          <MapPin size={12} aria-hidden />
          <span>{eventSubline(event) || event.city_name || "Ort unbekannt"}</span>
          {event.end_date && event.end_date !== event.date && <span className="event-row-date">bis {fmtDate(event.end_date)}</span>}
          {time && <span className="event-row-date">{time} Uhr</span>}
        </div>
        <div className="event-row-badges">
          <EventTypeBadge type={event.event_type} />
          <EventStatusBadge status={event.status} />
          <TicketBadge status={event.ticket_status} />
          {!event.is_confirmed && <ConfirmationBadge event={event} />}
          {outside && (
            <span className="outside-label">
              <EyeOff size={12} aria-hidden /> außerhalb deiner Filter
            </span>
          )}
          {extra}
        </div>
      </div>
      {ticketHref && (
        <a className="btn btn-default btn-sm event-row-ticket" href={ticketHref} target="_blank" rel="noopener noreferrer nofollow" onClick={stop}>
          <Ticket size={14} aria-hidden />
          <span className="btn-label">Tickets</span>
        </a>
      )}
    </div>
  );
}

/** Compact one-line entry used inside desktop tiles. */
export function EventLine({ event, onOpen }: { event: TourEvent; onOpen?: (e: TourEvent) => void }) {
  const outside = event.matches === false;
  const cancelled = event.status === "cancelled";
  const open = (ev: MouseEvent) => {
    ev.stopPropagation();
    if (onOpen) onOpen(event);
    else openEvent(event.id, { title: `${event.artist_name} – ${eventHeadline(event)}` });
  };
  return (
    <button
      type="button"
      className={cx("event-line", outside && "is-outside", cancelled && "is-cancelled", event.event_type === "festival" && "is-festival")}
      onClick={open}
      title={outside && event.hidden_reason ? `Nicht in deinen Filtern: ${event.hidden_reason}` : undefined}
    >
      <span className="event-line-date">{fmtDate(event.date)}</span>
      <span className="event-line-place">
        {eventHeadline(event)}
        {event.city_name && event.venue_name && event.event_type !== "festival" && <span className="event-line-city"> – {event.city_name}</span>}
      </span>
      <span className="event-line-flags">
        {event.event_type === "festival" && <span className="flag flag-festival">Festival</span>}
        {event.event_type === "support" && <span className="flag flag-support">Support</span>}
        {event.status === "cancelled" && <span className="flag flag-cancelled">Abgesagt</span>}
        {event.status === "postponed" && <span className="flag flag-postponed">Verschoben</span>}
        {event.country && <span className="flag flag-country">{event.country.code}</span>}
      </span>
    </button>
  );
}

/** Events grouped by month with sticky headers. */
export function EventList({ events, showArtist, empty, onOpen }: { events: TourEvent[]; showArtist?: boolean; empty?: ReactNode; onOpen?: (e: TourEvent) => void }) {
  if (!events.length) return <>{empty ?? null}</>;
  const groups: { key: string; label: string; items: TourEvent[] }[] = [];
  for (const e of events) {
    const key = e.date.slice(0, 7);
    let g = groups[groups.length - 1];
    if (!g || g.key !== key) {
      g = { key, label: fmtMonthYear(e.date), items: [] };
      groups.push(g);
    }
    g.items.push(e);
  }
  return (
    <div className="event-list">
      {groups.map((g) => (
        <section key={g.key} className="event-group">
          <h4 className="event-group-head">{g.label}</h4>
          {g.items.map((e) => (
            <EventRow key={e.id} event={e} showArtist={showArtist} onOpen={onOpen} />
          ))}
        </section>
      ))}
    </div>
  );
}
