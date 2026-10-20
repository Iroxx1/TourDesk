// "Programm": complete upcoming programme of a selected venue (all artists); follow single artists from here.
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, ExternalLink, Plus, RefreshCw, Ticket } from "lucide-react";
import { ApiError, api, errorMessage } from "../api/client";
import type { Artist, ProgrammeArtist, ProgrammeItem, VenueProgramme } from "../api/types";
import { useInvalidateArtistData, useVenueProgramme } from "../api/hooks";
import { useSession } from "../auth/session";
import { Badge, Button, Card, EmptyState, ErrorView, InfoBar, Loading, SearchBox, Spinner } from "../components/ui";
import { fmtMonthShort, fmtMonthYear, fmtRelative, fmtTime, fmtWeekdayShort } from "../lib/format";
import { safeHref } from "../lib/urls";
import { toast } from "../state/ui";
import { openArtist } from "../state/windows";
import type { AppProps } from "./registry";

const normalizeSearch = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

const SOURCE_LABELS: Record<string, string> = {
  venue_website: "Programmseite",
  ticketmaster_venue: "Ticketmaster",
};

const STATUS_LABELS: Record<string, string> = {
  cancelled: "Abgesagt",
  postponed: "Verschoben",
  rescheduled: "Neuer Termin",
};

