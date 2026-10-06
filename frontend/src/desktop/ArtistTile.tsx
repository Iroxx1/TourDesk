// Desktop tile per artist: image, status, matching dates, expandable full tour.
import { memo, type KeyboardEvent } from "react";
import { AppWindow, ChevronDown, ChevronUp, Loader2, PartyPopper, RefreshCw } from "lucide-react";
import type { Tile } from "../api/types";
import { useArtistEvents } from "../api/hooks";
import { ArtistImage } from "../components/ArtistImage";
import { TourStatusPill } from "../components/badges";
import { EventLine } from "../components/EventRow";
import { Spinner, cx } from "../components/ui";
import { fmtDateRange, fmtRelative, pluralize } from "../lib/format";
import { useUi } from "../state/ui";
import { openArtist } from "../state/windows";

function FullTour({ artistId }: { artistId: number }) {
  const { data, isLoading, error } = useArtistEvents(artistId);
  if (isLoading) return <div className="tile-tour-loading"><Spinner size={16} label="Tour wird geladen" /></div>;
  if (error || !data) return <div className="tile-tour-empty">Tour konnte nicht geladen werden.</div>;
  if (!data.all_events.length) return <div className="tile-tour-empty">Keine weiteren Termine bekannt.</div>;
  const outside = data.all_events.filter((e) => e.matches === false).length;
  return (
    <div className="tile-tour">
      <div className="tile-section-head">
        Gesamte Tour · {pluralize(data.all_events.length, "Termin", "Termine")}
        {outside > 0 && <span className="tile-section-note"> · {outside} außerhalb deiner Filter</span>}
      </div>
      <div className="tile-events">
        {/* the columns live inside the scroll container: a multi-column box with a height limit
            would add further columns to the side instead of scrolling */}
        <div className="tile-tour-columns">
          {data.all_events.map((e) => (
            <EventLine key={e.id} event={e} />
          ))}
        </div>
      </div>
    </div>
  );
}

interface ArtistTileProps {
  tile: Tile;
  busy: boolean;
  size: "small" | "medium" | "large";
}

export const ArtistTile = memo(function ArtistTile({ tile, busy, size }: ArtistTileProps) {
  const expanded = useUi((s) => Boolean(s.expandedTiles[tile.artist.id]));
  const toggleTile = useUi((s) => s.toggleTile);
  const { artist, tour_status: status } = tile;
  const open = () => openArtist(artist.id, artist.name, artist.images.thumb);
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter") open();
  };
  const inactive = artist.subscription && !artist.subscription.is_active;
  const festivalsOn = artist.subscription?.show_festivals ?? false;
  const others = Math.max(0, tile.total_upcoming - tile.matching_events.length);

  return (
    <article
      className={cx("tile", `tile-${size}`, expanded && "is-expanded", inactive && "is-inactive", `tile-state-${status.state}`)}
      tabIndex={0}
      onKeyDown={onKey}
      aria-label={`${artist.name}, ${status.label}`}
    >
      <button type="button" className="tile-media" onClick={open} aria-label={`${artist.name} öffnen`}>
        <ArtistImage artist={artist} variant="tile" />
        <span className="tile-media-shade" />
        {busy && (
          <span className="tile-busy" title="Wird gerade aktualisiert">
            <Loader2 size={14} className="spin" /> Aktualisiert …
          </span>
        )}
        <span className="tile-open-hint" aria-hidden>
          <AppWindow size={14} /> Öffnen
        </span>
      </button>
      <div className="tile-body">
        <div className="tile-head">
          <h3 className="tile-name" title={artist.name}>
            {artist.name}
          </h3>
          {artist.genre && <div className="tile-genre">{artist.genre}</div>}
        </div>
        <div className="tile-status">
          <TourStatusPill status={status} size="sm" />
          {status.tour_name && status.state !== "not_on_tour" && (
            <div className="tile-tourname" title={status.detail}>
              {status.tour_name}
              {status.start_date && <span> · {fmtDateRange(status.start_date, status.end_date)}</span>}
            </div>
          )}
        </div>

        {!expanded && (
          <div className="tile-events">
            {tile.matching_events.length ? (
              tile.matching_events.map((e) => <EventLine key={e.id} event={e} />)
            ) : (
              <div className="tile-noevents">
                {tile.total_upcoming
                  ? `Keine Termine in deinen Filtern (${pluralize(tile.total_upcoming, "Termin", "Termine")} insgesamt)`
                  : artist.crawl_status === "pending"
                    ? "Termine werden gesucht …"
                    : "Keine bevorstehenden Termine bekannt"}
              </div>
            )}
          </div>
        )}
        {!expanded && others > 0 && (
          <div className="tile-more">
            {others === 1 ? "1 weiterer Termin" : `${others} weitere Termine`}
            {tile.more_count > 0 && <span className="tile-more-note"> · davon {tile.more_count} passend</span>}
          </div>
        )}
        {expanded && (
          <>
            {tile.matching_events.length > 0 && (
              <div className="tile-mine">
                <div className="tile-section-head">Meine passenden Termine</div>
                <div className="tile-events">
                  {tile.matching_events.map((e) => (
                    <EventLine key={e.id} event={e} />
                  ))}
                </div>
                {tile.more_count > 0 && <div className="tile-more">+ {tile.more_count} weitere</div>}
              </div>
            )}
            <FullTour artistId={artist.id} />
          </>
        )}

        <div className="tile-foot">
          <span className={cx("tile-festival", festivalsOn && "is-on")} title={festivalsOn ? "Festivalauftritte werden angezeigt" : "Festivals sind ausgeblendet"}>
            <PartyPopper size={13} aria-hidden />
            {festivalsOn ? "Festivals an" : "Festivals aus"}
            {tile.festival_upcoming > 0 && <span className="tile-festival-count"> · {tile.festival_upcoming}</span>}
          </span>
          <span className="tile-updated" title="Letzte erfolgreiche Aktualisierung">
            <RefreshCw size={12} aria-hidden /> {fmtRelative(tile.last_updated)}
          </span>
        </div>
        {(others > 0 || expanded) && (
          <button type="button" className="tile-expand" aria-expanded={expanded} onClick={() => toggleTile(artist.id)}>
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            {expanded ? "Weniger anzeigen" : "Gesamte Tour anzeigen"}
          </button>
        )}
      </div>
    </article>
  );
});
