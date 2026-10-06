// Crawler monitoring: workers/scheduler, queue, runs with logs, jobs, domains, errors.
import { useEffect, useState } from "react";
import { Ban, Globe, ListChecks, Play, RotateCw, Wrench, X } from "lucide-react";
import { api } from "../../api/client";
import { useAdminErrors, useAdminJobs, useAdminRuns } from "../../api/hooks";
import { JobStatusBadge, RunStatusBadge, StatusDot } from "../../components/badges";
import { Dialog } from "../../components/Dialog";
import { Badge, Button, Card, EmptyState, ErrorView, IconButton, KeyValue, Loading, Pagination, Segmented, Select, Tabs } from "../../components/ui";
import { ERROR_TYPE_LABELS, JOB_TYPE_LABELS, TRIGGER_LABELS, fmtDateTime, fmtDuration, fmtNumber, fmtRelative } from "../../lib/format";
import { safeHref } from "../../lib/urls";
import { confirmDialog } from "../../state/ui";
import type { AdminNav } from "./AdminApp";
import { useAdminAction, useAdminCrawlerStatus, useAdminDomains, useAdminRun } from "./hooks";
import { RunsTable } from "./Overview";

function RunDialog({ runId, onClose }: { runId: number | null; onClose(): void }) {
  const { data, isLoading, error } = useAdminRun(runId);
  return (
    <Dialog open={runId !== null} title={data ? `Crawler-Lauf #${data.id} – ${data.artist_name ?? data.label ?? ""}` : "Crawler-Lauf"} onClose={onClose} size="lg">
      {isLoading && <Loading />}
      {error && <ErrorView error={error} />}
      {data && (
        <div className="stack">
          <KeyValue
            items={[
              ["Status", <RunStatusBadge key="s" status={data.status} />],
              ["Auslöser", TRIGGER_LABELS[data.trigger] ?? data.trigger],
              ["Start", fmtDateTime(data.started_at)],
              ["Dauer", fmtDuration(data.duration_ms)],
              ["Quellen", `${data.sources_ok} ok / ${data.sources_failed} fehlerhaft / ${data.sources_total} gesamt`],
              ["Events", `${data.events_found} gefunden · ${data.events_new} neu · ${data.events_updated} geändert · ${data.events_removed} entfernt`],
            ]}
          />
          {data.log && <pre className="log-block">{data.log}</pre>}
          {data.errors && data.errors.length > 0 && (
            <Card title={`Fehler (${data.errors.length})`} padded={false}>
              <ErrorTable items={data.errors} />
            </Card>
          )}
        </div>
      )}
    </Dialog>
  );
}

