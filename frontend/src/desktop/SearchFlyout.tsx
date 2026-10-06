// Global search: artists, catalogue artists, events, venues, cities, regions, countries.
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Building2, CalendarDays, Globe2, Map, MapPin, Mic2, Plus, Search } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Artist } from "../api/types";
import { useInvalidateArtistData, useSearch } from "../api/hooks";
import { useSession } from "../auth/session";
import { ArtistImage } from "../components/ArtistImage";
import { EventRow } from "../components/EventRow";
import { RuleToggle } from "../components/RuleToggle";
import { IconButton, Spinner, cx } from "../components/ui";
import { toast, useUi } from "../state/ui";
import { openApp, openArtist } from "../state/windows";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function SearchFlyout() {
  const query = useUi((s) => s.searchQuery);
  const setQuery = useUi((s) => s.setSearchQuery);
  const close = () => useUi.getState().setFlyout(null);
  const debounced = useDebounced(query, 220);
  const { data, isFetching } = useSearch(debounced);
  const invalidate = useInvalidateArtistData();
  const { readOnly } = useSession();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const follow = useMutation({
    mutationFn: (a: { id: number; name: string }) => api.post<Artist>("/api/artists", { name: a.name, artist_id: a.id }),
    onSuccess: (artist) => {
      toast(`${artist.name} wird jetzt überwacht`, "success");
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });

  const has =
    data &&
    (data.artists.length || data.catalog_artists.length || data.events.length || data.venues.length || data.cities.length || data.regions.length || data.countries.length);
  const short = query.trim().length < 2;

  return (
    <div className="flyout search-flyout" role="dialog" aria-label="Suche">
      <div className="search-head">
        <Search size={18} aria-hidden />
        <input
          ref={input}
          className="search-input"
          placeholder="Suche nach Künstlern, Veranstaltungsorten, Städten, Regionen …"
          aria-label="Suchbegriff"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {isFetching && <Spinner size={16} />}
      </div>
      <div className="search-body">
        {short && (
          <div className="search-hint">
            <p>Beispiele:</p>
            <div className="search-examples">
              {["Rockhal", "Saarland", "Metz", "Festival"].map((ex) => (
                <button key={ex} type="button" className="chip chip-button" onClick={() => setQuery(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {!short && data && !has && !isFetching && <div className="search-empty">Keine Treffer für „{data.query}“.</div>}

        {data && data.artists.length > 0 && (
          <section className="search-group">
            <h3>
              <Mic2 size={14} /> Meine Künstler
            </h3>
            {data.artists.map((a) => (
              <button
                key={a.id}
                type="button"
                className="search-item"
                onClick={() => {
                  openArtist(a.id, a.name, a.images.thumb);
                  close();
                }}
              >
                <ArtistImage artist={a} variant="thumb" className="search-thumb" />
                <span className="search-item-text">
                  <strong>{a.name}</strong>
                  <span>{a.genre || "Künstler"}</span>
                </span>
              </button>
            ))}
          </section>
        )}

        {data && data.catalog_artists.length > 0 && (
          <section className="search-group">
            <h3>
              <Mic2 size={14} /> Weitere Künstler im Katalog
            </h3>
            {data.catalog_artists.map((a) => (
              <div key={a.id} className="search-item">
                <span className="search-item-icon">
                  <Mic2 size={16} />
                </span>
                <span className="search-item-text">
                  <strong>{a.name}</strong>
                  <span>{a.genre || "Im Katalog vorhanden"}</span>
                </span>
                <IconButton
                  size="sm"
                  label={`${a.name} überwachen`}
                  icon={<Plus size={14} />}
                  disabled={readOnly || follow.isPending}
                  onClick={() => follow.mutate(a)}
                />
              </div>
            ))}
          </section>
        )}

        {data && data.events.length > 0 && (
          <section className="search-group">
            <h3>
              <CalendarDays size={14} /> Termine
            </h3>
            <div className="search-events">
              {data.events.slice(0, 12).map((e) => (
                <EventRow key={e.id} event={e} showArtist />
              ))}
            </div>
            {data.events.length > 12 && (
              <button
                type="button"
                className="search-more"
                onClick={() => {
                  openApp("agenda", { q: data.query, scope: "all" });
                  close();
                }}
              >
                Alle {data.events.length} Termine anzeigen ›
              </button>
            )}
          </section>
        )}

        {data && data.venues.length > 0 && (
          <section className="search-group">
            <h3>
              <Building2 size={14} /> Veranstaltungsorte
            </h3>
            {data.venues.map((v) => (
              <div key={v.id} className="search-item" role="button" tabIndex={0} onClick={() => { openApp("agenda", { q: v.name, scope: "all" }); close(); }} onKeyDown={(e) => { if (e.key === "Enter") { openApp("agenda", { q: v.name, scope: "all" }); close(); } }}>
                <span className="search-item-icon">
                  <Building2 size={16} />
                </span>
                <span className="search-item-text">
                  <strong>{v.name}</strong>
                  <span>{[v.city_name, v.country_name].filter(Boolean).join(", ")}{v.upcoming_event_count ? ` · ${v.upcoming_event_count} Termine` : ""}</span>
                </span>
                <RuleToggle compact level="venue" id={v.id} label={v.name} />
              </div>
            ))}
          </section>
        )}

        {data && (data.regions.length > 0 || data.cities.length > 0 || data.countries.length > 0) && (
          <section className="search-group">
            <h3>
              <Map size={14} /> Orte
            </h3>
            {data.countries.map((c) => (
              <div key={`c${c.id}`} className={cx("search-item")}>
                <span className="search-item-icon">
                  <Globe2 size={16} />
                </span>
                <span className="search-item-text">
                  <strong>{c.name}</strong>
                  <span>Land · komplett</span>
                </span>
                <RuleToggle compact level="country" id={c.id} label={c.name} />
              </div>
            ))}
            {data.regions.map((r) => (
              <div key={`r${r.id}`} className="search-item" role="button" tabIndex={0} onClick={() => { openApp("places", { countryId: r.country_id, regionId: r.id }); close(); }} onKeyDown={(e) => { if (e.key === "Enter") { openApp("places", { countryId: r.country_id, regionId: r.id }); close(); } }}>
                <span className="search-item-icon">
                  <Map size={16} />
                </span>
                <span className="search-item-text">
                  <strong>{r.name}</strong>
                  <span>Region in {r.country_name} · alle Städte und Veranstaltungsorte</span>
                </span>
                <RuleToggle compact level="region" id={r.id} label={r.name} />
              </div>
            ))}
            {data.cities.map((c) => (
              <div key={`ci${c.id}`} className="search-item">
                <span className="search-item-icon">
                  <MapPin size={16} />
                </span>
                <span className="search-item-text">
                  <strong>{c.name}</strong>
                  <span>{[c.region_name, c.country_name].filter(Boolean).join(", ")}</span>
                </span>
                <RuleToggle compact level="city" id={c.id} label={c.name} />
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
