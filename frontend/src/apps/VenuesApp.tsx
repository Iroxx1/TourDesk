// "Veranstaltungsorte": preferred venues, venue search and creating new venues.
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, CalendarDays, ExternalLink, Plus, Rss, Search, Star } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { City, Venue } from "../api/types";
import { useCities, useVenues } from "../api/hooks";
import { useSession } from "../auth/session";
import { RuleToggle } from "../components/RuleToggle";
import { Badge, Button, Card, ChipInput, EmptyState, Loading, SearchBox, Spinner, Tabs, TextField, Toggle, cx } from "../components/ui";
import { safeHref, hostOf } from "../lib/urls";
import { toast } from "../state/ui";
import { openApp } from "../state/windows";
import type { AppProps } from "./registry";

type Tab = "mine" | "search" | "create";

function VenueItem({ v }: { v: Venue }) {
  const web = safeHref(v.website);
  return (
    <div className="venue-item">
      <span className="venue-icon">
        <Building2 size={18} />
      </span>
      <span className="venue-text">
        <strong>{v.name}</strong>
        <span className="muted">
          {[v.city_name, v.region_name, v.country_name].filter(Boolean).join(" · ")}
          {v.capacity ? ` · ${v.capacity.toLocaleString("de-DE")} Plätze` : ""}
        </span>
        <span className="venue-badges">
          {v.upcoming_event_count ? (
            <button type="button" className="badge badge-accent badge-button" onClick={() => openApp("agenda", { q: v.name, scope: "all" })}>
              <CalendarDays size={12} /> {v.upcoming_event_count} Termine
            </button>
          ) : null}
          {v.has_agenda_source && (
            <Badge tone="success" title="Das Programm dieses Ortes wird regelmäßig durchsucht">
              <Rss size={12} /> Programm wird überwacht
            </Badge>
          )}
          {v.aliases.length > 0 && <span className="muted small">auch: {v.aliases.slice(0, 3).join(", ")}</span>}
          {web && (
            <a className="muted small" href={web} target="_blank" rel="noopener noreferrer nofollow">
              {hostOf(web)} <ExternalLink size={11} />
            </a>
          )}
        </span>
      </span>
      <RuleToggle level="venue" id={v.id} label={v.name} />
    </div>
  );
}

function CityField({ value, onChange }: { value: City | null; onChange(c: City | null): void }) {
  const [q, setQ] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const cities = useCities({ q: q.trim(), limit: 12 }, open && q.trim().length >= 2);
  return (
    <div className="combo">
      <TextField
        label="Stadt"
        required
        value={q}
        placeholder="z. B. Esch-sur-Alzette"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          if (value) onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        hint={value ? [value.region_name, value.country_name].filter(Boolean).join(", ") : "Stadt aus der Liste wählen"}
        autoComplete="off"
      />
      {open && q.trim().length >= 2 && (
        <div className="combo-list" role="listbox">
          {cities.isFetching && <Spinner size={14} />}
          {(cities.data ?? []).map((c) => (
            <button
              key={c.id}
              type="button"
              role="option"
              aria-selected={value?.id === c.id}
              className="combo-option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(c);
                setQ(c.name);
                setOpen(false);
              }}
            >
              <strong>{c.name}</strong>
              <span className="muted">{[c.region_name, c.country_name].filter(Boolean).join(", ")}</span>
            </button>
          ))}
          {cities.data && !cities.data.length && !cities.isFetching && <div className="muted combo-empty">Keine Stadt gefunden</div>}
        </div>
      )}
    </div>
  );
}