function ErrorTable({ items }: { items: import("../../api/types").CrawlerError[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Zeit</th>
            <th>Typ</th>
            <th>Künstler / Domain</th>
            <th>Meldung</th>
            <th>Nächster Versuch</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => {
            const href = safeHref(e.url);
            return (
              <tr key={e.id}>
                <td title={fmtDateTime(e.occurred_at)}>{fmtRelative(e.occurred_at)}</td>
                <td>
                  <Badge tone="danger">
                    {ERROR_TYPE_LABELS[e.error_type] ?? e.error_type}
                    {e.status_code ? ` ${e.status_code}` : ""}
                  </Badge>
                </td>
                <td>
                  <strong>{e.artist_name ?? "–"}</strong>
                  <div className="muted small">
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                        {e.domain}
                      </a>
                    ) : (
                      e.domain
                    )}
                  </div>
                </td>
                <td className="wrap">{e.message}</td>
                <td>{e.retry_at ? fmtRelative(e.retry_at) : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type CrawlerTab = "runs" | "jobs" | "domains";

export function CrawlerSection({ nav }: { nav: AdminNav }) {
  const status = useAdminCrawlerStatus();
  const [tab, setTab] = useState<CrawlerTab>("runs");
  const [runFilter, setRunFilter] = useState("");
  const [jobFilter, setJobFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [runId, setRunId] = useState<number | null>((nav.params.runId as number) ?? null);
  const runs = useAdminRuns({ status: runFilter || undefined, offset, limit: 50 });
  const jobs = useAdminJobs({ status: jobFilter || undefined, limit: 100 });
  const domains = useAdminDomains(tab === "domains");
  useEffect(() => {
    if (nav.params.runId) setRunId(Number(nav.params.runId));
  }, [nav.params.runId]);

  const createJob = useAdminAction((job_type: string) => api.post<{ created: number }>("/api/admin/crawler/jobs", { job_type }), (r) => `${r.created} Job(s) eingeplant`);
  const cancel = useAdminAction((id: number) => api.del(`/api/admin/crawler/jobs/${id}`), "Job abgebrochen");

  const s = status.data;
  const queued = s?.queue.filter((q) => q.status === "queued").reduce((n, q) => n + q.count, 0) ?? 0;
  const running = s?.running.length ?? 0;

  return (
    <div className="stack">
      {status.error && <ErrorView error={status.error} />}
      {s && (
        <Card
          title="Status"
          subtitle={s.settings.enabled ? `Automatischer Crawl alle ${s.settings.interval_minutes} Minuten · nächster fälliger Künstler ${fmtRelative(s.next_due)}` : "Automatischer Crawl ist deaktiviert"}
          actions={
            <div className="button-row">
              <Button size="sm" variant="accent" icon={<Play size={14} />} loading={createJob.isPending} onClick={() => createJob.mutate("all_artists")}>
                Alle Künstler crawlen
              </Button>
              <Button size="sm" icon={<Globe size={14} />} onClick={() => createJob.mutate("all_sources")}>
                Alle Venue-/Festivalquellen
              </Button>
              <Button size="sm" icon={<Wrench size={14} />} onClick={() => createJob.mutate("maintenance")}>
                Wartung
              </Button>
            </div>
          }
        >
          <div className="stat-row">
            <span className="stat-inline">
              <strong>{running}</strong> laufend
            </span>
            <span className="stat-inline">
              <strong>{queued}</strong> wartend
            </span>
            {Object.entries(s.runs_24h).map(([k, v]) => (
              <span key={k} className="stat-inline">
                <RunStatusBadge status={k} /> <strong>{fmtNumber(v)}</strong> <span className="muted">in 24 h</span>
              </span>
            ))}
          </div>
          <div className="heartbeats">
            {s.heartbeats.length === 0 && <span className="muted">Kein Worker oder Scheduler aktiv. Starte die Dienste „tourdesk worker“ und „tourdesk scheduler“.</span>}
            {s.heartbeats.map((h) => (
              <span key={h.component} className="heartbeat">
                <StatusDot tone={h.alive ? "ok" : "error"} /> <strong>{h.kind}</strong> <span className="muted">{h.component}</span> · {h.alive ? `aktiv, ${fmtRelative(h.last_seen_at)}` : `seit ${fmtRelative(h.last_seen_at)} still`}
                {typeof h.info?.threads === "number" && <span className="muted"> · {String(h.info.threads)} Threads</span>}
              </span>
            ))}
          </div>
          {s.running.length > 0 && (
            <ul className="compact-list">
              {s.running.map((j) => (
                <li key={j.id}>
                  <JobStatusBadge status={j.status} />
                  <span className="compact-main">
                    <strong>{j.artist_name ?? `${JOB_TYPE_LABELS[j.job_type] ?? j.job_type}${j.source_id ? ` #${j.source_id}` : ""}`}</strong>
                    <span className="muted">
                      {JOB_TYPE_LABELS[j.job_type] ?? j.job_type} · seit {fmtRelative(j.started_at)} · {j.worker_id}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Tabs<CrawlerTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "runs", label: "Läufe", icon: <RotateCw size={15} />, count: runs.data?.total ?? null },
          { id: "jobs", label: "Jobs", icon: <ListChecks size={15} /> },
          { id: "domains", label: "Domains", icon: <Globe size={15} /> },
        ]}
      />

      {tab === "runs" && (
        <Card padded={false}>
          <div className="card-toolbar">
            <Segmented
              value={runFilter}
              onChange={(v) => {
                setRunFilter(v);
                setOffset(0);
              }}
              options={[
                { value: "", label: "Alle" },
                { value: "success", label: "Erfolgreich" },
                { value: "partial", label: "Teilweise" },
                { value: "failed", label: "Fehlgeschlagen" },
                { value: "running", label: "Laufend" },
              ]}
            />
          </div>
          {runs.isLoading && <Loading />}
          {runs.data && <RunsTable runs={runs.data.items} onOpen={setRunId} />}
          {runs.data && <Pagination offset={offset} limit={50} total={runs.data.total} onChange={setOffset} />}
        </Card>
      )}

      {tab === "jobs" && (
        <Card padded={false}>
          <div className="card-toolbar">
            <Select
              aria-label="Status"
              value={jobFilter}
              onChange={setJobFilter}
              options={[
                { value: "", label: "Alle Status" },
                { value: "queued", label: "Wartend" },
                { value: "running", label: "Laufend" },
                { value: "succeeded", label: "Erfolgreich" },
                { value: "partial", label: "Teilweise" },
                { value: "failed", label: "Fehlgeschlagen" },
                { value: "cancelled", label: "Abgebrochen" },
              ]}
            />
          </div>
          {jobs.isLoading && <Loading />}
          {jobs.data && !jobs.data.items.length && <EmptyState compact title="Keine Jobs" />}
          {jobs.data && jobs.data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Typ</th>
                    <th>Ziel</th>
                    <th>Status</th>
                    <th>Grund</th>
                    <th className="num">Versuche</th>
                    <th>Erstellt</th>
                    <th>Fällig</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {jobs.data.items.map((j) => (
                    <tr key={j.id}>
                      <td className="muted">{j.id}</td>
                      <td>{JOB_TYPE_LABELS[j.job_type] ?? j.job_type}</td>
                      <td>{j.artist_name ?? (j.source_id ? `Quelle #${j.source_id}` : "–")}</td>
                      <td>
                        <JobStatusBadge status={j.status} />
                        {j.error && <div className="muted small wrap">{j.error}</div>}
                      </td>
                      <td>{TRIGGER_LABELS[j.reason] ?? j.reason}</td>
                      <td className="num">
                        {j.attempts}/{j.max_attempts}
                      </td>
                      <td>{fmtRelative(j.created_at)}</td>
                      <td>{j.status === "queued" ? fmtRelative(j.run_after) : "–"}</td>
                      <td>
                        {j.status === "queued" && (
                          <IconButton
                            size="sm"
                            label="Abbrechen"
                            icon={<X size={14} />}
                            onClick={async () => {
                              if (await confirmDialog({ title: `Job #${j.id} abbrechen?`, confirmLabel: "Abbrechen", cancelLabel: "Zurück", danger: true })) cancel.mutate(j.id);
                            }}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === "domains" && (
        <Card padded={false} subtitle="Pro Domain wird höchstens eine Anfrage gleichzeitig gestellt; robots.txt und Crawl-Delay werden beachtet.">
          {domains.isLoading && <Loading />}
          {domains.data && !domains.data.length && <EmptyState compact title="Noch keine Domains abgefragt" />}
          {domains.data && domains.data.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Letzte Anfrage</th>
                    <th className="num">Anfragen</th>
                    <th className="num">Fehler</th>
                    <th>robots.txt</th>
                    <th>Crawl-Delay</th>
                    <th>Gesperrt bis</th>
                  </tr>
                </thead>
                <tbody>
                  {domains.data.map((d) => (
                    <tr key={d.domain}>
                      <td>
                        <strong>{d.domain}</strong>
                        {d.last_error && <div className="muted small wrap">{d.last_error}</div>}
                      </td>
                      <td>{fmtRelative(d.last_request_at)}</td>
                      <td className="num">{fmtNumber(d.request_count)}</td>
                      <td className="num">{d.error_count ? <Badge tone="danger">{d.error_count}</Badge> : "0"}</td>
                      <td>{d.robots_status ?? "–"}</td>
                      <td>{d.crawl_delay_s ? `${d.crawl_delay_s} s` : "–"}</td>
                      <td>{d.blocked_until && new Date(d.blocked_until) > new Date() ? <Badge tone="warning">{fmtRelative(d.blocked_until)}</Badge> : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      <RunDialog runId={runId} onClose={() => setRunId(null)} />
    </div>
  );
}

export function ErrorsSection({ nav }: { nav: AdminNav }) {
  const [hours, setHours] = useState("168");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error, refetch } = useAdminErrors({ since_hours: Number(hours), error_type: type || undefined, offset, limit: 100 });
  return (
    <div className="stack">
      <div className="toolbar">
        <Select
          aria-label="Zeitraum"
          value={hours}
          onChange={(v) => {
            setHours(v);
            setOffset(0);
          }}
          options={[
            { value: "24", label: "Letzte 24 Stunden" },
            { value: "168", label: "Letzte 7 Tage" },
            { value: "720", label: "Letzte 30 Tage" },
          ]}
        />
        {data && Object.keys(data.by_type).length > 0 && (
          <div className="chip-row">
            <button type="button" className={`chip chip-button${type === "" ? " is-selected" : ""}`} onClick={() => setType("")}>
              Alle ({Object.values(data.by_type).reduce((a, b) => a + b, 0)})
            </button>
            {Object.entries(data.by_type).map(([k, v]) => (
              <button
                key={k}
                type="button"
                className={`chip chip-button${type === k ? " is-selected" : ""}`}
                onClick={() => {
                  setType(k);
                  setOffset(0);
                }}
              >
                {ERROR_TYPE_LABELS[k] ?? k} ({v})
              </button>
            ))}
          </div>
        )}
        <Button size="sm" variant="subtle" icon={<Ban size={14} />} onClick={() => nav.go("sources", { status: "error" })}>
          Fehlerhafte Quellen
        </Button>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <Card padded={false}>
          {!data.items.length ? <EmptyState compact title="Keine Fehler im gewählten Zeitraum 🎉" /> : <ErrorTable items={data.items} />}
          <Pagination offset={offset} limit={100} total={data.total} onChange={setOffset} />
        </Card>
      )}
    </div>
  );
}
