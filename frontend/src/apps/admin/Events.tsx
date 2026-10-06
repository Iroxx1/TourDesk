// Admin: all stored events with "why (not) shown for user X" explanations.
import { useState } from "react";
import { HelpCircle } from "lucide-react";
import { useAdminUsers } from "../../api/hooks";
import { ConfirmationBadge, EventStatusBadge, EventTypeBadge } from "../../components/badges";
import { Button, Card, EmptyState, ErrorView, Loading, Pagination, SearchBox, Select, Toggle, cx } from "../../components/ui";
import { eventHeadline, fmtDate, fmtRelative } from "../../lib/format";
import { openEvent } from "../../state/windows";
import type { AdminNav } from "./AdminApp";
import { useAdminEventsList } from "./hooks";

export function EventsSection({ nav }: { nav: AdminNav }) {
  const [q, setQ] = useState("");
  const [upcoming, setUpcoming] = useState(true);
  const [offset, setOffset] = useState(0);
  const [userId, setUserId] = useState<string>(nav.params.userId ? String(nav.params.userId) : "");
  const users = useAdminUsers();
  const { data, isLoading, error, refetch } = useAdminEventsList({ q: q.trim(), upcoming, offset, limit: 50, artist_id: nav.params.artistId ?? undefined });

  return (
    <div className="stack">
      <div className="toolbar">
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Künstler, Veranstaltungsort oder Stadt" className="toolbar-grow" />
        <Toggle label="Nur kommende" checked={upcoming} onChange={(v) => { setUpcoming(v); setOffset(0); }} showState={false} />
        <Select
          aria-label="Erklärung für Benutzer"
          value={userId}
          onChange={setUserId}
          options={[{ value: "", label: "Erklärung für Benutzer …" }, ...(users.data ?? []).map((u) => ({ value: String(u.id), label: u.username }))]}
        />
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <Card padded={false}>
          {!data.items.length && <EmptyState compact title="Keine Events gefunden" />}
          {data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table table-hover">
                <thead>
                  <tr>
                    <th>Datum</th>
                    <th>Künstler</th>
                    <th>Ort</th>
                    <th>Art / Status</th>
                    <th>Quellen</th>
                    <th>Zuletzt gesehen</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.id} className={cx("is-clickable", !e.is_listed && "is-dim")} onClick={() => openEvent(e.id, { admin: true, adminUserId: userId ? Number(userId) : null, title: `${e.artist_name} – ${eventHeadline(e)}` })}>
                      <td>{fmtDate(e.date)}</td>
                      <td>
                        <strong>{e.artist_name}</strong>
                      </td>
                      <td>
                        {eventHeadline(e)}
                        <div className="muted small">{[e.city_name, e.region?.name, e.country?.code].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td>
                        <span className="badge-stack">
                          <EventTypeBadge type={e.event_type} />
                          <EventStatusBadge status={e.status} />
                          {!e.is_listed && <span className="muted small">nicht mehr gelistet</span>}
                        </span>
                      </td>
                      <td>
                        <ConfirmationBadge event={e} /> <span className="muted small">{e.source_count}</span>
                      </td>
                      <td>{fmtRelative(e.last_seen_at)}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="subtle"
                          icon={<HelpCircle size={14} />}
                          disabled={!userId}
                          title={userId ? "Warum wird dieses Event (nicht) angezeigt?" : "Zuerst oben einen Benutzer wählen"}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            openEvent(e.id, { admin: true, adminUserId: Number(userId), title: `${e.artist_name} – ${eventHeadline(e)}` });
                          }}
                        >
                          Warum?
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination offset={offset} limit={50} total={data.total} onChange={setOffset} />
        </Card>
      )}
    </div>
  );
}
