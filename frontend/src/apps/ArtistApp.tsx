// Artist window: hero image, tour status, festival switch, matching dates, full tour, sources, editing.
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CalendarRange,
  ExternalLink,
  History,
  ImageUp,
  Link2,
  ListMusic,
  Pencil,
  Pin,
  Plus,
  RefreshCw,
  Trash2,
  Wand2,
} from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Artist, Source } from "../api/types";
import { useArtist, useArtistEvents, useArtistSources, useInvalidateArtistData, useUpdateArtist } from "../api/hooks";
import { useSession } from "../auth/session";
import { ArtistImage } from "../components/ArtistImage";
import { CrawlStatusBadge, SourceStatusBadge, TourStatusPill } from "../components/badges";
import { EventList } from "../components/EventRow";
import {
  Badge,
  Button,
  Card,
  ChipInput,
  EmptyState,
  ErrorView,
  IconButton,
  InfoBar,
  LinkButton,
  Loading,
  Select,
  Tabs,
  TextField,
  Toggle,
} from "../components/ui";
import { fmtDateRange, fmtDateTime, fmtRelative, pluralize } from "../lib/format";
import { safeHref, hostOf } from "../lib/urls";
import { confirmDialog, toast } from "../state/ui";
import { useWindows } from "../state/windows";
import type { AppProps } from "./registry";

type Tab = "mine" | "tour" | "past" | "sources" | "edit";

const PROVIDER_LABELS: Record<string, string> = {
  tour_page: "Tourseite (offiziell)",
  ical_feed: "iCal-Feed",
  generic_web: "Sonstige Webseite",
};

function SourcesTab({ artistId }: { artistId: number }) {
  const { data, isLoading, error, refetch } = useArtistSources(artistId);
  const { readOnly } = useSession();
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [provider, setProvider] = useState("tour_page");
  const add = useMutation({
    mutationFn: () => api.post<Source>(`/api/artists/${artistId}/sources`, { url: url.trim(), provider }),
    onSuccess: () => {
      setUrl("");
      toast("Quelle hinzugefügt – wird gleich gecrawlt.", "success");
      qc.invalidateQueries({ queryKey: ["artist", artistId] });
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/api/artists/${artistId}/sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artist", artistId] }),
    onError: (e) => toast(errorMessage(e), "error"),
  });
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorView error={error} retry={refetch} />;

  const row = (s: Source, deletable: boolean) => {
    const href = safeHref(s.url);
    return (
      <div key={s.id} className="source-row">
        <div className="source-main">
          <div className="source-title">
            <strong>{s.name}</strong>
            <SourceStatusBadge status={s.is_enabled ? s.status : "disabled"} />
          </div>
          <div className="source-meta">
            <span>{s.provider_label}</span>
            <span>· Vertrauen {s.trust_level}: {s.trust_label}</span>
            {href && (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                · {hostOf(href)} <ExternalLink size={11} />
              </a>
            )}
          </div>
          <div className="source-meta">
            <span>Zuletzt erfolgreich: {s.last_success_at ? fmtRelative(s.last_success_at) : "noch nie"}</span>
            {s.last_event_count !== null && <span>· {pluralize(s.last_event_count, "Termin", "Termine")} gefunden</span>}
          </div>
          {s.status === "error" && s.last_error && (
            <div className="source-error">
              {s.last_error}
              {s.next_attempt_at && <span> · Nächster Versuch {fmtRelative(s.next_attempt_at)}</span>}
            </div>
          )}
        </div>
        {deletable && s.can_delete && (
          <IconButton
            label="Quelle entfernen"
            icon={<Trash2 size={16} />}
            disabled={readOnly}
            onClick={async () => {
              if (await confirmDialog({ title: "Quelle entfernen?", message: s.url ?? s.name, confirmLabel: "Entfernen", danger: true })) remove.mutate(s.id);
            }}
          />
        )}
      </div>
    );
  };

  return (
    <div className="stack">
      <Card title="Quellen dieses Künstlers" subtitle="Offizielle Website, Tourseiten, APIs und eigene Quellen. Niedrigere Vertrauensstufe = vertrauenswürdiger.">
        {data.sources.length ? data.sources.map((s) => row(s, true)) : <EmptyState compact title="Noch keine eigenen Quellen" text="TourDesk sucht automatisch nach der offiziellen Website und Tourseiten." />}
      </Card>
      {data.contributing.length > 0 && (
        <Card title="Weitere Quellen mit Terminen" subtitle="Veranstaltungsorte, Festivals und Ticketseiten, die Termine dieses Künstlers listen.">
          {data.contributing.map((s) => row(s, false))}
        </Card>
      )}
      <Card title="Quelle hinzufügen" subtitle="Zum Beispiel die Tourseite der Band oder ein öffentlicher iCal-Kalender.">
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (url.trim()) add.mutate();
          }}
        >
          <TextField label="URL" type="url" placeholder="https://www.band.de/tour" value={url} onChange={(e) => setUrl(e.target.value)} disabled={readOnly} required />
          <Select
            label="Art der Quelle"
            value={provider}
            onChange={setProvider}
            options={data.addable_providers.map((p) => ({ value: p, label: PROVIDER_LABELS[p] ?? p }))}
            disabled={readOnly}
          />
          <Button type="submit" variant="accent" icon={<Plus size={16} />} loading={add.isPending} disabled={readOnly || !url.trim()}>
            Hinzufügen
          </Button>
        </form>
      </Card>
    </div>
  );
}

