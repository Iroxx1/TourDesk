// "Filter": hierarchical location rules (country / region / city / venue), period, event types, festivals.
import { useMemo, useState } from "react";
import { Building2, CalendarRange, Globe2, Map, MapPin, PartyPopper, Plus, SlidersHorizontal, X } from "lucide-react";
import { errorMessage } from "../api/client";
import type { FilterProfile, LocationLevel, LocationRule } from "../api/types";
import { useCities, useCountries, useDashboard, useFilter, useFilterMutations, useRegions, useVenues } from "../api/hooks";
import { useSession } from "../auth/session";
import { RuleToggle } from "../components/RuleToggle";
import { Badge, Button, Card, EmptyState, ErrorView, IconButton, Loading, SearchBox, Segmented, Select, Spinner, TextField, Toggle, cx } from "../components/ui";
import { LEVEL_LABELS, fmtNumber, pluralize } from "../lib/format";
import { toast } from "../state/ui";
import { openApp } from "../state/windows";
import type { AppProps } from "./registry";

const LEVEL_HELP: Record<LocationLevel, string> = {
  region: "Die komplette Region inklusive aller Städte und Veranstaltungsorte – z. B. „Saarland komplett“.",
  city: "Alle Veranstaltungsorte dieser Stadt – z. B. nur Metz oder Straßburg, nicht die ganze Region.",
  venue: "Nur dieser eine Veranstaltungsort – z. B. Rockhal. Stadt und Land werden dadurch nicht automatisch ausgewählt.",
  country: "Das ganze Land mit allen Regionen, Städten und Veranstaltungsorten.",
};

const LEVEL_ICON: Record<LocationLevel, typeof Map> = { country: Globe2, region: Map, city: MapPin, venue: Building2 };

