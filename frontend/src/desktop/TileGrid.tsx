// The desktop content: greeting widget, hints and the artist tiles.
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CalendarCheck2, Clock, MapPinned, Music4, Plus, Radar, Sparkles } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Artist, Tile } from "../api/types";
import { useCrawlerStatus, useDashboard, useInvalidateArtistData } from "../api/hooks";
import { useSession } from "../auth/session";
import { Button, EmptyState, InfoBar, Segmented, Skeleton, cx } from "../components/ui";
import { fmtLongDate, fmtRelative, greeting, isoDay, pluralize } from "../lib/format";
import { toast } from "../state/ui";
import { openApp } from "../state/windows";
import { ArtistTile } from "./ArtistTile";

type TileFilter = "all" | "events" | "tour";

function sortTiles(tiles: Tile[], sort: string): Tile[] {
  const collator = new Intl.Collator("de", { sensitivity: "base" });
  const byName = (a: Tile, b: Tile) => collator.compare(a.artist.name, b.artist.name);
  const nextOf = (t: Tile) => t.matching_events[0]?.date ?? null;
  const sorted = [...tiles].sort((a, b) => {
    const pa = a.artist.subscription?.pinned ? 0 : 1;
    const pb = b.artist.subscription?.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    if (sort === "name") return byName(a, b);
    if (sort === "added") {
      const sa = a.artist.subscription?.sort_order ?? 0;
      const sb = b.artist.subscription?.sort_order ?? 0;
      if (sa !== sb) return sa - sb;
      return (a.artist.subscription?.created_at ?? "").localeCompare(b.artist.subscription?.created_at ?? "");
    }
    const na = nextOf(a);
    const nb = nextOf(b);
    if (na && nb && na !== nb) return na < nb ? -1 : 1;
    if (na && !nb) return -1;
    if (!na && nb) return 1;
    const ta = a.tour_status.next_date;
    const tb = b.tour_status.next_date;
    if (ta && tb && ta !== tb) return ta < tb ? -1 : 1;
    if (ta && !tb) return -1;
    if (!ta && tb) return 1;
    return byName(a, b);
  });
  return sorted;
}

