// Admin source management: status of every source, check (dry run), crawl, reset, enable, trust level.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, FlaskConical, Play, Plus, Power, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import type { NamedRef, Source } from "../../api/types";
import { useAdminSources, useVenues } from "../../api/hooks";
import { JobStatusBadge, SourceStatusBadge } from "../../components/badges";
import { Dialog } from "../../components/Dialog";
import { Badge, Button, Card, EmptyState, ErrorView, IconButton, KeyValue, Loading, Pagination, SearchBox, Select, Spinner, TextField, cx } from "../../components/ui";
import { ERROR_TYPE_LABELS, SCOPE_LABELS, fmtDateTime, fmtDuration, fmtRelative } from "../../lib/format";
import { hostOf, safeHref } from "../../lib/urls";
import { confirmDialog } from "../../state/ui";
import type { AdminNav } from "./AdminApp";
import { useAdminAction, useAdminCatalog, useAdminJob } from "./hooks";

const TRUST_OPTIONS = [
  { value: "1", label: "1 – Offizielle Künstlerwebsite" },
  { value: "2", label: "2 – Offizieller Veranstaltungsort" },
  { value: "3", label: "3 – Veranstalter / Festival" },
  { value: "4", label: "4 – Offizieller Ticketanbieter" },
  { value: "5", label: "5 – Ticketbörse / Plattform" },
  { value: "6", label: "6 – Sonstige Quelle" },
];

