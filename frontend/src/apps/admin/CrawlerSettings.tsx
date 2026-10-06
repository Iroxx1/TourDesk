// Admin: central crawler configuration (interval, politeness, providers, API keys).
import { useEffect, useMemo, useState } from "react";
import { KeyRound, Save, ShieldCheck, Timer, Wand2 } from "lucide-react";
import { api } from "../../api/client";
import { Badge, Button, Card, ChipInput, ErrorView, InfoBar, Loading, SettingRow, TextField, Toggle } from "../../components/ui";
import { useAdminAction, useAdminCrawlerSettings, type CrawlerSettings } from "./hooks";

const PROVIDER_NAMES: Record<string, string> = {
  official_website: "Offizielle Künstlerwebsites",
  tour_page: "Tourseiten",
  generic_web: "Sonstige Webseiten",
  ical_feed: "iCal-Feeds",
  ticketmaster: "Ticketmaster (API-Key nötig)",
  bandsintown: "Bandsintown (App-ID nötig)",
  songkick: "Songkick (API-Key nötig)",
  venue_website: "Programme der Veranstaltungsorte",
  festival_lineup: "Festival-Line-ups",
  promoter_website: "Veranstalter-Websites",
  ticket_listing: "Ticketseiten",
  demo: "Demo-Quelle (Beispielband)",
};

type NumKey =
  | "interval_minutes"
  | "min_domain_interval_s"
  | "timeout_s"
  | "max_retries"
  | "max_response_mb"
  | "cache_ttl_minutes"
  | "max_pages_per_source"
  | "worker_threads"
  | "enrich_interval_days"
  | "source_backoff_max_hours"
  | "keep_runs_days";

const NUMBERS: { key: NumKey; label: string; hint: string; min: number; max: number; step?: number }[] = [
  { key: "interval_minutes", label: "Crawl-Intervall (Minuten)", hint: "Standard 60 – ungefähr stündlich", min: 10, max: 1440 },
  { key: "min_domain_interval_s", label: "Mindestabstand je Domain (s)", hint: "Höflichkeitspause zwischen Anfragen an dieselbe Website", min: 1, max: 120, step: 0.5 },
  { key: "timeout_s", label: "Timeout (s)", hint: "Abbruch langsamer Anfragen", min: 3, max: 120 },
  { key: "max_retries", label: "Wiederholungen", hint: "Bei Netzwerkfehlern mit Backoff", min: 0, max: 5 },
  { key: "max_response_mb", label: "Max. Antwortgröße (MB)", hint: "Schutz vor riesigen Downloads", min: 1, max: 50 },
  { key: "cache_ttl_minutes", label: "HTTP-Cache (Minuten)", hint: "Unveränderte Seiten werden nicht erneut geladen", min: 0, max: 1440 },
  { key: "max_pages_per_source", label: "Seiten je Quelle", hint: "Max. Folgeseiten (Paginierung)", min: 1, max: 10 },
  { key: "worker_threads", label: "Worker-Threads", hint: "Wirksam nach Neustart des Workers", min: 1, max: 16 },
  { key: "enrich_interval_days", label: "Metadaten/Bilder auffrischen (Tage)", hint: "", min: 1, max: 365 },
  { key: "source_backoff_max_hours", label: "Max. Backoff fehlerhafter Quellen (h)", hint: "Fehlerhafte Quellen werden seltener, aber weiter versucht", min: 1, max: 168 },
  { key: "keep_runs_days", label: "Crawler-Läufe aufbewahren (Tage)", hint: "", min: 1, max: 365 },
];

