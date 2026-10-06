// "Orte": browse countries → regions → cities and add any level to the personal filter.
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Globe2, Map, MapPin, Plus } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { City, Country, Region } from "../api/types";
import { useCities, useCountries, useRegions } from "../api/hooks";
import { useSession } from "../auth/session";
import { RuleToggle } from "../components/RuleToggle";
import { Button, Card, EmptyState, IconButton, SearchBox, Select, Spinner, TextField, cx } from "../components/ui";
import { fmtNumber } from "../lib/format";
import { useIsMobile } from "../lib/useMediaQuery";
import { toast } from "../state/ui";
import type { AppProps } from "./registry";

function CreateCity({ countries, initialName, defaultCountry, defaultRegion, onDone }: { countries: Country[]; initialName: string; defaultCountry: number | null; defaultRegion: number | null; onDone(c: City): void }) {
  const { readOnly } = useSession();
  const qc = useQueryClient();
  const [name, setName] = useState(initialName);
  const [countryId, setCountryId] = useState<number | null>(defaultCountry ?? countries[0]?.id ?? null);
  const [regionId, setRegionId] = useState<number | null>(defaultRegion);
  const regions = useRegions(countryId);
  const create = useMutation({
    mutationFn: () => api.post<City>("/api/cities", { name: name.trim(), country_id: countryId, region_id: regionId }),
    onSuccess: (city) => {
      toast(`${city.name} angelegt`, "success");
      qc.invalidateQueries({ queryKey: ["cities"] });
      onDone(city);
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  return (
    <Card title="Stadt anlegen" subtitle="Für Orte, die (noch) nicht im Katalog sind. Ohne Region prüft ein Administrator die Zuordnung.">
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && countryId) create.mutate();
        }}
      >
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={160} />
        <Select
          label="Land"
          value={countryId ? String(countryId) : ""}
          onChange={(v) => {
            setCountryId(Number(v));
            setRegionId(null);
          }}
          options={countries.map((c) => ({ value: String(c.id), label: c.name }))}
        />
        <Select
          label="Region"
          value={regionId ? String(regionId) : ""}
          onChange={(v) => setRegionId(v ? Number(v) : null)}
          options={[{ value: "", label: "– unbekannt –" }, ...(regions.data ?? []).map((r) => ({ value: String(r.id), label: r.name }))]}
        />
        <div className="form-actions">
          <Button type="submit" variant="accent" loading={create.isPending} disabled={readOnly || !name.trim() || !countryId}>
            Anlegen
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function PlacesApp({ win }: AppProps) {
  const countries = useCountries();
  const mobile = useIsMobile();
  const [countryId, setCountryId] = useState<number | null>((win.params.countryId as number) ?? null);
  const [regionId, setRegionId] = useState<number | null>((win.params.regionId as number) ?? null);
  const [countryQ, setCountryQ] = useState("");
  const [cityQ, setCityQ] = useState("");
  const [creating, setCreating] = useState<string | null>((win.params.create as string) ?? null);
  const [mobileStep, setMobileStep] = useState<"countries" | "regions" | "cities">(
    win.params.regionId ? "cities" : win.params.countryId ? "regions" : "countries",
  );
  const regions = useRegions(countryId);
  const cities = useCities({ q: cityQ.trim(), country_id: countryId, region_id: regionId, limit: 100 }, Boolean(regionId) || cityQ.trim().length >= 2);

  useEffect(() => {
    if (win.nonce === 0) return;
    if (win.params.countryId) setCountryId(Number(win.params.countryId));
    if (win.params.regionId) {
      setRegionId(Number(win.params.regionId));
      setMobileStep("cities");
    }
    if (win.params.create) setCreating(String(win.params.create));
  }, [win.nonce, win.params.countryId, win.params.regionId, win.params.create]);

  useEffect(() => {
    if (countryId === null && countries.data?.length) setCountryId(countries.data[0].id);
  }, [countries.data, countryId]);

  const country = countries.data?.find((c) => c.id === countryId) ?? null;
  const region = regions.data?.find((r) => r.id === regionId) ?? null;
  const countryList = (countries.data ?? []).filter((c) => !countryQ.trim() || c.name.toLowerCase().includes(countryQ.trim().toLowerCase()));
  // phones: one column at a time
  const show = (col: "countries" | "regions" | "cities") => !mobile || mobileStep === col;

  if (creating !== null && countries.data) {
    return (
      <div className="app-scroll">
        <Button variant="subtle" icon={<ArrowLeft size={16} />} onClick={() => setCreating(null)}>
          Zurück zu den Orten
        </Button>
        <CreateCity
          countries={countries.data}
          initialName={creating}
          defaultCountry={countryId}
          defaultRegion={regionId}
          onDone={(c) => {
            setCreating(null);
            setCountryId(c.country_id);
            setRegionId(c.region_id);
          }}
        />
      </div>
    );
  }

  return (
    <div className={cx("places-app", mobile && "is-mobile")}>
      {show("countries") && (
        <section className="places-col">
          <header className="places-col-head">
            <Globe2 size={15} /> Länder
          </header>
          <SearchBox value={countryQ} onChange={setCountryQ} placeholder="Land suchen" />
          <div className="places-list">
            {countries.isLoading && <Spinner />}
            {countryList.map((c) => (
              <div
                key={c.id}
                className={cx("places-item", c.id === countryId && "is-selected")}
                role="button"
                tabIndex={0}
                onClick={() => {
                  setCountryId(c.id);
                  setRegionId(null);
                  setMobileStep("regions");
                }}
                onKeyDown={(e) => e.key === "Enter" && (setCountryId(c.id), setRegionId(null), setMobileStep("regions"))}
              >
                <span className="country-code">{c.code}</span>
                <span className="places-item-text">
                  <strong>{c.name}</strong>
                  <span className="muted">{c.region_count} Regionen</span>
                </span>
                <RuleToggle compact level="country" id={c.id} label={c.name} />
              </div>
            ))}
          </div>
        </section>
      )}
      {show("regions") && (
        <section className="places-col">
          <header className="places-col-head">
            {mobile && <IconButton size="sm" label="Zurück" icon={<ArrowLeft size={16} />} onClick={() => setMobileStep("countries")} />}
            <Map size={15} /> Regionen {country ? `in ${country.name}` : ""}
          </header>
          <div className="places-list">
            {regions.isLoading && <Spinner />}
            {!regions.isLoading && !regions.data?.length && <EmptyState compact title="Keine Regionen" />}
            {(regions.data ?? []).map((r: Region) => (
              <div
                key={r.id}
                className={cx("places-item", r.id === regionId && "is-selected")}
                role="button"
                tabIndex={0}
                onClick={() => {
                  setRegionId(r.id);
                  setCityQ("");
                  setMobileStep("cities");
                }}
                onKeyDown={(e) => e.key === "Enter" && (setRegionId(r.id), setMobileStep("cities"))}
              >
                <Map size={15} className="picker-icon" />
                <span className="places-item-text">
                  <strong>{r.name}</strong>
                  <span className="muted">{r.city_count ? `${fmtNumber(r.city_count)} Orte` : r.kind}</span>
                </span>
                <RuleToggle compact level="region" id={r.id} label={r.name} />
              </div>
            ))}
          </div>
        </section>
      )}
      {show("cities") && (
        <section className="places-col places-col-wide">
          <header className="places-col-head">
            {mobile && <IconButton size="sm" label="Zurück" icon={<ArrowLeft size={16} />} onClick={() => setMobileStep("regions")} />}
            <MapPin size={15} /> {region ? `Städte in ${region.name}` : "Städte"}
          </header>
          <SearchBox value={cityQ} onChange={setCityQ} placeholder={region ? `In ${region.name} suchen` : "Stadt suchen"} />
          <div className="places-list">
            {!regionId && cityQ.trim().length < 2 && <div className="muted picker-hint">Wähle eine Region oder suche nach einer Stadt.</div>}
            {cities.isFetching && <Spinner />}
            {(cities.data ?? []).map((c) => (
              <div key={c.id} className="places-item">
                <MapPin size={15} className="picker-icon" />
                <span className="places-item-text">
                  <strong>{c.name}</strong>
                  <span className="muted">
                    {[c.region_name, c.country_name].filter(Boolean).join(" · ")}
                    {c.population ? ` · ${fmtNumber(c.population)} Einw.` : ""}
                  </span>
                </span>
                <RuleToggle compact level="city" id={c.id} label={c.name} />
              </div>
            ))}
          </div>
          <Button size="sm" variant="subtle" icon={<Plus size={14} />} onClick={() => setCreating(cityQ.trim())}>
            Stadt anlegen
          </Button>
        </section>
      )}
    </div>
  );
}
