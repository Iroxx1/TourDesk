// Admin dashboard: counts, crawler state, recent runs, errors, problem sources, new events, new users.
import { Activity, CalendarPlus, Cpu, Link2, Mic2, Play, Users } from "lucide-react";
import type { CrawlerRun } from "../../api/types";
import { useAdminOverview } from "../../api/hooks";
import { RunStatusBadge, StatusDot } from "../../components/badges";
import { Badge, Button, Card, EmptyState, ErrorView, Loading, Stat } from "../../components/ui";
import { ERROR_TYPE_LABELS, eventHeadline, fmtDate, fmtDuration, fmtNumber, fmtRelative } from "../../lib/format";
import { openEvent } from "../../state/windows";
import type { AdminNav } from "./AdminApp";
import { useAdminAction } from "./hooks";
import { api } from "../../api/client";

export function RunsTable({ runs, onOpen }: { runs: CrawlerRun[]; onOpen(id: number): void }) {
  if (!runs.length) return <EmptyState compact title="Noch keine Crawler-Läufe" />;
  return (
    <div className="table-wrap">
      <table className="table table-hover">
        <thead>
          <tr>
            <th>Start</th>
            <th>Lauf</th>
            <th>Status</th>
            <th className="num">Quellen</th>
            <th className="num">Gefunden</th>
            <th className="num">Neu</th>
            <th className="num">Geändert</th>
            <th className="num">Entfernt</th>
            <th className="num">Fehler</th>
            <th className="num">Dauer</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} onClick={() => onOpen(r.id)} className="is-clickable">
              <td title={r.started_at}>{fmtRelative(r.started_at)}</td>
              <td>
                <strong>{r.artist_name ?? r.label ?? r.job_type}</strong>
              </td>
              <td>
                <RunStatusBadge status={r.status} />
              </td>
              <td className="num">
                {r.sources_ok}/{r.sources_total}
              </td>
              <td className="num">{r.events_found}</td>
              <td className="num">{r.events_new || "–"}</td>
              <td className="num">{r.events_updated || "–"}</td>
              <td className="num">{r.events_removed || "–"}</td>
              <td className="num">{r.errors_count ? <Badge tone="danger">{r.errors_count}</Badge> : "0"}</td>
              <td className="num">{fmtDuration(r.duration_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewSection({ nav }: { nav: AdminNav }) {
  const { data, isLoading, error, refetch } = useAdminOverview();
  const crawlAll = useAdminAction(() => api.post<{ created: number }>("/api/admin/crawler/jobs", { job_type: "all_artists" }), (r) => `${r.created} Crawl-Jobs eingeplant`);
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorView error={error} retry={refetch} />;
  const c = data.counts;
  const cs = data.crawler_status;
  return (
    <div className="stack admin-overview">
      <div className="stat-grid">
        <Stat label={`Benutzer (${fmtNumber(c.active_users)} aktiv)`} value={fmtNumber(c.users)} icon={<Users size={18} />} onClick={() => nav.go("users")} />
        <Stat label={`Künstler (${fmtNumber(c.artists)} im Katalog)`} value={fmtNumber(c.monitored_artists)} icon={<Mic2 size={18} />} onClick={() => nav.go("catalog")} />
        <Stat label={`Events (${fmtNumber(c.upcoming_events)} kommend)`} value={fmtNumber(c.events)} icon={<CalendarPlus size={18} />} onClick={() => nav.go("events")} />
        <Stat label={`Crawler-Jobs (${c.crawler_jobs_running} laufen)`} value={fmtNumber(c.crawler_jobs_queued + c.crawler_jobs_running)} icon={<Activity size={18} />} onClick={() => nav.go("crawler")} />
        <Stat label="Fehler letzte 24 h" value={fmtNumber(c.errors_24h)} tone={c.errors_24h ? "danger" : "success"} icon={<Cpu size={18} />} onClick={() => nav.go("errors")} />
        <Stat label={`Quellen aktiv · ${fmtNumber(c.new_events_24h)} neue Events (24 h)`} value={fmtNumber(c.sources)} icon={<Link2 size={18} />} onClick={() => nav.go("sources")} />
      </div>

      <Card
        title="Crawler"
        actions={
          <Button size="sm" icon={<Play size={14} />} loading={crawlAll.isPending} onClick={() => crawlAll.mutate()}>
            Alle Künstler jetzt crawlen
          </Button>
        }
      >
        <div className="crawler-health">
          <span className="health health-ok">
            <span aria-hidden>🟢</span> {fmtNumber(cs.ok)} erfolgreich
          </span>
          <span className="health health-partial">
            <span aria-hidden>🟡</span> {fmtNumber(cs.partial)} teilweise erfolgreich
          </span>
          <span className="health health-error">
            <span aria-hidden>🔴</span> {fmtNumber(cs.error)} Fehler
          </span>
          {cs.pending > 0 && (
            <span className="health health-pending">
              <span aria-hidden>⏳</span> {fmtNumber(cs.pending)} warten auf ersten Crawl
            </span>
          )}
          <span className="muted">· {fmtNumber(c.runs_24h)} Läufe in 24 h</span>
        </div>
        <div className="heartbeats">
          {data.heartbeats.length === 0 && <span className="muted">Kein Worker/Scheduler hat sich bisher gemeldet – läuft der Crawler-Dienst?</span>}
          {data.heartbeats.map((h) => (
            <span key={h.component} className="heartbeat" title={`Gestartet ${fmtRelative(h.started_at)}`}>
              <StatusDot tone={h.alive ? "ok" : "error"} /> {h.kind === "scheduler" ? "Scheduler" : h.kind === "worker" ? "Worker" : h.kind} <span className="muted">{h.component}</span> ·{" "}
              {h.alive ? `aktiv (${fmtRelative(h.last_seen_at)})` : `keine Rückmeldung seit ${fmtRelative(h.last_seen_at)}`}
            </span>
          ))}
        </div>
      </Card>

      <Card title="Letzte Crawler-Läufe" actions={<Button size="sm" variant="subtle" onClick={() => nav.go("crawler")}>Alle ›</Button>} padded={false}>
        <RunsTable runs={data.recent_runs} onOpen={(id) => nav.go("crawler", { runId: id })} />
      </Card>

      <div className="two-col">
        <Card title="Fehler" actions={<Button size="sm" variant="subtle" onClick={() => nav.go("errors")}>Alle ›</Button>}>
          {data.recent_errors.length === 0 && <EmptyState compact title="Keine Fehler" />}
          <ul className="compact-list">
            {data.recent_errors.map((e) => (
              <li key={e.id}>
                <Badge tone="danger">{ERROR_TYPE_LABELS[e.error_type] ?? e.error_type}</Badge>
                <span className="compact-main">
                  <strong>{e.artist_name ?? e.domain ?? "–"}</strong>
                  <span className="muted">{e.message}</span>
                </span>
                <span className="muted small">{fmtRelative(e.occurred_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Problematische Quellen" actions={<Button size="sm" variant="subtle" onClick={() => nav.go("sources", { status: "error" })}>Alle ›</Button>}>
          {data.problem_sources.length === 0 && <EmptyState compact title="Alle Quellen funktionieren" />}
          <ul className="compact-list">
            {data.problem_sources.map((s) => (
              <li key={s.id}>
                <Badge tone="danger">{s.consecutive_failures}×</Badge>
                <span className="compact-main">
                  <strong>{s.name}</strong>
                  <span className="muted">{s.last_error}</span>
                  <span className="muted small">
                    Zuletzt erfolgreich: {s.last_success_at ? fmtRelative(s.last_success_at) : "noch nie"} · Nächster Versuch: {s.next_attempt_at ? fmtRelative(s.next_attempt_at) : "–"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="two-col">
        <Card title="Neue Events (7 Tage)" actions={<Button size="sm" variant="subtle" onClick={() => nav.go("events")}>Alle ›</Button>}>
          {data.new_events.length === 0 && <EmptyState compact title="Keine neuen Events" />}
          <ul className="compact-list">
            {data.new_events.map((e) => (
              <li key={e.id} className="is-clickable" onClick={() => openEvent(e.id, { admin: true, title: `${e.artist_name} – ${eventHeadline(e)}` })}>
                <span className="compact-date">{fmtDate(e.date)}</span>
                <span className="compact-main">
                  <strong>{e.artist_name}</strong>
                  <span className="muted">
                    {eventHeadline(e)}
                    {e.city_name ? `, ${e.city_name}` : ""}
                  </span>
                </span>
                <span className="muted small">{fmtRelative(e.first_seen_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Kürzlich registrierte Benutzer" actions={<Button size="sm" variant="subtle" onClick={() => nav.go("users")}>Alle ›</Button>}>
          <ul className="compact-list">
            {data.recent_users.map((u) => (
              <li key={u.id} className="is-clickable" onClick={() => nav.go("users", { userId: u.id })}>
                <span className="compact-main">
                  <strong>{u.username}</strong>
                  <span className="muted">{u.email}</span>
                </span>
                {u.role === "admin" && <Badge tone="accent">Admin</Badge>}
                {!u.is_active && <Badge tone="neutral">deaktiviert</Badge>}
                <span className="muted small">{fmtRelative(u.created_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
