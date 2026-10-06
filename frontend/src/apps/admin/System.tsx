// Admin: system & database status, log viewer, audit log.
import { useState } from "react";
import { Database, HardDrive, RefreshCw, Server } from "lucide-react";
import { useAdminAudit } from "../../api/hooks";
import { StatusDot } from "../../components/badges";
import { Badge, Button, Card, EmptyState, ErrorView, KeyValue, Loading, Pagination, SearchBox, Segmented, Select, Stat, cx } from "../../components/ui";
import { fmtBytes, fmtDateTime, fmtNumber, fmtRelative } from "../../lib/format";
import { useAdminLogs, useAdminSystem } from "./hooks";

export function SystemSection() {
  const { data, isLoading, error, refetch, isFetching } = useAdminSystem();
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorView error={error} retry={refetch} />;
  const db = data.database as { ok?: boolean; server_version?: string; size_bytes?: number; connections?: number; migration_revision?: string; error?: string };
  const usedPct = data.disk.total ? Math.round((data.disk.used / data.disk.total) * 100) : 0;
  return (
    <div className="stack">
      <div className="stat-grid">
        {Object.entries(data.counts).map(([k, v]) => (
          <Stat key={k} label={{ users: "Benutzer", artists: "Künstler", events: "Events", sources: "Quellen", venues: "Veranstaltungsorte", cities: "Städte" }[k] ?? k} value={fmtNumber(v)} />
        ))}
      </div>
      <div className="two-col">
        <Card title="Datenbank" icon={<Database size={16} />} actions={<Button size="sm" variant="subtle" icon={<RefreshCw size={14} />} loading={isFetching} onClick={() => refetch()}>Aktualisieren</Button>}>
          <KeyValue
            items={[
              ["Status", db.ok ? <span key="ok"><StatusDot tone="ok" /> erreichbar</span> : <span key="err"><StatusDot tone="error" /> {db.error ?? "Fehler"}</span>],
              ["PostgreSQL", db.server_version ?? "–"],
              ["Größe", fmtBytes(db.size_bytes)],
              ["Verbindungen", String(db.connections ?? "–")],
              ["Migration", db.migration_revision ?? "–"],
            ]}
          />
        </Card>
        <Card title="Server" icon={<Server size={16} />}>
          <KeyValue
            items={[
              ["Version", data.version],
              ["Umgebung", data.env],
              ["Python", data.python],
              ["Plattform", data.platform],
              ["Öffentliche URL", data.public_url ?? "nicht gesetzt (lokal)"],
              ["Vertrauenswürdige Proxys", Array.isArray(data.trusted_proxies) ? data.trusted_proxies.join(", ") || "–" : String(data.trusted_proxies || "–")],
              ["Sichere Cookies", String(data.cookie_secure ?? "auto")],
              ["Frontend", data.frontend ?? "nicht gebaut"],
            ]}
          />
        </Card>
      </div>
      <div className="two-col">
        <Card title="Speicher" icon={<HardDrive size={16} />}>
          <div className="meter" role="meter" aria-valuenow={usedPct} aria-valuemin={0} aria-valuemax={100}>
            <span className={cx("meter-fill", usedPct > 90 && "is-danger", usedPct > 75 && usedPct <= 90 && "is-warning")} style={{ width: `${usedPct}%` }} />
          </div>
          <KeyValue
            items={[
              ["Belegt", `${fmtBytes(data.disk.used)} von ${fmtBytes(data.disk.total)} (${usedPct} %)`],
              ["Frei", fmtBytes(data.disk.free)],
              ["Bilder-Cache", fmtBytes(data.disk.media_bytes)],
            ]}
          />
        </Card>
        <Card title="Dienste">
          {data.heartbeats.length === 0 && <EmptyState compact title="Keine Worker/Scheduler aktiv" />}
          <ul className="compact-list">
            {data.heartbeats.map((h) => (
              <li key={h.component}>
                <StatusDot tone={h.alive ? "ok" : "error"} />
                <span className="compact-main">
                  <strong>{h.kind}</strong>
                  <span className="muted">
                    {h.component} · gestartet {fmtRelative(h.started_at)}
                  </span>
                </span>
                <span className="muted small">{fmtRelative(h.last_seen_at)}</span>
              </li>
            ))}
          </ul>
          <div className="log-files">
            {data.logs.map((l) => (
              <Badge key={l.name} tone={l.exists ? "neutral" : "warning"}>
                {l.name}.log · {l.exists ? fmtBytes(l.size) : "fehlt"}
              </Badge>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

const LOG_FILES = [
  { value: "crawler", label: "Crawler" },
  { value: "api", label: "API / Webserver" },
  { value: "worker", label: "Worker" },
  { value: "scheduler", label: "Scheduler" },
  { value: "cli", label: "CLI" },
];

export function LogsSection() {
  const [file, setFile] = useState("crawler");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const [lines, setLines] = useState("300");
  const { data, isLoading, error, refetch, isFetching } = useAdminLogs({ file, level: level || undefined, q: q.trim() || undefined, lines: Number(lines) });
  const entries = data?.entries ?? [];
  return (
    <div className="stack logs-section">
      <div className="toolbar">
        <Segmented value={file} onChange={setFile} options={LOG_FILES} />
        {file !== "crawler" && (
          <Select
            aria-label="Level"
            value={level}
            onChange={setLevel}
            options={[
              { value: "", label: "Alle Level" },
              { value: "INFO", label: "ab INFO" },
              { value: "WARNING", label: "ab WARNING" },
              { value: "ERROR", label: "nur Fehler" },
            ]}
          />
        )}
        <SearchBox value={q} onChange={setQ} placeholder="Text filtern (z. B. login, admin, Rockhal)" className="toolbar-grow" />
        <Select aria-label="Zeilen" value={lines} onChange={setLines} options={["100", "300", "1000", "2000"].map((v) => ({ value: v, label: `${v} Zeilen` }))} />
        <Button size="sm" variant="subtle" icon={<RefreshCw size={14} />} loading={isFetching} onClick={() => refetch()}>
          Neu laden
        </Button>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && !entries.length && <EmptyState compact title="Keine Einträge" text="Die Logdatei ist leer oder der Filter liefert keine Treffer. Logs werden unter <data>/logs geschrieben." />}
      {data && entries.length > 0 && file === "crawler" && (
        <pre className="log-block log-crawler">
          {entries
            .map((e) => String(e.msg ?? ""))
            .map((line, i) => (i > 0 && /^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$/.test(line) ? `\n${line}` : line))
            .join("\n")}
        </pre>
      )}
      {data && entries.length > 0 && file !== "crawler" && (
        <div className="log-table">
          {entries.map((e, i) => {
            const lvl = String(e.level ?? "INFO");
            const extra = Object.entries(e).filter(([k]) => !["ts", "level", "logger", "role", "msg"].includes(k));
            return (
              <div key={i} className={cx("log-line", `log-${lvl.toLowerCase()}`)}>
                <span className="log-ts">{e.ts ? fmtDateTime(String(e.ts)) : ""}</span>
                <span className="log-level">{lvl}</span>
                <span className="log-logger">{String(e.logger ?? "")}</span>
                <span className="log-msg">
                  {String(e.msg ?? "")}
                  {extra.length > 0 && (
                    <span className="log-extra">
                      {extra.map(([k, v]) => (
                        <span key={k}>
                          {k}={typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </span>
                      ))}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AuditSection() {
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error, refetch } = useAdminAudit({ action: action || undefined, q: q.trim() || undefined, offset, limit: 100 });
  return (
    <div className="stack">
      <div className="toolbar">
        <Select
          aria-label="Aktion"
          value={action}
          onChange={(v) => { setAction(v); setOffset(0); }}
          options={[
            { value: "", label: "Alle Aktionen" },
            { value: "auth.", label: "Anmeldungen" },
            { value: "admin.", label: "Admin-Aktionen" },
            { value: "user.", label: "Profiländerungen" },
            { value: "artist.", label: "Künstler" },
            { value: "source.", label: "Quellen" },
            { value: "venue.", label: "Veranstaltungsorte" },
            { value: "geo.", label: "Orte" },
          ]}
        />
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Benutzer oder Ziel" className="toolbar-grow" />
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <Card padded={false}>
          {!data.items.length && <EmptyState compact title="Keine Einträge" />}
          {data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Zeit</th>
                    <th>Aktion</th>
                    <th>Benutzer</th>
                    <th>Ziel</th>
                    <th>Details</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} className={cx(!a.success && "is-error")}>
                      <td title={a.created_at}>{fmtDateTime(a.created_at)}</td>
                      <td>
                        <code>{a.action}</code> {!a.success && <Badge tone="danger">fehlgeschlagen</Badge>}
                      </td>
                      <td>{a.actor ?? "–"}</td>
                      <td>{a.target ?? (a.target_type ? `${a.target_type} ${a.target_id ?? ""}` : "–")}</td>
                      <td className="wrap muted small">{a.details && Object.keys(a.details).length ? Object.entries(a.details).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ") : ""}</td>
                      <td className="muted">{a.ip ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination offset={offset} limit={100} total={data.total} onChange={setOffset} />
        </Card>
      )}
    </div>
  );
}
