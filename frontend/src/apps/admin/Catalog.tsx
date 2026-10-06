// Admin: global artist catalogue (subscribers, events, crawl status) with crawl / enrich / delete.
import { useState } from "react";
import { CalendarSearch, ImagePlus, Play, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import { ArtistImage } from "../../components/ArtistImage";
import { CrawlStatusBadge } from "../../components/badges";
import { Card, EmptyState, ErrorView, IconButton, Loading, Pagination, SearchBox, Select } from "../../components/ui";
import { fmtRelative } from "../../lib/format";
import { confirmDialog } from "../../state/ui";
import type { AdminNav } from "./AdminApp";
import { useAdminAction, useAdminCatalog } from "./hooks";

export function CatalogSection({ nav }: { nav: AdminNav }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error, refetch } = useAdminCatalog({ q: q.trim(), status: status || undefined, offset, limit: 50 });
  const crawl = useAdminAction((id: number) => api.post(`/api/admin/artists/${id}/crawl`), "Crawl eingeplant");
  const enrich = useAdminAction((id: number) => api.post(`/api/admin/artists/${id}/enrich`), "Metadaten- und Bildsuche eingeplant");
  const remove = useAdminAction((id: number) => api.del<{ detail: string }>(`/api/admin/artists/${id}`), (r) => r.detail);

  return (
    <div className="stack">
      <div className="toolbar">
        <SearchBox value={q} onChange={(v) => { setQ(v); setOffset(0); }} placeholder="Künstler suchen" className="toolbar-grow" />
        <Select
          aria-label="Crawlerstatus"
          value={status}
          onChange={(v) => { setStatus(v); setOffset(0); }}
          options={[
            { value: "", label: "Alle Status" },
            { value: "ok", label: "Erfolgreich" },
            { value: "partial", label: "Teilweise" },
            { value: "error", label: "Fehler" },
            { value: "pending", label: "Wartend" },
          ]}
        />
      </div>
      {isLoading && <Loading />}
      {error && <ErrorView error={error} retry={refetch} />}
      {data && (
        <Card padded={false}>
          {!data.items.length && <EmptyState compact title="Keine Künstler" />}
          {data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Künstler</th>
                    <th>Status</th>
                    <th className="num">Abos</th>
                    <th className="num">Kommende Events</th>
                    <th>Zuletzt erfolgreich</th>
                    <th>Nächster Crawl</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <span className="cell-artist">
                          <ArtistImage artist={a} variant="thumb" className="cell-artist-img" />
                          <span>
                            <strong>{a.name}</strong>
                            <span className="muted small">{[a.genre, a.is_demo ? "Demo" : null].filter(Boolean).join(" · ")}</span>
                          </span>
                        </span>
                      </td>
                      <td>
                        <CrawlStatusBadge status={a.crawl_status} />
                        {a.last_error && <div className="muted small wrap">{a.last_error}</div>}
                      </td>
                      <td className="num">{a.subscribers ?? 0}</td>
                      <td className="num">{a.upcoming_events ?? 0}</td>
                      <td>{fmtRelative(a.last_success_at)}</td>
                      <td>{a.next_crawl_at ? fmtRelative(a.next_crawl_at) : "–"}</td>
                      <td className="row-actions">
                        <IconButton size="sm" label="Events anzeigen" icon={<CalendarSearch size={14} />} onClick={() => nav.go("events", { artistId: a.id })} />
                        <IconButton size="sm" label="Jetzt crawlen" icon={<Play size={14} />} onClick={() => crawl.mutate(a.id)} />
                        <IconButton size="sm" label="Metadaten/Bild neu suchen" icon={<ImagePlus size={14} />} onClick={() => enrich.mutate(a.id)} />
                        <IconButton
                          size="sm"
                          label="Aus Katalog löschen"
                          icon={<Trash2 size={14} />}
                          onClick={async () => {
                            if (
                              await confirmDialog({
                                title: `${a.name} aus dem Katalog löschen?`,
                                message: `Alle Events, Quellen und ${a.subscribers ?? 0} Abo(s) dieses Künstlers werden entfernt.`,
                                confirmLabel: "Endgültig löschen",
                                danger: true,
                              })
                            )
                              remove.mutate(a.id);
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination offset={offset} limit={50} total={data.total} onChange={setOffset} />
        </Card>
      )}
    </div>
  );
}