function CreateVenue({ initialName, onCreated }: { initialName: string; onCreated(v: Venue): void }) {
  const { readOnly } = useSession();
  const qc = useQueryClient();
  const [name, setName] = useState(initialName);
  const [city, setCity] = useState<City | null>(null);
  const [address, setAddress] = useState("");
  const [postal, setPostal] = useState("");
  const [website, setWebsite] = useState("");
  const [agenda, setAgenda] = useState("");
  const [aliases, setAliases] = useState<string[]>([]);
  const [addToFilters, setAddToFilters] = useState(true);
  const create = useMutation({
    mutationFn: () =>
      api.post<Venue>("/api/venues", {
        name: name.trim(),
        city_id: city?.id,
        address: address.trim() || null,
        postal_code: postal.trim() || null,
        website: website.trim() || null,
        agenda_url: agenda.trim() || null,
        aliases,
        add_to_filters: addToFilters,
      }),
    onSuccess: (v) => {
      toast(`${v.name} gespeichert${addToFilters ? " und zu deinen Filtern hinzugefügt" : ""}`, "success");
      qc.invalidateQueries({ queryKey: ["venues"] });
      qc.invalidateQueries({ queryKey: ["filter"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onCreated(v);
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  return (
    <Card title="Neuen Veranstaltungsort anlegen" icon={<Plus size={16} />} subtitle="Mit Programm-URL durchsucht TourDesk zusätzlich den Veranstaltungskalender des Ortes nach deinen Künstlern.">
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && city) create.mutate();
        }}
      >
        <TextField label="Name" required minLength={2} maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        <CityField value={city} onChange={setCity} />
        <TextField label="Adresse" value={address} onChange={(e) => setAddress(e.target.value)} />
        <TextField label="Postleitzahl" value={postal} onChange={(e) => setPostal(e.target.value)} maxLength={20} />
        <TextField label="Website" type="url" placeholder="https://" value={website} onChange={(e) => setWebsite(e.target.value)} />
        <TextField label="Programm-/Kalender-URL" type="url" placeholder="https://…/programm" value={agenda} onChange={(e) => setAgenda(e.target.value)} hint="Optional – sonst wird die Website verwendet." />
        <ChipInput label="Alternative Namen" values={aliases} onChange={setAliases} placeholder="z. B. Messegelände Luxemburg" />
        <Toggle label="Zu meinen Filtern hinzufügen" checked={addToFilters} onChange={setAddToFilters} />
        <div className="form-actions span-2">
          <Button type="submit" variant="accent" loading={create.isPending} disabled={readOnly || !name.trim() || !city}>
            Speichern
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function VenuesApp({ win }: AppProps) {
  const [tab, setTab] = useState<Tab>((win.params.tab as Tab) || "mine");
  const [q, setQ] = useState("");
  const [createName, setCreateName] = useState(String(win.params.name ?? ""));
  const favorites = useVenues({ favorites: true }, tab === "mine");
  const search = useVenues({ q: q.trim(), limit: 50 }, tab === "search" && q.trim().length >= 2);

  useEffect(() => {
    if (win.nonce === 0) return;
    if (win.params.tab) setTab(win.params.tab as Tab);
    if (win.params.name !== undefined) setCreateName(String(win.params.name ?? ""));
  }, [win.nonce, win.params.tab, win.params.name]);

  return (
    <div className="app-scroll stack">
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "mine", label: "Bevorzugte Veranstaltungsorte", icon: <Star size={15} />, count: favorites.data?.length ?? null },
          { id: "search", label: "Suchen", icon: <Search size={15} /> },
          { id: "create", label: "Hinzufügen", icon: <Plus size={15} /> },
        ]}
      />
      {tab === "mine" && (
        <Card padded={false} className={cx("venue-card")}>
          {favorites.isLoading && <Loading />}
          {favorites.data && !favorites.data.length && (
            <EmptyState
              compact
              icon={<Building2 size={26} />}
              title="Noch keine bevorzugten Veranstaltungsorte"
              text="Wähle einzelne Orte wie die Rockhal, ohne gleich das ganze Land auszuwählen."
              action={<Button onClick={() => setTab("search")}>Veranstaltungsort suchen</Button>}
            />
          )}
          {favorites.data?.map((v) => <VenueItem key={v.id} v={v} />)}
        </Card>
      )}
      {tab === "search" && (
        <>
          <SearchBox value={q} onChange={setQ} placeholder="Name, Alias oder Stadt – z. B. Rockhal, Messegelände, Saarbrücken" autoFocus />
          <Card padded={false} className="venue-card">
            {q.trim().length < 2 && <EmptyState compact title="Veranstaltungsort suchen" text="Mindestens zwei Buchstaben eingeben." />}
            {search.isFetching && <Loading label="Suche …" />}
            {search.data?.map((v) => <VenueItem key={v.id} v={v} />)}
            {q.trim().length >= 2 && search.data && !search.data.length && !search.isFetching && (
              <EmptyState
                compact
                title="Nichts gefunden"
                action={
                  <Button
                    icon={<Plus size={16} />}
                    onClick={() => {
                      setCreateName(q.trim());
                      setTab("create");
                    }}
                  >
                    „{q.trim()}“ anlegen
                  </Button>
                }
              />
            )}
          </Card>
        </>
      )}
      {tab === "create" && <CreateVenue key={createName} initialName={createName} onCreated={() => setTab("mine")} />}
    </div>
  );
}
