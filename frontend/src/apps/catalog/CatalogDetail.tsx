// Künstlerkatalog: Karteikarte mit Details, „Hinzufügen“ und „Abbrechen“ (beide schließen nur die Karte).
import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, Plus } from "lucide-react";
import { api, errorMessage } from "../../api/client";
import { useCatalogDetail, useInvalidateArtistData } from "../../api/hooks";
import type { Artist, CatalogEntry } from "../../api/types";
import { useSession } from "../../auth/session";
import { Button, Spinner } from "../../components/ui";
import { toast } from "../../state/ui";
import { EntryImage, countryName, kindLabel, yearsLabel } from "./catalogFormat";

interface Props {
  entry: CatalogEntry;
  onClose(): void;
}

export function CatalogDetailCard({ entry, onClose }: Props) {
  const { readOnly } = useSession();
  const detail = useCatalogDetail(entry.mbid);
  const qc = useQueryClient();
  const invalidate = useInvalidateArtistData();
  const card = useRef<HTMLDivElement>(null);
  const d = detail.data;
  const followed = d?.followed ?? entry.followed;

  useEffect(() => {
    const t = window.setTimeout(() => card.current?.querySelector<HTMLElement>(".cat-detail-add, .cat-detail-cancel")?.focus(), 30);
    return () => window.clearTimeout(t);
  }, []);

  const add = useMutation({
    mutationFn: async () => {
      const payload = {
        name: entry.name,
        musicbrainz_id: entry.mbid,
        genre: entry.genres[0] ?? null,
        official_website: d?.website ?? null,
      };
      try {
        return await api.post<Artist>("/api/artists", payload);
      } catch (e) {
        // eine Website, die TourDesk nicht akzeptiert, soll das Hinzufügen nicht verhindern
        if (payload.official_website && /website/i.test(errorMessage(e))) {
          return api.post<Artist>("/api/artists", { ...payload, official_website: null });
        }
        throw e;
      }
    },
    onSuccess: (artist) => {
      toast(`${artist.name} wird jetzt überwacht – die Suche nach Terminen läuft.`, "success");
      invalidate();
      qc.invalidateQueries({ queryKey: ["catalog"] });
      onClose();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });

  const facts = [kindLabel(entry.kind), countryName(entry.country), yearsLabel(entry)].filter(Boolean) as string[];
  const extraTags = (d?.tags ?? []).filter((t) => !entry.genres.some((g) => g.toLowerCase() === t)).slice(0, 4);

  return (
    <div className="cat-detail-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={card} className="cat-detail" role="dialog" aria-modal="true" aria-label={`${entry.name} – Details`}>
        <div className="cat-detail-head">
          <EntryImage entry={entry} className="cat-detail-photo" />
          <div className="cat-detail-title">
            <h2>{entry.name}</h2>
            {entry.disambiguation && <p className="cat-detail-disamb">{entry.disambiguation}</p>}
            {facts.length > 0 && <p className="cat-detail-facts">{facts.join(" · ")}</p>}
            <div className="cat-detail-genres">
              {entry.genres.map((g) => (
                <span key={g} className="cat-chip">
                  {g}
                </span>
              ))}
              {extraTags.map((t) => (
                <span key={t} className="cat-chip cat-chip-tag">
                  {t}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="cat-detail-body">
          {detail.isLoading ? (
            <div className="cat-detail-loading">
              <Spinner size={16} label="Beschreibung wird geladen …" />
            </div>
          ) : d?.description ? (
            <p className="cat-detail-desc">
              {d.description}
              {d.wikipedia_url && (
                <>
                  {" "}
                  <a href={d.wikipedia_url} target="_blank" rel="noopener noreferrer" className="cat-detail-source">
                    Wikipedia{d.description_lang === "en" ? " (englisch)" : ""}
                  </a>
                </>
              )}
            </p>
          ) : (
            <p className="cat-detail-desc is-empty">Keine Kurzbeschreibung gefunden.</p>
          )}
          <div className="cat-detail-links">
            {d?.website && (
              <a href={d.website} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} /> Offizielle Website
              </a>
            )}
            {d?.wikipedia_url && (
              <a href={d.wikipedia_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} /> Wikipedia
              </a>
            )}
            <a href={d?.musicbrainz_url ?? `https://musicbrainz.org/artist/${entry.mbid}`} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={14} /> MusicBrainz
            </a>
          </div>
          {d?.image_credit && (
            <p className="cat-detail-credit">
              Bild:{" "}
              <a href={d.image_credit} target="_blank" rel="noopener noreferrer">
                Wikimedia Commons
              </a>{" "}
              (Urheber und Lizenz auf der Dateiseite)
            </p>
          )}
          {d?.website && !followed && <p className="cat-detail-hint">Die offizielle Website wird beim Hinzufügen gleich als Tourquelle eingetragen.</p>}
        </div>

        <div className="cat-detail-foot">
          <Button className="cat-detail-cancel" onClick={onClose}>
            Abbrechen
          </Button>
          {followed ? (
            <Button variant="accent" icon={<Check size={16} />} disabled>
              Bereits überwacht
            </Button>
          ) : (
            <Button
              className="cat-detail-add"
              variant="accent"
              icon={<Plus size={16} />}
              loading={add.isPending}
              disabled={readOnly || add.isPending}
              onClick={() => add.mutate()}
            >
              Hinzufügen
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
