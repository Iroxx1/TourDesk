// "Künstler": add (catalogue / MusicBrainz / manual), edit switches, reorder and remove artists.
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Globe, Mic2, Plus, Trash2, UserPlus } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Artist, LookupItem } from "../api/types";
import { qk, useArtists, useFilter, useInvalidateArtistData, useLookup, useUpdateArtist } from "../api/hooks";
import { useSession } from "../auth/session";
import { ArtistImage } from "../components/ArtistImage";
import { CrawlStatusBadge } from "../components/badges";
import { Badge, Button, Card, ChipInput, EmptyState, IconButton, Loading, SearchBox, Spinner, TextField, Toggle } from "../components/ui";
import { fmtRelative } from "../lib/format";
import { confirmDialog, toast } from "../state/ui";
import { openArtist } from "../state/windows";
import { sortedArtists } from "../desktop/Taskbar";
import type { AppProps } from "./registry";

function useDebounced(value: string, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface CreatePayload {
  name: string;
  artist_id?: number | null;
  musicbrainz_id?: string | null;
  official_website?: string | null;
  genre?: string | null;
  aliases?: string[];
  search_terms?: string[];
  show_festivals?: boolean;
}

function AddArtist({ autoFocus }: { autoFocus: boolean }) {
  const { readOnly } = useSession();
  const invalidate = useInvalidateArtistData();
  const { data: filter } = useFilter();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q);
  const catalog = useLookup(debounced, false);
  const external = useLookup(debounced, true);
  const [manual, setManual] = useState(false);
  const [form, setForm] = useState({ name: "", website: "", genre: "", aliases: [] as string[], terms: [] as string[], festivals: true });
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);
  useEffect(() => {
    if (filter) setForm((f) => ({ ...f, festivals: filter.default_show_festivals }));
  }, [filter]);

  const create = useMutation({
    mutationFn: (payload: CreatePayload) => api.post<Artist>("/api/artists", payload),
    onSuccess: (artist) => {
      toast(`${artist.name} wird jetzt überwacht – die Suche nach Terminen läuft.`, "success");
      invalidate();
      setManual(false);
      setForm((f) => ({ ...f, name: "", website: "", genre: "", aliases: [], terms: [] }));
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });

  const results: LookupItem[] = external.data ?? catalog.data ?? [];
  const searching = debounced.trim().length >= 2;

  const addItem = (item: LookupItem) =>
    create.mutate({
      name: item.name,
      artist_id: item.artist_id,
      musicbrainz_id: item.musicbrainz_id,
      genre: item.genre,
    });

  return (
    <Card title="Künstler hinzufügen" icon={<UserPlus size={16} />} subtitle="Suche im TourDesk-Katalog und bei MusicBrainz – oder lege den Künstler manuell an.">
      <SearchBox ref={input} value={q} onChange={setQ} placeholder="Name des Künstlers oder der Band" disabled={readOnly} />
      {searching && (
        <div className="lookup-results">
          {(catalog.isFetching || external.isFetching) && (
            <div className="lookup-status">
              <Spinner size={14} label={external.isFetching ? "Suche bei MusicBrainz …" : "Suche …"} />
            </div>
          )}
          {results.map((item, i) => (
            <div key={`${item.source}-${item.artist_id ?? item.musicbrainz_id ?? i}`} className="lookup-item">
              <span className="lookup-icon">{item.source === "catalog" ? <Mic2 size={16} /> : <Globe size={16} />}</span>
              <span className="lookup-text">
                <strong>{item.name}</strong>
                <span className="muted">
                  {[item.disambiguation, item.kind === "Group" ? "Band" : item.kind === "Person" ? "Künstler/in" : item.kind, item.country, item.genre].filter(Boolean).join(" · ") ||
                    (item.source === "catalog" ? "Bereits im TourDesk-Katalog" : "MusicBrainz")}
                </span>
              </span>
              <Badge tone={item.source === "catalog" ? "accent" : "neutral"}>{item.source === "catalog" ? "Katalog" : "MusicBrainz"}</Badge>
              {item.followed ? (
                <Badge tone="success">
                  <Check size={12} /> überwacht
                </Badge>
              ) : (
                <Button size="sm" variant="accent" icon={<Plus size={14} />} disabled={readOnly || create.isPending} onClick={() => addItem(item)}>
                  Hinzufügen
                </Button>
              )}
            </div>
          ))}
          {!catalog.isFetching && !external.isFetching && results.length === 0 && <div className="muted lookup-empty">Kein Treffer gefunden.</div>}
          {!manual && (
            <button
              type="button"
              className="lookup-manual"
              onClick={() => {
                setManual(true);
                setForm((f) => ({ ...f, name: q.trim() }));
              }}
            >
              Nicht dabei? „{q.trim()}“ manuell anlegen ›
            </button>
          )}
        </div>
      )}
      {!searching && !manual && (
        <button type="button" className="lookup-manual" onClick={() => setManual(true)}>
          Künstler manuell anlegen ›
        </button>
      )}
      {manual && (
        <form
          className="form-grid manual-form"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate({
              name: form.name.trim(),
              official_website: form.website.trim() || null,
              genre: form.genre.trim() || null,
              aliases: form.aliases,
              search_terms: form.terms,
              show_festivals: form.festivals,
            });
          }}
        >
          <TextField label="Name" required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
          <TextField label="Genre (optional)" value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })} />
          <TextField
            label="Offizielle Website"
            type="url"
            placeholder="https://"
            value={form.website}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
            hint="Empfohlen: Die offizielle Website ist die vertrauenswürdigste Quelle."
            className="span-2"
          />
          <ChipInput label="Alternative Namen" values={form.aliases} onChange={(aliases) => setForm({ ...form, aliases })} placeholder="Enter drücken zum Hinzufügen" />
          <ChipInput label="Bevorzugte Suchbegriffe" values={form.terms} onChange={(terms) => setForm({ ...form, terms })} placeholder="z. B. Tourname" />
          <Toggle label="Festivals anzeigen" description="Bestätigte Festivalauftritte zusätzlich anzeigen" checked={form.festivals} onChange={(festivals) => setForm({ ...form, festivals })} className="span-2" />
          <div className="form-actions span-2">
            <Button type="submit" variant="accent" loading={create.isPending} disabled={readOnly || !form.name.trim()}>
              Künstler anlegen
            </Button>
            <Button onClick={() => setManual(false)}>Abbrechen</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function ArtistRow({ artist, first, last, onMove }: { artist: Artist; first: boolean; last: boolean; onMove(dir: -1 | 1): void }) {
  const { readOnly } = useSession();
  const update = useUpdateArtist(artist.id);
  const invalidate = useInvalidateArtistData();
  const remove = useMutation({
    mutationFn: () => api.del(`/api/artists/${artist.id}`),
    onSuccess: () => {
      toast(`${artist.name} entfernt`, "success");
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const sub = artist.subscription;
  const set = (patch: Record<string, unknown>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });
  return (
    <div className="artist-row">
      <button type="button" className="artist-row-main" onClick={() => openArtist(artist.id, artist.name, artist.images.thumb)}>
        <ArtistImage artist={artist} variant="thumb" className="artist-row-img" />
        <span className="artist-row-text">
          <strong>{artist.name}</strong>
          <span className="muted">
            {artist.genre ? `${artist.genre} · ` : ""}aktualisiert {fmtRelative(artist.last_success_at)}
          </span>
        </span>
      </button>
      <CrawlStatusBadge status={artist.crawl_status} />
      <div className="artist-row-switches">
        <Toggle label="Aktiv" checked={Boolean(sub?.is_active)} disabled={readOnly} onChange={(v) => set({ is_active: v })} showState={false} />
        <Toggle label="Festivals" checked={Boolean(sub?.show_festivals)} disabled={readOnly} onChange={(v) => set({ show_festivals: v })} showState={false} />
      </div>
      <div className="artist-row-actions">
        <IconButton size="sm" label="Nach oben" icon={<ArrowUp size={14} />} disabled={readOnly || first} onClick={() => onMove(-1)} />
        <IconButton size="sm" label="Nach unten" icon={<ArrowDown size={14} />} disabled={readOnly || last} onClick={() => onMove(1)} />
        <IconButton
          size="sm"
          label={`${artist.name} entfernen`}
          icon={<Trash2 size={14} />}
          disabled={readOnly || remove.isPending}
          onClick={async () => {
            if (await confirmDialog({ title: `${artist.name} entfernen?`, message: "Der Künstler wird nicht mehr für dich überwacht.", confirmLabel: "Entfernen", danger: true })) remove.mutate();
          }}
        />
      </div>
    </div>
  );
}

export function ArtistsApp({ win }: AppProps) {
  const { data, isLoading } = useArtists();
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const list = useMemo(() => sortedArtists(data), [data]);
  const shown = filter.trim() ? list.filter((a) => a.name.toLowerCase().includes(filter.trim().toLowerCase())) : list;

  const reorder = useMutation({
    mutationFn: (ids: number[]) => api.post("/api/artists/reorder", { ids }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: qk.artists });
      qc.invalidateQueries({ queryKey: qk.dashboard });
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const move = (artist: Artist, dir: -1 | 1) => {
    const ids = list.map((a) => a.id);
    const i = ids.indexOf(artist.id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    // optimistic order
    qc.setQueryData<Artist[]>(qk.artists, (old) =>
      old?.map((a) => (a.subscription ? { ...a, subscription: { ...a.subscription, sort_order: ids.indexOf(a.id), pinned: a.subscription.pinned } } : a)),
    );
    reorder.mutate(ids);
  };

  return (
    <div className="app-scroll stack">
      <AddArtist autoFocus={Boolean(win.params.add)} />
      <Card
        title={`Meine Künstler${data ? ` (${data.length})` : ""}`}
        icon={<Mic2 size={16} />}
        actions={data && data.length > 6 ? <SearchBox value={filter} onChange={setFilter} placeholder="Filtern" /> : undefined}
        padded={false}
      >
        {isLoading && <Loading />}
        {data && !data.length && <EmptyState compact title="Noch keine Künstler" text="Suche oben nach einem Künstler oder einer Band." />}
        <div className="artist-rows">
          {shown.map((a, i) => (
            <ArtistRow key={a.id} artist={a} first={i === 0 || Boolean(filter)} last={i === shown.length - 1 || Boolean(filter)} onMove={(d) => move(a, d)} />
          ))}
        </div>
      </Card>
    </div>
  );
}
