// Event details: date, venue, tickets ("Tickets kaufen" → real external page), sources, explanation.
import { useEffect, useState } from "react";
import { CalendarPlus, ChevronDown, ChevronRight, Clock, ExternalLink, Globe2, MapPin, Mic2, ShieldCheck, Ticket } from "lucide-react";
import type { EventDetail } from "../api/types";
import { useAdminEvent, useAdminUsers, useEvent } from "../api/hooks";
import { ArtistImage } from "../components/ArtistImage";
import { ConfirmationBadge, EventStatusBadge, EventTypeBadge, TicketBadge } from "../components/badges";
import { canBuyTickets } from "../components/EventRow";
import { ExplanationView } from "../components/ExplanationView";
import { Badge, Card, ErrorView, KeyValue, LinkButton, Loading, Select, cx } from "../components/ui";
import {
  EVENT_STATUS_LABELS,
  EVENT_TYPE_LABELS,
  TICKET_STATUS_LABELS,
  eventHeadline,
  fmtCountdown,
  fmtDate,
  fmtDateTime,
  fmtLongDate,
  fmtRelative,
  fmtTime,
} from "../lib/format";
import { hostOf, safeHref } from "../lib/urls";
import { openArtist, useWindows } from "../state/windows";
import type { AppProps } from "./registry";

function priceLabel(min: number | null, max: number | null, currency: string | null): string | null {
  if (min === null && max === null) return null;
  const fmt = (n: number) => n.toLocaleString("de-DE", { style: "currency", currency: currency || "EUR" });
  if (min !== null && max !== null && max !== min) return `${fmt(min)} – ${fmt(max)}`;
  return fmt((min ?? max) as number);
}

