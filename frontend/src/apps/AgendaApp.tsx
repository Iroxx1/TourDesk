// "Termine": all matching events (or all events of the followed artists) as an agenda.
import { useEffect, useState } from "react";
import { CalendarDays, X } from "lucide-react";
import type { TourEvent } from "../api/types";
import { useEvents } from "../api/hooks";
import { EventList } from "../components/EventRow";
import { Button, EmptyState, ErrorView, Loading, SearchBox, Segmented, Select, Spinner } from "../components/ui";
import { fmtDate, pluralize } from "../lib/format";
import type { AppProps } from "./registry";

const PAGE = 100;
type Scope = "matching" | "all";

export function AgendaApp({ win }: AppProps) {
  const p = win.params;
  const [scope, setScope] = useState<Scope>((p.scope as Scope) || "matching");
  const [q, setQ] = useState(String(p.q ?? ""));
  const [type, setType] = useState("");
  const [range, setRange] = useState<{ from: string | null; to: string | null }>({ from: (p.date_from as string) ?? null, to: (p.date_to as string) ?? null });
  const [limit, setLimit] = useState(PAGE);
  const [debounced, setDebounced] = useState(q);

  // re-opened from search / calendar with new parameters
  useEffect(() => {
    if (win.nonce === 0) return;
    setScope((p.scope as Scope) || "matching");
    setQ(String(p.q ?? ""));
    setDebounced(String(p.q ?? ""));
    setRange({ from: (p.date_from as string) ?? null, to: (p.date_to as string) ?? null });
    setLimit(PAGE);
  }, [win.nonce]);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const { data, isLoading, isFetching, error, refetch } = useEvents({
    scope,
    q: debounced.trim(),
    event_type: type || undefined,
    date_from: range.from ?? undefined,
    date_to: range.to ?? undefined,
    limit: Math.min(limit, 200),
  });
  const items: TourEvent[] = data?.items ?? [];

  return (
    <div className="agenda-app">
      <div className="toolbar">
        <Segmented<Scope>
          label="Umfang"
          value={scope}
          onChange={(v) => {
            setScope(v);
            setLimit(PAGE);
          }}
          options={[
            { value: "matching", label: "Meine Termine" },
            { value: "all", label: "Alle Termine meiner Künstler" },
          ]}
        />
        <SearchBox value={q} onChange={setQ} placeholder="Ort, Stadt oder Titel suchen" className="toolbar-grow" />
        <Select
          aria-label="Art"
          value={type}
          onChange={setType}
          options={[
            { value: "", label: "Alle Arten" },
            { value: "concert", label: "Konzerte" },
            { value: "festival", label: "Festivals" },
            { value: "support", label: "Support-Acts" },
            { value: "special", label: "Special Events" },
          ]}
        />
      </div>
      {(range.from || range.to) && (
        <div className="filter-chip-row">
          <span className="chip">
            {range.from === range.to ? fmtDate(range.from) : `${fmtDate(range.from)} – ${fmtDate(range.to)}`}
            <button type="button" aria-label="Zeitraum entfernen" onClick={() => setRange({ from: null, to: null })}>
              <X size={12} />
            </button>
          </span>
        </div>
      )}
      <div className="agenda-summary muted">
        {data ? pluralize(data.total, "Termin", "Termine") : " "}
        {isFetching && !isLoading && <Spinner size={14} />}
      </div>
      <div className="agenda-list">
        {isLoading && <Loading />}
        {error && <ErrorView error={error} retry={refetch} />}
        {data && (
          <EventList
            events={items}
            showArtist
            empty={
              <EmptyState
                icon={<CalendarDays size={28} />}
                title="Keine Termine gefunden"
                text={scope === "matching" ? "Es gibt aktuell keine Termine, die zu deinen Filtern passen." : "Für deine Künstler sind keine Termine bekannt."}
                action={scope === "matching" ? <Button onClick={() => setScope("all")}>Alle Termine anzeigen</Button> : undefined}
              />
            }
          />
        )}
        {data && data.total > items.length && limit < 200 && (
          <div className="load-more">
            <Button onClick={() => setLimit(200)} loading={isFetching}>
              Weitere Termine laden
            </Button>
          </div>
        )}
        {data && data.total > 200 && limit >= 200 && <p className="muted small center">Es werden die ersten 200 Termine angezeigt – grenze die Suche ein, um weitere zu sehen.</p>}
      </div>
    </div>
  );
}