function WelcomeCard() {
  const invalidate = useInvalidateArtistData();
  const { readOnly } = useSession();
  const addDemo = useMutation({
    mutationFn: () => api.post<Artist>("/api/artists", { name: "Beispielband" }),
    onSuccess: () => {
      toast("Beispielband hinzugefügt – die Demo-Termine erscheinen in wenigen Sekunden.", "success");
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  return (
    <div className="welcome">
      <div className="welcome-art" aria-hidden>
        <Music4 size={42} />
      </div>
      <h2>Willkommen bei TourDesk</h2>
      <p>Lege die Künstler an, die dich interessieren. TourDesk durchsucht ungefähr stündlich offizielle Websites, Veranstaltungsorte, Festivals und Ticketanbieter und zeigt dir nur die Termine, die zu deinen Orten passen.</p>
      <ol className="welcome-steps">
        <li>
          <span>1</span> Künstler hinzufügen
        </li>
        <li>
          <span>2</span> Regionen, Städte und Veranstaltungsorte festlegen
        </li>
        <li>
          <span>3</span> Festival-Schalter pro Künstler einstellen
        </li>
      </ol>
      <div className="welcome-actions">
        <Button variant="accent" size="lg" icon={<Plus size={18} />} disabled={readOnly} onClick={() => openApp("artists", { add: true })}>
          Künstler hinzufügen
        </Button>
        <Button size="lg" icon={<MapPinned size={18} />} onClick={() => openApp("filters")}>
          Orte festlegen
        </Button>
      </div>
      <button type="button" className="welcome-demo" disabled={readOnly || addDemo.isPending} onClick={() => addDemo.mutate()}>
        <Sparkles size={14} /> Erst einmal ausprobieren? <strong>„Beispielband“ mit Demo-Terminen hinzufügen</strong>
      </button>
    </div>
  );
}

export function TileGrid() {
  const { me } = useSession();
  const { data, isLoading, error, refetch } = useDashboard();
  const crawler = useCrawlerStatus();
  const [filter, setFilter] = useState<TileFilter>("all");
  const view = me.settings.view;
  const busy = useMemo(() => new Set([...(crawler.data?.running ?? []), ...(crawler.data?.queued ?? [])]), [crawler.data]);

  const tiles = useMemo(() => {
    if (!data) return [];
    let list = sortTiles(data.tiles, view.sort);
    if (!view.show_artists_without_events) list = list.filter((t) => t.total_upcoming > 0 || t.matching_count > 0);
    if (filter === "events") list = list.filter((t) => t.matching_count > 0);
    if (filter === "tour") list = list.filter((t) => t.tour_status.state !== "not_on_tour");
    return list;
  }, [data, view.sort, view.show_artists_without_events, filter]);

  const name = me.user.display_name || me.user.username;
  const onTour = data?.tiles.filter((t) => t.tour_status.state === "on_tour").length ?? 0;
  const announced = data?.tiles.filter((t) => t.tour_status.state === "announced").length ?? 0;
  const running = crawler.data?.running.length ?? 0;
  const queued = crawler.data?.queued.length ?? 0;
  const today = isoDay(new Date());

  return (
    <div className="desktop-main">
      <section className="widget-hero">
        <div className="widget-hero-text">
          <div className="widget-date">{fmtLongDate(today)}</div>
          <h1 className="widget-greeting">
            {greeting()}, {name}
          </h1>
          {data && (
            <div className="widget-summary">
              <span className="chip-stat">
                <CalendarCheck2 size={15} /> {pluralize(data.total_matching, "passender Termin", "passende Termine")}
              </span>
              <span className="chip-stat chip-on">
                <span className="tour-dot tour-dot-on" /> {onTour} auf Tour
              </span>
              <span className="chip-stat chip-announced">
                <span className="tour-dot tour-dot-announced" /> {announced} angekündigt
              </span>
              <span className={cx("chip-stat", (running || queued) > 0 && "is-busy")} title="Status des Crawlers">
                {running || queued ? <Radar size={15} className="pulse" /> : <Clock size={15} />}
                {running || queued
                  ? `Suche läuft für ${pluralize(running + queued, "Künstler", "Künstler")}`
                  : `Zuletzt aktualisiert ${fmtRelative(data.crawler_last_run ?? crawler.data?.last_run_at ?? null)}`}
              </span>
            </div>
          )}
        </div>
        {data && data.tiles.length > 0 && (
          <div className="widget-hero-actions">
            <Segmented<TileFilter>
              label="Kacheln filtern"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "Alle" },
                { value: "events", label: "Mit Terminen" },
                { value: "tour", label: "Auf Tour" },
              ]}
            />
            <Button variant="accent" icon={<Plus size={16} />} onClick={() => openApp("artists", { add: true })}>
              Künstler
            </Button>
          </div>
        )}
      </section>

      {data && !data.has_location_rules && data.tiles.length > 0 && (
        <InfoBar
          tone="info"
          className="desktop-infobar"
          title="Noch keine Orte festgelegt."
          action={
            <Button size="sm" onClick={() => openApp("filters")}>
              Orte festlegen
            </Button>
          }
        >
          Es werden Termine aus allen Ländern angezeigt. Lege Regionen, Städte oder Veranstaltungsorte fest, um nur relevante Termine zu sehen.
        </InfoBar>
      )}

      {error && (
        <InfoBar tone="error" title="Dashboard konnte nicht geladen werden." action={<Button size="sm" onClick={() => refetch()}>Erneut versuchen</Button>}>
          {errorMessage(error)}
        </InfoBar>
      )}

      {isLoading && (
        <div className={cx("tile-grid", `grid-${view.tile_size}`)}>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="tile tile-skeleton">
              <div className="tile-media" />
              <div className="tile-body">
                <Skeleton lines={4} />
              </div>
            </div>
          ))}
        </div>
      )}

      {data && data.tiles.length === 0 && <WelcomeCard />}

      {data && data.tiles.length > 0 && tiles.length === 0 && (
        <EmptyState
          title="Keine Künstler für diese Auswahl"
          text={filter === "events" ? "Aktuell hat keiner deiner Künstler passende Termine." : "Derzeit ist keiner deiner Künstler auf Tour."}
          action={<Button onClick={() => setFilter("all")}>Alle anzeigen</Button>}
        />
      )}

      {tiles.length > 0 && (
        <div className={cx("tile-grid", `grid-${view.tile_size}`)}>
          {tiles.map((t) => (
            <ArtistTile key={t.artist.id} tile={t} busy={busy.has(t.artist.id)} size={view.tile_size} />
          ))}
        </div>
      )}
    </div>
  );
}