function EventBody({ event, admin }: { event: EventDetail; admin: boolean }) {
  const [explainOpen, setExplainOpen] = useState(admin);
  const ticketHref = safeHref(event.ticket_url);
  const sourceHref = safeHref(event.primary_source_url);
  const start = fmtTime(event.start_time);
  const doors = fmtTime(event.doors_time);
  const buy = canBuyTickets(event);
  const activeTickets = event.tickets.filter((t) => t.is_active);
  const activeSources = event.sources.filter((s) => s.is_active);
  const artist = { name: event.artist_name, images: { thumb: event.artist_image, tile: event.artist_image, hero: event.artist_image, source: null, source_url: null } };

  return (
    <div className="event-app">
      <header className={cx("event-hero", event.event_type === "festival" && "is-festival", event.status === "cancelled" && "is-cancelled")}>
        <button type="button" className="event-hero-artist" onClick={() => openArtist(event.artist_id, event.artist_name)} title={`${event.artist_name} öffnen`}>
          <ArtistImage artist={artist} variant="thumb" className="event-hero-img" />
        </button>
        <div className="event-hero-text">
          <button type="button" className="event-hero-artistname" onClick={() => openArtist(event.artist_id, event.artist_name)}>
            <Mic2 size={14} /> {event.artist_name}
          </button>
          <h2 className="event-hero-title">{eventHeadline(event)}</h2>
          {event.title && event.title !== eventHeadline(event) && <div className="event-hero-sub">{event.title}</div>}
          <div className="event-hero-date">
            <strong>{fmtLongDate(event.date)}</strong>
            {event.end_date && event.end_date !== event.date && <span> – {fmtDate(event.end_date)}</span>}
            <span className="event-countdown">{fmtCountdown(event.date)}</span>
          </div>
          <div className="event-hero-badges">
            <EventTypeBadge type={event.event_type} />
            <EventStatusBadge status={event.status} />
            <TicketBadge status={event.ticket_status} />
            <ConfirmationBadge event={event} />
            {event.matches === false && <Badge tone="neutral">außerhalb deiner Filter</Badge>}
          </div>
        </div>
      </header>

      <div className="event-cta">
        {buy && ticketHref ? (
          <LinkButton href={ticketHref} variant="accent" size="lg" icon={<Ticket size={18} />}>
            Tickets kaufen
          </LinkButton>
        ) : ticketHref ? (
          <LinkButton href={ticketHref} size="lg" icon={<Ticket size={18} />}>
            {event.ticket_status === "sold_out" ? "Ausverkauft – Ticketseite öffnen" : "Ticketseite öffnen"}
          </LinkButton>
        ) : null}
        {sourceHref && (
          <LinkButton href={sourceHref} size="lg" icon={<ExternalLink size={18} />}>
            Originalquelle
          </LinkButton>
        )}
        <LinkButton href={`/api/events/${event.id}/ical`} external={false} size="lg" icon={<CalendarPlus size={18} />} download>
          In Kalender
        </LinkButton>
      </div>
      {event.ticket_url && !buy && event.status === "cancelled" && <p className="muted small">Der Termin wurde abgesagt – bitte die Hinweise des Veranstalters zur Erstattung beachten.</p>}

      <div className="event-grid">
        <Card title="Details" icon={<Clock size={16} />}>
          <KeyValue
            items={[
              ["Künstler", event.artist_name],
              ["Datum", fmtDate(event.date) + (event.end_date && event.end_date !== event.date ? ` – ${fmtDate(event.end_date)}` : "")],
              ["Beginn", start ? `${start} Uhr` : "noch nicht bekannt"],
              ...(doors ? ([["Einlass", `${doors} Uhr`]] as [string, string][]) : []),
              ["Art", EVENT_TYPE_LABELS[event.event_type]],
              ["Status", EVENT_STATUS_LABELS[event.status]],
              ["Tour", event.tour?.name ?? "–"],
              ["Festival", event.festival ? `Ja – ${event.festival.name}` : "Nein"],
            ]}
          />
        </Card>
        <Card title="Ort" icon={<MapPin size={16} />}>
          <KeyValue
            items={[
              ["Veranstaltungsort", event.venue_name ?? "–"],
              ["Stadt", event.city_name ?? "–"],
              ["Region", event.region?.name ?? "–"],
              ["Land", event.country ? `${event.country.name} (${event.country.code})` : "–"],
              ...(event.timezone ? ([["Zeitzone", event.timezone]] as [string, string][]) : []),
            ]}
          />
        </Card>
        <Card title="Tickets" icon={<Ticket size={16} />}>
          <KeyValue
            items={[
              ["Ticketstatus", TICKET_STATUS_LABELS[event.ticket_status] ?? event.ticket_status],
              ["Ticketanbieter", event.ticket_provider ?? (ticketHref ? hostOf(ticketHref) : "–")],
              [
                "Ticketlink",
                ticketHref ? (
                  <a href={ticketHref} target="_blank" rel="noopener noreferrer nofollow">
                    {hostOf(ticketHref)} <ExternalLink size={12} />
                  </a>
                ) : (
                  "–"
                ),
              ],
              ...(event.onsale_at ? ([["Vorverkauf ab", fmtDateTime(event.onsale_at)]] as [string, string][]) : []),
            ]}
          />
          {activeTickets.length > 1 && (
            <ul className="ticket-list">
              {activeTickets.map((t) => {
                const href = safeHref(t.url);
                const price = priceLabel(t.price_min, t.price_max, t.currency);
                return (
                  <li key={t.url}>
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                        {t.provider || hostOf(href)}
                      </a>
                    ) : (
                      t.provider
                    )}
                    <span className="muted"> · {TICKET_STATUS_LABELS[t.status] ?? t.status}</span>
                    {price && <span className="muted"> · {price}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <Card
          title={activeSources.length >= 2 ? `${activeSources.length} Quellen bestätigen diesen Termin` : "Quelle"}
          icon={<ShieldCheck size={16} />}
          subtitle={`Zuletzt geprüft ${fmtRelative(event.last_checked_at ?? event.last_seen_at)} · zuerst gefunden ${fmtDate(event.first_seen_at.slice(0, 10))}`}
        >
          <ul className="source-list">
            {event.sources.map((s, i) => {
              const href = safeHref(s.url);
              return (
                <li key={`${s.source_name}-${i}`} className={cx(!s.is_active && "is-inactive")}>
                  <span className={cx("trust", `trust-${s.trust_level}`)} title={s.trust_label}>
                    {s.trust_level}
                  </span>
                  <span className="source-list-text">
                    <strong>{s.source_name}</strong>
                    <span className="muted">
                      {s.provider_label} · {s.trust_label}
                      {!s.is_active && " · nicht mehr gelistet"}
                    </span>
                  </span>
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="source-list-link" title="Originaleintrag öffnen">
                      <Globe2 size={14} /> {hostOf(href)}
                    </a>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      {event.explanation && (
        <section className={cx("explain-card", explainOpen && "is-open")}>
          <button type="button" className="explain-toggle" aria-expanded={explainOpen} onClick={() => setExplainOpen(!explainOpen)}>
            {explainOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            {event.explanation.title}
          </button>
          {explainOpen && <ExplanationView explanation={event.explanation} heading={false} />}
        </section>
      )}

      <footer className="event-footer muted small">
        Zuletzt aktualisiert {fmtDateTime(event.updated_at)} · Event-ID {event.id} · Vertrauensstufe {event.best_trust} · Konfidenz {Math.round(event.confidence * 100)} %
      </footer>
    </div>
  );
}

function AdminEventView({ eventId, initialUser }: { eventId: number; initialUser: number | null }) {
  const [userId, setUserId] = useState<number | null>(initialUser);
  const users = useAdminUsers();
  const { data, isLoading, error, refetch } = useAdminEvent(eventId, userId);
  return (
    <div className="stack">
      <div className="admin-event-bar">
        <Select
          label="Sichtbarkeit prüfen für Benutzer"
          value={userId ? String(userId) : ""}
          onChange={(v) => setUserId(v ? Number(v) : null)}
          options={[{ value: "", label: "– Benutzer wählen –" }, ...(users.data ?? []).map((u) => ({ value: String(u.id), label: `${u.username} (${u.email})` }))]}
        />
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <>
          <EventBody event={data} admin />
          {data.observations && data.observations.length > 0 && (
            <Card title={`Rohdaten der Quellen (${data.observations.length})`} subtitle="So wurde der Termin auf den einzelnen Seiten gefunden.">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Provider</th>
                      <th>Stufe</th>
                      <th>Titel</th>
                      <th>Ort</th>
                      <th>Datum (roh)</th>
                      <th>Zuletzt gesehen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.observations.map((o, i) => {
                      const row = o as Record<string, string | number | boolean | null>;
                      const href = safeHref(row.url as string | null);
                      return (
                        <tr key={i} className={cx(!row.is_active && "is-dim")}>
                          <td>{href ? <a href={href} target="_blank" rel="noopener noreferrer nofollow">{String(row.provider)}</a> : String(row.provider)}</td>
                          <td>{String(row.trust_level ?? "")}</td>
                          <td>{String(row.raw_title ?? "")}</td>
                          <td>{[row.raw_venue, row.raw_city].filter(Boolean).join(", ")}</td>
                          <td>{String(row.raw_date ?? "")}</td>
                          <td>{fmtRelative(row.last_seen_at as string)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

export function EventApp({ win }: AppProps) {
  const eventId = Number(win.params.eventId);
  const admin = Boolean(win.params.admin);
  if (admin) return <AdminEventView eventId={eventId} initialUser={win.params.adminUserId ? Number(win.params.adminUserId) : null} />;
  return <UserEventView eventId={eventId} winId={win.id} />;
}

function UserEventView({ eventId, winId }: { eventId: number; winId: string }) {
  const { data, isLoading, error, refetch } = useEvent(eventId);
  useEffect(() => {
    if (data) useWindows.getState().setMeta(winId, { title: `${data.artist_name} – ${eventHeadline(data)}`, icon: data.artist_image });
  }, [data, winId]);
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorView error={error} retry={refetch} />;
  return <EventBody event={data} admin={false} />;
}