function CheckDialog({ jobId, source, onClose }: { jobId: number | null; source: Source | null; onClose(): void }) {
  const { data } = useAdminJob(jobId);
  const result = data?.result as Record<string, unknown> | null | undefined;
  const events = (result?.events as Record<string, unknown>[] | undefined) ?? [];
  const warnings = (result?.warnings as string[] | undefined) ?? [];
  const lineup = (result?.lineup_sample as string[] | undefined) ?? [];
  const matched = (result?.matched_artists as string[] | undefined) ?? [];
  const busy = !data || ["queued", "running"].includes(data.status);
  return (
    <Dialog open={jobId !== null} title={`Quelle prüfen: ${source?.name ?? ""}`} onClose={onClose} size="lg">
      {busy && (
        <div className="check-busy">
          <Spinner label={data?.status === "running" ? "Seite wird abgerufen und ausgewertet …" : "Wartet auf einen freien Worker …"} />
          <p className="muted small">Die Prüfung ist ein Probelauf: Es werden keine Termine gespeichert.</p>
        </div>
      )}
      {data && !busy && (
        <div className="stack">
          <div className="button-row">
            <JobStatusBadge status={data.status} />
            {result?.ok === false && <Badge tone="danger">{String(result.error ?? data.error ?? "Fehler")}</Badge>}
          </div>
          {result && result.ok !== false && (
            <KeyValue
              items={[
                ["Methode", String(result.method ?? "–")],
                ["Seiten", String(result.pages ?? "–")],
                ["HTTP-Status", String(result.http_status ?? "–")],
                ["Dauer", fmtDuration(Number(result.duration_ms ?? 0))],
                ["Gefundene Termine", String(result.events_total ?? 0)],
                ["Line-up-Einträge", String(result.lineup_count ?? 0)],
              ]}
            />
          )}
          {warnings.length > 0 && (
            <ul className="warning-list">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          {matched.length > 0 && (
            <p>
              <strong>Erkannte überwachte Künstler:</strong> {matched.join(", ")}
            </p>
          )}
          {events.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Datum</th>
                    <th>Titel</th>
                    <th>Ort</th>
                    <th>Status</th>
                    <th>Methode</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={i}>
                      <td>{String(e.date ?? "")}</td>
                      <td>{String(e.title ?? e.artist ?? "")}</td>
                      <td>{[e.venue, e.city, e.country].filter(Boolean).join(", ")}</td>
                      <td>{String(e.status ?? "")}</td>
                      <td className="muted">{String(e.method ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {lineup.length > 0 && <p className="muted small">Line-up (Auszug): {lineup.join(", ")}</p>}
        </div>
      )}
    </Dialog>
  );
}

function CreateSourceDialog({ open, onClose, providers }: { open: boolean; onClose(): void; providers: Record<string, string> }) {
  const [scope, setScope] = useState("venue");
  const [provider, setProvider] = useState("venue_website");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [trust, setTrust] = useState("2");
  const [targetQ, setTargetQ] = useState("");
  const [target, setTarget] = useState<NamedRef | null>(null);
  const artists = useAdminCatalog({ q: targetQ, limit: 10 });
  const venues = useVenues({ q: targetQ, limit: 10 }, scope === "venue" && targetQ.length >= 2);
  const festivals = useQuery({
    queryKey: ["festivals", targetQ],
    queryFn: () => api.get<NamedRef[]>("/api/festivals", { q: targetQ }),
    enabled: scope === "festival" && targetQ.length >= 2,
  });
  const create = useAdminAction(
    () =>
      api.post("/api/admin/sources", {
        scope,
        provider,
        name: name.trim(),
        url: url.trim() || null,
        trust_level: Number(trust),
        artist_id: scope === "artist" ? target?.id : null,
        venue_id: scope === "venue" ? target?.id : null,
        festival_id: scope === "festival" ? target?.id : null,
      }),
    "Quelle angelegt",
  );
  const options: NamedRef[] =
    scope === "artist" ? (artists.data?.items ?? []).map((a) => ({ id: a.id, name: a.name })) : scope === "venue" ? (venues.data ?? []).map((v) => ({ id: v.id, name: `${v.name} (${v.city_name ?? ""})` })) : festivals.data ?? [];

  useEffect(() => {
    setTarget(null);
    setTargetQ("");
  }, [scope]);

  return (
    <Dialog
      open={open}
      title="Quelle hinzufügen"
      onClose={onClose}
      footer={
        <>
          <Button
            variant="accent"
            loading={create.isPending}
            disabled={!name.trim() || (scope !== "global" && !target)}
            onClick={() => create.mutate(undefined, { onSuccess: onClose })}
          >
            Anlegen
          </Button>
          <Button onClick={onClose}>Abbrechen</Button>
        </>
      }
    >
      <div className="form-grid">
        <Select
          label="Bereich"
          value={scope}
          onChange={setScope}
          options={Object.entries(SCOPE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Select label="Provider" value={provider} onChange={setProvider} options={Object.entries(providers).map(([value, label]) => ({ value, label }))} />
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required className="span-2" />
        <TextField label="URL" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" className="span-2" />
        <Select label="Vertrauensstufe" value={trust} onChange={setTrust} options={TRUST_OPTIONS} className="span-2" />
        {scope !== "global" && (
          <div className="span-2 stack-sm">
            <SearchBox value={targetQ} onChange={setTargetQ} placeholder={`${SCOPE_LABELS[scope]} suchen`} />
            {target ? (
              <div className="selected-target">
                <CheckCircle2 size={16} /> {target.name}
                <Button size="sm" variant="subtle" onClick={() => setTarget(null)}>
                  Ändern
                </Button>
              </div>
            ) : (
              <div className="option-list">
                {options.slice(0, 10).map((o) => (
                  <button key={o.id} type="button" className="option-item" onClick={() => setTarget(o)}>
                    {o.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}

function SourceRow({ s, onCheck }: { s: Source; onCheck(s: Source): void }) {
  const href = safeHref(s.url);
  const run = useAdminAction(() => api.post(`/api/admin/sources/${s.id}/run`), "Crawl eingeplant");
  const reset = useAdminAction(() => api.post(`/api/admin/sources/${s.id}/reset`), "Fehlerzähler zurückgesetzt");
  const toggle = useAdminAction(() => api.patch(`/api/admin/sources/${s.id}`, { is_enabled: !s.is_enabled }), s.is_enabled ? "Quelle deaktiviert" : "Quelle aktiviert");
  const trust = useAdminAction((level: number) => api.patch(`/api/admin/sources/${s.id}`, { trust_level: level }), "Vertrauensstufe geändert");
  const remove = useAdminAction(() => api.del(`/api/admin/sources/${s.id}`), "Quelle gelöscht");
  const target = s.artist_name ?? s.venue_name ?? s.festival_name;
  return (
    <div className={cx("admin-source", !s.is_enabled && "is-dim", s.status === "error" && "is-error")}>
      <div className="admin-source-main">
        <div className="admin-source-title">
          <strong>{s.name}</strong>
          <SourceStatusBadge status={s.is_enabled ? s.status : "disabled"} />
          <Badge>{s.provider_label}</Badge>
          <Badge tone="neutral">{SCOPE_LABELS[s.scope]}{target ? `: ${target}` : ""}</Badge>
          {s.is_auto && <Badge tone="info">automatisch</Badge>}
        </div>
        {href && (
          <a className="admin-source-url" href={href} target="_blank" rel="noopener noreferrer nofollow">
            {s.url} <ExternalLink size={11} />
          </a>
        )}
        <div className="admin-source-meta muted small">
          <span>Zuletzt erfolgreich: {s.last_success_at ? fmtRelative(s.last_success_at) : "noch nie"}</span>
          <span>· Letzter Versuch: {fmtRelative(s.last_attempt_at)}</span>
          {s.last_event_count !== null && <span>· {s.last_event_count} Termine</span>}
          {s.last_http_status && <span>· HTTP {s.last_http_status}</span>}
          {s.last_duration_ms !== null && <span>· {fmtDuration(s.last_duration_ms)}</span>}
          {s.last_method && <span>· {s.last_method}</span>}
          <span>
            · {s.total_runs} Läufe, {s.total_failures} Fehler
          </span>
        </div>
        {s.last_error && s.status !== "ok" && (
          <div className="admin-source-error">
            <Badge tone="danger">{ERROR_TYPE_LABELS[s.last_error_type ?? ""] ?? s.last_error_type ?? "Fehler"}</Badge>
            <span>{s.last_error}</span>
            <span className="muted small">
              {s.consecutive_failures}× in Folge · zuletzt {fmtDateTime(s.last_error_at)} · nächster Versuch {s.next_attempt_at ? fmtRelative(s.next_attempt_at) : "beim nächsten Lauf"}
            </span>
          </div>
        )}
      </div>
      <div className="admin-source-actions">
        <Select aria-label="Vertrauensstufe" value={String(s.trust_level)} onChange={(v) => trust.mutate(Number(v))} options={TRUST_OPTIONS.map((o) => ({ value: o.value, label: `Stufe ${o.value}` }))} />
        <IconButton label="Prüfen (Probelauf)" icon={<FlaskConical size={16} />} onClick={() => onCheck(s)} />
        <IconButton label="Jetzt crawlen" icon={<Play size={16} />} disabled={!s.is_enabled || run.isPending} onClick={() => run.mutate()} />
        {s.consecutive_failures > 0 && <IconButton label="Fehler zurücksetzen" icon={<RotateCcw size={16} />} onClick={() => reset.mutate()} />}
        <IconButton label={s.is_enabled ? "Deaktivieren" : "Aktivieren"} icon={<Power size={16} />} active={s.is_enabled} onClick={() => toggle.mutate()} />
        <IconButton
          label="Löschen"
          icon={<Trash2 size={16} />}
          onClick={async () => {
            if (await confirmDialog({ title: "Quelle löschen?", message: `${s.name}${s.url ? ` (${hostOf(s.url)})` : ""}. Tipp: Deaktivieren behält die Historie.`, confirmLabel: "Löschen", danger: true }))
              remove.mutate();
          }}
        />
      </div>
    </div>
  );
}

export function SourcesSection({ nav }: { nav: AdminNav }) {
  const [scope, setScope] = useState("");
  const [status, setStatus] = useState((nav.params.status as string) ?? "");
  const [provider, setProvider] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [check, setCheck] = useState<{ job: number; source: Source } | null>(null);
  const { data, isLoading, error, refetch } = useAdminSources({ scope: scope || undefined, status: status || undefined, provider: provider || undefined, q: q.trim(), offset, limit: 50 });
  const startCheck = useAdminAction((s: Source) => api.post<{ job_id: number }>(`/api/admin/sources/${s.id}/check`));

  return (
    <div className="stack">
      <div className="toolbar">
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Name oder URL" className="toolbar-grow" />
        <Select aria-label="Bereich" value={scope} onChange={(v) => { setScope(v); setOffset(0); }} options={[{ value: "", label: "Alle Bereiche" }, ...Object.entries(SCOPE_LABELS).map(([value, label]) => ({ value, label }))]} />
        <Select
          aria-label="Status"
          value={status}
          onChange={(v) => { setStatus(v); setOffset(0); }}
          options={[
            { value: "", label: "Alle Status" },
            { value: "ok", label: "OK" },
            { value: "warning", label: "Warnung" },
            { value: "error", label: "Fehler" },
            { value: "new", label: "Neu" },
            { value: "disabled", label: "Deaktiviert" },
          ]}
        />
        <Select aria-label="Provider" value={provider} onChange={(v) => { setProvider(v); setOffset(0); }} options={[{ value: "", label: "Alle Provider" }, ...Object.entries(data?.providers ?? {}).map(([value, label]) => ({ value, label }))]} />
        <Button variant="accent" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
          Quelle
        </Button>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <Card padded={false}>
          {!data.items.length && <EmptyState compact title="Keine Quellen gefunden" />}
          {data.items.map((s) => (
            <SourceRow key={s.id} s={s} onCheck={(src) => startCheck.mutate(src, { onSuccess: (r) => setCheck({ job: r.job_id, source: src }) })} />
          ))}
          <Pagination offset={offset} limit={50} total={data.total} onChange={setOffset} />
        </Card>
      )}
      {creating && <CreateSourceDialog open onClose={() => setCreating(false)} providers={data?.providers ?? {}} />}
      <CheckDialog jobId={check?.job ?? null} source={check?.source ?? null} onClose={() => setCheck(null)} />
    </div>
  );
}