export function CrawlerSettingsSection() {
  const { data, isLoading, error, refetch } = useAdminCrawlerSettings();
  const [draft, setDraft] = useState<CrawlerSettings | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  useEffect(() => {
    if (data) {
      setDraft(data);
      setKeys({});
    }
  }, [data]);
  const changes = useMemo(() => {
    if (!data || !draft) return {};
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(draft) as (keyof CrawlerSettings)[]) {
      if (k === "api_keys" || k === "api_keys_from_env") continue;
      if (JSON.stringify(draft[k]) !== JSON.stringify(data[k])) out[k] = draft[k];
    }
    const keyPatch = Object.fromEntries(Object.entries(keys).filter(([, v]) => v !== ""));
    if (Object.keys(keyPatch).length) out.api_keys = keyPatch;
    return out;
  }, [data, draft, keys]);
  const save = useAdminAction(() => api.put<CrawlerSettings>("/api/admin/crawler/settings", changes), "Crawler-Einstellungen gespeichert");

  if (isLoading || (!draft && !error)) return <Loading />;
  if (error || !draft) return <ErrorView error={error} retry={refetch} />;
  const set = <K extends keyof CrawlerSettings>(k: K, v: CrawlerSettings[K]) => setDraft({ ...draft, [k]: v });
  const dirty = Object.keys(changes).length > 0;

  return (
    <div className="stack">
      {dirty && (
        <InfoBar
          tone="warning"
          title="Ungespeicherte Änderungen"
          action={
            <Button size="sm" variant="accent" icon={<Save size={14} />} loading={save.isPending} onClick={() => save.mutate()}>
              Speichern
            </Button>
          }
        >
          {Object.keys(changes).join(", ")}
        </InfoBar>
      )}
      <Card title="Zeitplan" icon={<Timer size={16} />}>
        <SettingRow title="Automatischer Crawl" description="Scheduler plant die Künstler regelmäßig ein">
          <Toggle checked={draft.enabled} onChange={(v) => set("enabled", v)} />
        </SettingRow>
        <div className="form-grid">
          {NUMBERS.map((n) => (
            <TextField
              key={n.key}
              label={n.label}
              hint={n.hint || undefined}
              type="number"
              min={n.min}
              max={n.max}
              step={n.step ?? 1}
              value={String(draft[n.key])}
              onChange={(e) => {
                const value = Number(e.target.value);
                if (!Number.isNaN(value)) set(n.key, value);
              }}
            />
          ))}
        </div>
      </Card>
      <Card title="Höflichkeit & Sicherheit" icon={<ShieldCheck size={16} />}>
        <SettingRow title="robots.txt beachten" description="Empfohlen. Gesperrte Seiten werden nicht abgerufen.">
          <Toggle checked={draft.respect_robots} onChange={(v) => set("respect_robots", v)} />
        </SettingRow>
        <SettingRow title="Private Netzwerke erlauben" description="Nur für Tests – schützt sonst vor Zugriffen auf interne Adressen (SSRF)">
          <Toggle checked={draft.allow_private_networks} onChange={(v) => set("allow_private_networks", v)} />
        </SettingRow>
        <div className="form-grid">
          <TextField label="User-Agent" value={draft.user_agent} onChange={(e) => set("user_agent", e.target.value)} className="span-2" />
          <TextField label="Kontakt (E-Mail/URL im User-Agent)" value={draft.contact} onChange={(e) => set("contact", e.target.value)} hint="Website-Betreiber können so Kontakt aufnehmen." className="span-2" />
        </div>
      </Card>
      <Card title="Provider" subtitle="Einzelne Quelltypen global ein- oder ausschalten.">
        {Object.entries(draft.providers).map(([k, v]) => (
          <SettingRow key={k} title={PROVIDER_NAMES[k] ?? k}>
            <Toggle checked={v} onChange={(on) => set("providers", { ...draft.providers, [k]: on })} />
          </SettingRow>
        ))}
      </Card>
      <Card title="Metadaten, Bilder & Geodaten" icon={<Wand2 size={16} />}>
        <SettingRow title="MusicBrainz-Suche" description="Beim Hinzufügen von Künstlern">
          <Toggle checked={draft.musicbrainz_lookup} onChange={(v) => set("musicbrainz_lookup", v)} />
        </SettingRow>
        <SettingRow title="Geocoding (Nominatim)" description="Unbekannte Orte automatisch einer Region zuordnen">
          <Toggle checked={draft.geocoder_enabled} onChange={(v) => set("geocoder_enabled", v)} />
        </SettingRow>
        <div className="form-grid">
          <TextField label="Geocoder-URL" value={draft.geocoder_url} onChange={(e) => set("geocoder_url", e.target.value)} className="span-2" />
          <ChipInput label="Bildquellen (Reihenfolge)" values={draft.image_providers} onChange={(v) => set("image_providers", v.filter((x) => ["official", "wikidata", "deezer"].includes(x)))} hint="official, wikidata, deezer" />
          <ChipInput label="Ticketmaster-Länder" values={draft.ticketmaster_countries} onChange={(v) => set("ticketmaster_countries", v.map((x) => x.toUpperCase().slice(0, 2)))} hint="ISO-Ländercodes, z. B. DE, LU, FR" />
        </div>
      </Card>
      <Card title="API-Schlüssel" icon={<KeyRound size={16} />} subtitle="Werte aus der .env haben Vorrang. Gespeicherte Schlüssel werden nie wieder angezeigt.">
        <div className="form-grid">
          {Object.keys(draft.api_keys).map((k) => (
            <TextField
              key={k}
              label={
                <>
                  {k} {draft.api_keys_from_env[k] ? <Badge tone="success">aus .env</Badge> : draft.api_keys[k] ? <Badge tone="accent">gespeichert</Badge> : <Badge>nicht gesetzt</Badge>}
                </>
              }
              type="password"
              autoComplete="off"
              placeholder={draft.api_keys[k] ? "•••••••• (unverändert)" : "Schlüssel eingeben"}
              value={keys[k] ?? ""}
              onChange={(e) => setKeys({ ...keys, [k]: e.target.value })}
            />
          ))}
        </div>
      </Card>
      <div className="form-actions">
        <Button variant="accent" icon={<Save size={16} />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          Speichern
        </Button>
        <Button disabled={!dirty} onClick={() => { setDraft(data ?? null); setKeys({}); }}>
          Verwerfen
        </Button>
      </div>
    </div>
  );
}