function ArtistAction({ a, venueId }: { a: ProgrammeArtist; venueId: number }) {
  const { readOnly } = useSession();
  const qc = useQueryClient();
  const invalidate = useInvalidateArtistData();
  const add = useMutation({
    mutationFn: () =>
      api.post<Artist>(
        "/api/artists",
        a.artist_id ? { name: a.name, artist_id: a.artist_id } : { name: a.name, musicbrainz_id: a.musicbrainz_id ?? null },
      ),
    onSuccess: (artist) => {
      toast(`${artist.name} ist jetzt auf deiner Übersicht – die Suche nach Terminen läuft.`, "success");
      invalidate(artist.id);
      qc.invalidateQueries({ queryKey: ["venue-programme", venueId] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) qc.invalidateQueries({ queryKey: ["venue-programme", venueId] });
      toast(errorMessage(e), e instanceof ApiError && e.status === 409 ? "info" : "error");
    },
  });
  if (a.followed && a.artist_id) {
    return (
      <button type="button" className="badge badge-success badge-button" onClick={() => openArtist(a.artist_id as number, a.name)} title="Künstler öffnen">
        <Check size={12} /> {a.name}
      </button>
    );
  }
  return (
    <span className="programme-artist">
      <span className="programme-artist-name">{a.name}</span>
      <Button size="sm" icon={<Plus size={14} />} loading={add.isPending} disabled={readOnly} onClick={() => add.mutate()}
        title={`${a.name} auf deine Übersicht setzen und nach Terminen suchen`}>
        Hinzufügen
      </Button>
    </span>
  );
}

function ProgrammeRow({ item, venueId }: { item: ProgrammeItem; venueId: number }) {
  const url = safeHref(item.url);
  const tickets = safeHref(item.ticket_url);
  const time = fmtTime(item.time);
  const title = item.title || item.artists.map((a) => a.name).join(", ");
  return (
    <div className="programme-item">
      <div className="programme-date" aria-label={item.date}>
        <span className="programme-wd">{fmtWeekdayShort(item.date)}</span>
        <strong>{Number(item.date.slice(8, 10))}</strong>
        <span className="programme-mon">{fmtMonthShort(item.date)}</span>
      </div>
      <div className="programme-main">
        <strong className="programme-title">{title}</strong>
        <span className="programme-meta muted small">
          {time && <span>{time} Uhr</span>}
          {item.category && <Badge>{item.category}</Badge>}
          {STATUS_LABELS[item.status] && <Badge tone="warning">{STATUS_LABELS[item.status]}</Badge>}
          {tickets && (
            <a href={tickets} target="_blank" rel="noopener noreferrer nofollow">
              <Ticket size={12} /> Tickets
            </a>
          )}
          {url && url !== tickets && (
            <a href={url} target="_blank" rel="noopener noreferrer nofollow">
              Details <ExternalLink size={11} />
            </a>
          )}
        </span>
        {item.artists.length > 0 && (
          <span className="programme-artists">
            {item.artists.map((a) => (
              <ArtistAction key={a.name} a={a} venueId={venueId} />
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

function pendingText(data: VenueProgramme): string {
  const page = data.sources.some((s) => s.provider !== "ticketmaster_venue");
  const tm = data.sources.some((s) => s.provider === "ticketmaster_venue");
  if (page && tm) return "Die Programmseite und Ticketmaster werden gerade durchsucht";
  return tm ? "Ticketmaster wird gerade durchsucht" : "Die Programmseite wird gerade durchsucht";
}

function SourcesLine({ data }: { data: VenueProgramme }) {
  if (!data.sources.length) return null;
  return (
    <span className="programme-sources muted small">
      {data.sources.map((s) => (
        <span key={s.id} title={s.message ?? undefined}>
          {SOURCE_LABELS[s.provider] ?? s.label}:{s.programme_at ? `${s.count ?? 0} Einträge · ${fmtRelative(s.programme_at)}` : "noch nicht abgerufen"}
          {s.status === "error" && " · Fehler"}
        </span>
      ))}
    </span>
  );
}

export function ProgrammeApp({ win }: AppProps) {
  const venueId = Number(win.params.venueId);
  const q = useVenueProgramme(venueId);
  const [search, setSearch] = useState("");
  const data = q.data;

  const filtered = useMemo(() => {
    const items = data?.items ?? [];
    const needle = normalizeSearch(search);
    if (!needle) return items;
    return items.filter((it) =>
      normalizeSearch([it.title, it.category, ...it.artists.map((a) => a.name)].filter(Boolean).join(" ")).includes(needle),
    );
  }, [data, search]);

  const months = useMemo(() => {
    const out: { key: string; items: ProgrammeItem[] }[] = [];
    for (const it of filtered) {
      const key = it.date.slice(0, 7);
      if (out.length && out[out.length - 1].key === key) out[out.length - 1].items.push(it);
      else out.push({ key, items: [it] });
    }
    return out;
  }, [filtered]);

  if (q.isLoading) return <Loading label="Programm wird geladen …" />;
  if (q.error || !data) return <ErrorView error={q.error} retry={() => q.refetch()} />;
  const v = data.venue;

  return (
    <div className="app-scroll stack">
      <Card
        icon={<BookOpen size={16} />}
        title={`Programm · ${v.name}`}
        subtitle={[v.city_name, v.country_name].filter(Boolean).join(" · ") + " – alle angekündigten Termine, egal welcher Künstler."}
        actions={<Button size="sm" variant="subtle" icon={<RefreshCw size={14} />} onClick={() => q.refetch()} loading={q.isFetching && !data.pending}>Aktualisieren</Button>}
      >
        <SourcesLine data={data} />
      </Card>
      {data.pending && (
        <InfoBar tone="info" title="Programm wird abgerufen" action={<Spinner size={16} />}>
          {pendingText(data)} – die Liste füllt sich gleich.
        </InfoBar>
      )}
      {!v.is_favorite && !data.pending && data.sources.length > 0 && (
        <InfoBar tone="info" title="Ort nicht ausgewählt">
          Das Programm wird noch 14 Tage nach dem letzten Öffnen aktualisiert. Wählst du den Ort aus, bleibt es dauerhaft aktuell.
        </InfoBar>
      )}
      {!data.sources.length && (
        <InfoBar tone="warning" title="Keine Programm-Quelle">
          Für diesen Ort ist weder eine Programmseite hinterlegt noch ein Ticketmaster-Schlüssel eingerichtet.
        </InfoBar>
      )}
      {data.items.length > 0 && (
        <SearchBox value={search} onChange={setSearch} placeholder="Im Programm suchen – Künstler, Titel, Kategorie" />
      )}
      <Card padded={false} className="programme-card">
        {!data.items.length && !data.pending && (
          <EmptyState compact icon={<BookOpen size={26} />} title="Keine kommenden Termine gefunden"
            text="Sobald die Quellen dieses Ortes Termine liefern, erscheinen sie hier." />
        )}
        {data.items.length > 0 && !filtered.length && <EmptyState compact title="Nichts gefunden" />}
        {months.map((m) => (
          <section key={m.key} className="programme-month">
            <h3 className="programme-month-title">
              {fmtMonthYear(`${m.key}-01`)} <span className="muted small">{m.items.length}</span>
            </h3>
            {m.items.map((it) => (
              <ProgrammeRow key={it.key} item={it} venueId={venueId} />
            ))}
          </section>
        ))}
      </Card>
    </div>
  );
}