function RuleGroups({ rules }: { rules: LocationRule[] }) {
  const { remove } = useFilterMutations();
  const { readOnly } = useSession();
  const groups = useMemo(() => {
    const map: Record<string, LocationRule[]> = {};
    for (const r of rules) (map[r.country_name ?? "Sonstige"] ??= []).push(r);
    return Object.entries(map);
  }, [rules]);

  if (!rules.length) {
    return (
      <EmptyState
        compact
        icon={<MapPin size={26} />}
        title="Noch keine Orte festgelegt"
        text="Ohne Ortsfilter werden Termine aus allen Ländern angezeigt. Füge rechts Regionen, Städte oder Veranstaltungsorte hinzu."
      />
    );
  }
  return (
    <div className="rule-groups">
      {groups.map(([country, items]) => {
        const complete = items.some((r) => r.level === "country");
        const summary = complete
          ? "komplett"
          : items.every((r) => r.level === "venue")
            ? `nur ${items.map((r) => r.label).join(", ")}`
            : items.map((r) => (r.level === "region" ? `${r.label} komplett` : r.label)).join(", ");
        return (
          <section key={country} className="rule-group">
            <header className="rule-group-head">
              {items[0]?.country_code && <span className="country-code">{items[0].country_code}</span>}
              <strong>{country}</strong>
              <span className="muted rule-group-summary">{summary}</span>
            </header>
            {items.map((r) => {
              const Icon = LEVEL_ICON[r.level];
              return (
                <div key={r.key} className={cx("rule", `rule-${r.level}`)}>
                  <span className="rule-icon">
                    <Icon size={15} />
                  </span>
                  <span className="rule-text">
                    <strong>{r.label}</strong>
                    <span className="muted">
                      {LEVEL_LABELS[r.level]} · {r.description}
                      {r.context && r.level !== "country" ? ` · ${r.context}` : ""}
                    </span>
                  </span>
                  <IconButton
                    size="sm"
                    label={`${r.label} entfernen`}
                    icon={<X size={14} />}
                    disabled={readOnly || remove.isPending}
                    onClick={() => remove.mutate(r.key, { onError: (e) => toast(errorMessage(e), "error") })}
                  />
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

function RegionPicker() {
  const countries = useCountries();
  const [countryId, setCountryId] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const effectiveCountry = countryId ?? countries.data?.[0]?.id ?? null;
  const regions = useRegions(effectiveCountry);
  const list = (regions.data ?? []).filter((r) => !q.trim() || r.name.toLowerCase().includes(q.trim().toLowerCase()) || r.local_name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="picker">
      <div className="picker-controls">
        <Select
          aria-label="Land"
          value={effectiveCountry ? String(effectiveCountry) : ""}
          onChange={(v) => setCountryId(Number(v))}
          options={(countries.data ?? []).filter((c) => c.region_count > 0).map((c) => ({ value: String(c.id), label: c.name }))}
        />
        <SearchBox value={q} onChange={setQ} placeholder="Region filtern" />
      </div>
      <div className="picker-list">
        {regions.isLoading && <Spinner label="Lädt" />}
        {list.map((r) => (
          <div key={r.id} className="picker-item">
            <Map size={15} className="picker-icon" />
            <span className="picker-text">
              <strong>{r.name}</strong>
              <span className="muted">
                {r.local_name !== r.name ? `${r.local_name} · ` : ""}
                {r.city_count ? `${fmtNumber(r.city_count)} Orte` : r.kind}
              </span>
            </span>
            <RuleToggle level="region" id={r.id} label={r.name} />
          </div>
        ))}
      </div>
    </div>
  );
}

function CityPicker() {
  const [q, setQ] = useState("");
  const cities = useCities({ q: q.trim(), limit: 30 }, q.trim().length >= 2);
  return (
    <div className="picker">
      <SearchBox value={q} onChange={setQ} placeholder="Stadt suchen, z. B. Metz, Straßburg, Trier" autoFocus />
      <div className="picker-list">
        {q.trim().length < 2 && <div className="muted picker-hint">Mindestens zwei Buchstaben eingeben.</div>}
        {cities.isFetching && <Spinner label="Suche" />}
        {(cities.data ?? []).map((c) => (
          <div key={c.id} className="picker-item">
            <MapPin size={15} className="picker-icon" />
            <span className="picker-text">
              <strong>{c.name}</strong>
              <span className="muted">
                {[c.local_name !== c.name ? c.local_name : null, c.region_name, c.country_name].filter(Boolean).join(" · ")}
                {c.population ? ` · ${fmtNumber(c.population)} Einw.` : ""}
              </span>
            </span>
            <RuleToggle level="city" id={c.id} label={c.name} />
          </div>
        ))}
        {q.trim().length >= 2 && cities.data && !cities.data.length && !cities.isFetching && (
          <div className="muted picker-hint">
            Keine Stadt gefunden.{" "}
            <button type="button" className="link-button" onClick={() => openApp("places", { create: q.trim() })}>
              Stadt anlegen ›
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function VenuePicker() {
  const [q, setQ] = useState("");
  const venues = useVenues({ q: q.trim(), limit: 30 }, q.trim().length >= 2);
  return (
    <div className="picker">
      <SearchBox value={q} onChange={setQ} placeholder="Veranstaltungsort suchen, z. B. Rockhal, Garage" autoFocus />
      <div className="picker-list">
        {q.trim().length < 2 && <div className="muted picker-hint">Mindestens zwei Buchstaben eingeben.</div>}
        {venues.isFetching && <Spinner label="Suche" />}
        {(venues.data ?? []).map((v) => (
          <div key={v.id} className="picker-item">
            <Building2 size={15} className="picker-icon" />
            <span className="picker-text">
              <strong>{v.name}</strong>
              <span className="muted">
                {[v.city_name, v.region_name, v.country_name].filter(Boolean).join(" · ")}
                {v.aliases.length ? ` · auch: ${v.aliases.slice(0, 2).join(", ")}` : ""}
              </span>
            </span>
            <RuleToggle level="venue" id={v.id} label={v.name} />
          </div>
        ))}
        {q.trim().length >= 2 && venues.data && !venues.data.length && !venues.isFetching && <div className="muted picker-hint">Kein Veranstaltungsort gefunden.</div>}
      </div>
      <Button size="sm" variant="subtle" icon={<Plus size={14} />} onClick={() => openApp("venues", { tab: "create", name: q.trim() })}>
        Neuen Veranstaltungsort anlegen
      </Button>
    </div>
  );
}

function CountryPicker() {
  const countries = useCountries();
  const [q, setQ] = useState("");
  const list = (countries.data ?? []).filter((c) => !q.trim() || c.name.toLowerCase().includes(q.trim().toLowerCase()) || c.code.toLowerCase() === q.trim().toLowerCase());
  return (
    <div className="picker">
      <SearchBox value={q} onChange={setQ} placeholder="Land suchen" />
      <div className="picker-list">
        {list.slice(0, 80).map((c) => (
          <div key={c.id} className="picker-item">
            <span className="country-code">{c.code}</span>
            <span className="picker-text">
              <strong>{c.name}</strong>
              <span className="muted">{c.region_count ? `${c.region_count} Regionen` : "Land"}</span>
            </span>
            <RuleToggle level="country" id={c.id} label={c.name} />
          </div>
        ))}
      </div>
    </div>
  );
}

function PeriodCard({ f }: { f: FilterProfile }) {
  const { update } = useFilterMutations();
  const { readOnly } = useSession();
  const set = (patch: Partial<FilterProfile>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });
  return (
    <Card title="Zeitraum" icon={<CalendarRange size={16} />}>
      <Segmented<FilterProfile["date_mode"]>
        label="Zeitraum"
        value={f.date_mode}
        disabled={readOnly}
        onChange={(date_mode) => set({ date_mode })}
        options={[
          { value: "upcoming", label: "Alle kommenden" },
          { value: "months", label: "Nächste Monate" },
          { value: "range", label: "Zeitraum" },
        ]}
      />
      {f.date_mode === "months" && (
        <Select
          label="Monate im Voraus"
          value={String(f.months_ahead ?? 12)}
          disabled={readOnly}
          onChange={(v) => set({ months_ahead: Number(v) })}
          options={[1, 2, 3, 6, 9, 12, 18, 24].map((m) => ({ value: String(m), label: `${m} ${m === 1 ? "Monat" : "Monate"}` }))}
        />
      )}
      {f.date_mode === "range" && (
        <div className="form-row">
          <TextField label="Von" type="date" value={f.date_from ?? ""} disabled={readOnly} onChange={(e) => set({ date_from: e.target.value || null })} />
          <TextField label="Bis" type="date" value={f.date_to ?? ""} disabled={readOnly} onChange={(e) => set({ date_to: e.target.value || null })} />
        </div>
      )}
    </Card>
  );
}

function TypesCard({ f }: { f: FilterProfile }) {
  const { update } = useFilterMutations();
  const { readOnly } = useSession();
  const set = (patch: Partial<FilterProfile>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });
  return (
    <Card title="Konzertfilter" icon={<SlidersHorizontal size={16} />}>
      <Toggle label="Konzerte / Tourtermine" checked={f.include_concerts} disabled={readOnly} onChange={(v) => set({ include_concerts: v })} />
      <Toggle label="Support-Auftritte" description="Der Künstler spielt im Vorprogramm" checked={f.include_support} disabled={readOnly} onChange={(v) => set({ include_support: v })} />
      <Toggle label="Special Events" description="Akustik-Shows, Release-Partys, Sonderkonzerte" checked={f.include_special} disabled={readOnly} onChange={(v) => set({ include_special: v })} />
      <Toggle label="Abgesagte & verschobene Termine" description="Werden deutlich gekennzeichnet statt ausgeblendet" checked={f.show_cancelled} disabled={readOnly} onChange={(v) => set({ show_cancelled: v })} />
      <Toggle
        label="Unbestätigte Termine"
        description="Termine, die nur von wenig vertrauenswürdigen Quellen gemeldet werden"
        checked={f.show_unconfirmed}
        disabled={readOnly}
        onChange={(v) => set({ show_unconfirmed: v })}
      />
    </Card>
  );
}

function FestivalCard({ f }: { f: FilterProfile }) {
  const { update } = useFilterMutations();
  const { readOnly } = useSession();
  const set = (patch: Partial<FilterProfile>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });
  return (
    <Card title="Festivalfilter" icon={<PartyPopper size={16} />} subtitle="Gerüchte und unbestätigte Teilnahmen werden nie als bestätigte Termine angezeigt.">
      <Segmented<FilterProfile["festival_mode"]>
        label="Festivals"
        value={f.festival_mode}
        disabled={readOnly}
        onChange={(festival_mode) => set({ festival_mode })}
        options={[
          { value: "artist", label: "Pro Künstler" },
          { value: "always", label: "Immer anzeigen" },
          { value: "never", label: "Nie anzeigen" },
        ]}
      />
      <p className="muted small">
        {f.festival_mode === "artist"
          ? "Der Schalter „Festivals anzeigen“ beim jeweiligen Künstler entscheidet."
          : f.festival_mode === "always"
            ? "Festivalauftritte aller Künstler werden angezeigt."
            : "Festivalauftritte werden generell ausgeblendet."}
      </p>
      <Segmented<FilterProfile["festival_scope"]>
        label="Festival-Orte"
        value={f.festival_scope}
        disabled={readOnly || f.festival_mode === "never"}
        onChange={(festival_scope) => set({ festival_scope })}
        options={[
          { value: "filters", label: "Nur in meinen Orten" },
          { value: "anywhere", label: "Überall" },
        ]}
      />
      <Toggle
        label="Festivals für neue Künstler einschalten"
        description="Voreinstellung des Festival-Schalters beim Hinzufügen"
        checked={f.default_show_festivals}
        disabled={readOnly}
        onChange={(v) => set({ default_show_festivals: v })}
      />
    </Card>
  );
}

export function FiltersApp({ win }: AppProps) {
  const { data: f, isLoading, error, refetch } = useFilter();
  const dashboard = useDashboard();
  const [level, setLevel] = useState<LocationLevel>((win.params.level as LocationLevel) || "region");
  if (isLoading) return <Loading />;
  if (error || !f) return <ErrorView error={error} retry={refetch} />;
  const Icon = LEVEL_ICON[level];

  return (
    <div className="app-scroll filters-app">
      <div className="filters-summary">
        <Badge tone="accent">{pluralize(f.locations.length, "Ortsregel", "Ortsregeln")}</Badge>
        {dashboard.data && <span className="muted">Aktuell passen {pluralize(dashboard.data.total_matching, "Termin", "Termine")} zu deinen Filtern.</span>}
      </div>
      <div className="filters-columns">
        <Card title="Meine Orte" icon={<MapPin size={16} />} subtitle="Regeln werden kombiniert: ein Termin wird angezeigt, wenn er zu mindestens einer Regel passt." className="filters-rules">
          <RuleGroups rules={f.locations} />
        </Card>
        <Card title="Ort hinzufügen" icon={<Plus size={16} />} className="filters-add">
          <Segmented<LocationLevel>
            label="Ebene"
            value={level}
            onChange={setLevel}
            options={[
              { value: "region", label: "Region", icon: <Map size={14} /> },
              { value: "city", label: "Stadt", icon: <MapPin size={14} /> },
              { value: "venue", label: "Veranstaltungsort", icon: <Building2 size={14} /> },
              { value: "country", label: "Land", icon: <Globe2 size={14} /> },
            ]}
          />
          <p className="level-help">
            <Icon size={14} /> {LEVEL_HELP[level]}
          </p>
          {level === "region" && <RegionPicker />}
          {level === "city" && <CityPicker />}
          {level === "venue" && <VenuePicker />}
          {level === "country" && <CountryPicker />}
        </Card>
      </div>
      <div className="filters-cards">
        <PeriodCard f={f} />
        <TypesCard f={f} />
        <FestivalCard f={f} />
      </div>
    </div>
  );
}