function EditTab({ artist, onSaved }: { artist: Artist; onSaved(): void }) {
  const { readOnly } = useSession();
  const update = useUpdateArtist(artist.id);
  const invalidate = useInvalidateArtistData();
  const [name, setName] = useState(artist.name);
  const [genre, setGenre] = useState(artist.genre ?? "");
  const [website, setWebsite] = useState(artist.official_website ?? "");
  const [aliases, setAliases] = useState<string[]>(artist.aliases);
  const [terms, setTerms] = useState<string[]>(artist.search_terms);
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => api.upload<Artist>(`/api/artists/${artist.id}/image`, file),
    onSuccess: () => {
      toast("Bild gespeichert", "success");
      invalidate(artist.id);
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const refreshImage = useMutation({
    mutationFn: () => api.post(`/api/artists/${artist.id}/image/refresh`),
    onSuccess: () => toast("Bildsuche eingeplant – das Bild wird in Kürze aktualisiert.", "success"),
    onError: (e) => toast(errorMessage(e), "error"),
  });

  const save = () =>
    update.mutate(
      { name: name.trim(), genre: genre.trim() || null, official_website: website.trim() || null, aliases, search_terms: terms },
      {
        onSuccess: () => {
          toast("Gespeichert – die Quellen werden neu durchsucht.", "success");
          onSaved();
        },
        onError: (e) => toast(errorMessage(e), "error"),
      },
    );

  return (
    <div className="stack">
      <Card title="Künstlerdaten" subtitle="Diese Angaben gelten für alle Benutzer, die diesen Künstler überwachen.">
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} disabled={readOnly} />
          <TextField label="Genre" value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="z. B. Pop, Metal" maxLength={100} disabled={readOnly} />
          <TextField
            label="Offizielle Website"
            type="url"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="https://"
            hint="Wird als vertrauenswürdigste Quelle (Stufe 1) gecrawlt."
            disabled={readOnly}
            className="span-2"
          />
          <ChipInput label="Alternative Namen" values={aliases} onChange={setAliases} placeholder="z. B. BSB – Enter drücken" hint="Hilft beim Erkennen der Termine auf fremden Seiten." disabled={readOnly} />
          <ChipInput label="Bevorzugte Suchbegriffe" values={terms} onChange={setTerms} placeholder="z. B. DNA World Tour" hint="Zusätzliche Begriffe für die Suche in Quellen." disabled={readOnly} />
          <div className="form-actions span-2">
            <Button type="submit" variant="accent" loading={update.isPending} disabled={readOnly || !name.trim()}>
              Speichern
            </Button>
          </div>
        </form>
      </Card>
      <Card title="Künstlerbild" subtitle={artist.images.source ? `Aktuelle Quelle: ${artist.images.source}` : "Noch kein Bild gefunden"}>
        <div className="image-edit">
          <ArtistImage artist={artist} variant="tile" className="image-edit-preview" />
          <div className="stack-sm">
            <p className="muted">TourDesk sucht automatisch zuerst auf der offiziellen Website, dann bei zuverlässigen öffentlichen Quellen (Wikidata, Deezer). Bilder werden lokal zwischengespeichert.</p>
            <div className="button-row">
              <Button icon={<Wand2 size={16} />} loading={refreshImage.isPending} disabled={readOnly} onClick={() => refreshImage.mutate()}>
                Automatisch suchen
              </Button>
              <Button icon={<ImageUp size={16} />} loading={upload.isPending} disabled={readOnly} onClick={() => fileRef.current?.click()}>
                Eigenes Bild hochladen
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload.mutate(f);
                  e.target.value = "";
                }}
              />
            </div>
            {artist.images.source_url && safeHref(artist.images.source_url) && (
              <a className="muted small" href={safeHref(artist.images.source_url)} target="_blank" rel="noopener noreferrer nofollow">
                Bildquelle: {hostOf(artist.images.source_url)}
              </a>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

export function ArtistApp({ win }: AppProps) {
  const artistId = Number(win.params.artistId);
  const { data: artist, error, refetch, isLoading } = useArtist(artistId);
  const events = useArtistEvents(artistId);
  const update = useUpdateArtist(artistId);
  const invalidate = useInvalidateArtistData();
  const { readOnly } = useSession();
  const [tab, setTab] = useState<Tab>("mine");

  useEffect(() => {
    if (artist) useWindows.getState().setMeta(win.id, { title: artist.name, icon: artist.images.thumb });
  }, [artist, win.id]);

  const refresh = useMutation({
    mutationFn: () => api.post(`/api/artists/${artistId}/refresh`),
    onSuccess: () => {
      toast("Aktualisierung gestartet – neue Termine erscheinen automatisch.", "success");
      invalidate(artistId);
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const unfollow = useMutation({
    mutationFn: () => api.del(`/api/artists/${artistId}`),
    onSuccess: () => {
      toast(`${artist?.name ?? "Künstler"} entfernt`, "success");
      useWindows.getState().close(win.id);
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });

  const sub = artist?.subscription;
  const toggle = (patch: Record<string, unknown>, message: string) =>
    update.mutate(patch, { onSuccess: () => toast(message, "success"), onError: (e) => toast(errorMessage(e), "error") });

  if (isLoading) return <Loading />;
  if (error || !artist) return <ErrorView error={error} retry={refetch} />;

  const status = events.data?.tour_status;
  const website = safeHref(artist.official_website);
  const allEvents = events.data?.all_events ?? [];
  const outside = allEvents.filter((e) => e.matches === false).length;

  return (
    <div className="artist-app">
      <header className="artist-hero">
        <ArtistImage artist={artist} variant="hero" className={artist.images.source === "fallback" ? "artist-hero-img is-placeholder" : "artist-hero-img"} />
        <div className="artist-hero-shade" />
        <div className="artist-hero-content">
          <div className="artist-hero-text">
            {artist.genre && <div className="artist-hero-genre">{artist.genre}</div>}
            <h2 className="artist-hero-name">{artist.name}</h2>
            {status && (
              <div className="artist-hero-status">
                <TourStatusPill status={status} />
                {status.tour_name && <span className="artist-hero-tour">{status.tour_name}</span>}
                {status.start_date && <span className="artist-hero-dates">{fmtDateRange(status.start_date, status.end_date)}</span>}
              </div>
            )}
            {status?.detail && <div className="artist-hero-detail">{status.detail}</div>}
          </div>
          <div className="artist-hero-actions">
            {website && (
              <LinkButton href={website} icon={<Link2 size={16} />} size="sm">
                Website
              </LinkButton>
            )}
            <Button size="sm" icon={<RefreshCw size={16} />} loading={refresh.isPending} disabled={readOnly} onClick={() => refresh.mutate()}>
              Jetzt aktualisieren
            </Button>
          </div>
        </div>
      </header>

      <div className="artist-switches">
        <Toggle
          label="Festivals anzeigen"
          description={sub?.show_festivals ? "Bestätigte Festivalauftritte werden angezeigt" : "Nur normale Konzerte und Tourtermine"}
          checked={Boolean(sub?.show_festivals)}
          disabled={readOnly || update.isPending}
          onChange={(v) => toggle({ show_festivals: v }, v ? "Festivals werden angezeigt" : "Festivals ausgeblendet")}
        />
        <Toggle
          label="Überwachung aktiv"
          description={sub?.is_active ? "Termine werden angezeigt und regelmäßig aktualisiert" : "Pausiert – keine Anzeige"}
          checked={Boolean(sub?.is_active)}
          disabled={readOnly || update.isPending}
          onChange={(v) => toggle({ is_active: v }, v ? "Überwachung aktiviert" : "Überwachung pausiert")}
        />
        <div className="artist-meta">
          <CrawlStatusBadge status={artist.crawl_status} />
          <span title={fmtDateTime(artist.last_success_at)}>Zuletzt aktualisiert: {fmtRelative(artist.last_success_at)}</span>
          {artist.next_crawl_at && <span>· Nächste Prüfung {fmtRelative(artist.next_crawl_at)}</span>}
          <span className="artist-meta-icons">
            <IconButton
              size="sm"
              label={sub?.notify ? "Benachrichtigungen aus" : "Benachrichtigungen an"}
              active={sub?.notify}
              icon={<Bell size={15} />}
              disabled={readOnly}
              onClick={() => toggle({ notify: !sub?.notify }, sub?.notify ? "Benachrichtigungen deaktiviert" : "Benachrichtigungen aktiviert")}
            />
            <IconButton
              size="sm"
              label={sub?.pinned ? "Nicht mehr anheften" : "Anheften"}
              active={sub?.pinned}
              icon={<Pin size={15} />}
              disabled={readOnly}
              onClick={() => toggle({ pinned: !sub?.pinned }, sub?.pinned ? "Nicht mehr angeheftet" : "Angeheftet")}
            />
          </span>
        </div>
      </div>

      {artist.crawl_status === "error" && artist.last_error && (
        <InfoBar tone="warning" title="Beim letzten Crawl gab es Probleme.">
          {artist.last_error}
        </InfoBar>
      )}

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        className="artist-tabs"
        tabs={[
          { id: "mine", label: "Meine Termine", icon: <CalendarRange size={15} />, count: events.data?.matching.length ?? null },
          { id: "tour", label: "Gesamte Tour", icon: <ListMusic size={15} />, count: allEvents.length || null },
          { id: "past", label: "Vergangen", icon: <History size={15} /> },
          { id: "sources", label: "Quellen", icon: <Link2 size={15} /> },
          { id: "edit", label: "Bearbeiten", icon: <Pencil size={15} /> },
        ]}
      />

      <div className="artist-tab-body">
        {(tab === "mine" || tab === "tour" || tab === "past") && events.isLoading && <Loading />}
        {(tab === "mine" || tab === "tour" || tab === "past") && events.error && <ErrorView error={events.error} retry={events.refetch} />}
        {tab === "mine" && events.data && (
          <EventList
            events={events.data.matching}
            empty={
              <EmptyState
                icon={<CalendarRange size={28} />}
                title="Keine passenden Termine"
                text={
                  allEvents.length
                    ? `${pluralize(allEvents.length, "Termin ist", "Termine sind")} bekannt, aber keiner passt zu deinen Filtern.`
                    : artist.crawl_status === "pending"
                      ? "Die Quellen werden gerade zum ersten Mal durchsucht …"
                      : "Derzeit sind keine bevorstehenden Termine bekannt."
                }
                action={allEvents.length ? <Button onClick={() => setTab("tour")}>Gesamte Tour anzeigen</Button> : undefined}
              />
            }
          />
        )}
        {tab === "tour" && events.data && (
          <>
            {allEvents.length > 0 && (
              <div className="tour-legend">
                <span className="legend legend-match">passend</span>
                <span className="legend legend-outside">außerhalb deiner Filter{outside ? ` (${outside})` : ""}</span>
                <span className="legend legend-festival">Festival</span>
                <span className="legend legend-cancelled">abgesagt / verschoben</span>
              </div>
            )}
            {events.data.tours.length > 0 && (
              <div className="tour-names">
                {events.data.tours.map((t) => (
                  <Badge key={t.id} tone="accent">
                    {t.name}
                  </Badge>
                ))}
              </div>
            )}
            <EventList events={allEvents} empty={<EmptyState title="Keine bevorstehenden Termine bekannt" />} />
          </>
        )}
        {tab === "past" && events.data && (
          <EventList events={[...events.data.past_events].reverse()} empty={<EmptyState title="Keine vergangenen Termine im letzten Jahr" />} />
        )}
        {tab === "sources" && <SourcesTab artistId={artistId} />}
        {tab === "edit" && (
          <>
            <EditTab artist={artist} onSaved={() => setTab("sources")} />
            <Card title="Künstler entfernen" className="danger-zone">
              <div className="danger-row">
                <span>Entfernt {artist.name} aus deiner Liste. Andere Benutzer sind nicht betroffen.</span>
                <Button
                  variant="danger"
                  icon={<Trash2 size={16} />}
                  disabled={readOnly}
                  loading={unfollow.isPending}
                  onClick={async () => {
                    if (await confirmDialog({ title: `${artist.name} entfernen?`, message: "Der Künstler wird nicht mehr für dich überwacht.", confirmLabel: "Entfernen", danger: true }))
                      unfollow.mutate();
                  }}
                >
                  Entfernen
                </Button>
              </div>
            </Card>
          </>
        )}
      </div>
      <div className="artist-footer">
        Zuletzt erfolgreich gecrawlt: {fmtDateTime(artist.last_success_at)} · Crawlerstatus: <CrawlStatusBadge status={artist.crawl_status} />
      </div>
    </div>
  );
}
