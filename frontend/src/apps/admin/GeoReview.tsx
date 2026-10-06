// Admin: cities/venues created automatically by the crawler that need a region/city assignment.
import { useState } from "react";
import { Check, MapPin } from "lucide-react";
import { api } from "../../api/client";
import type { City, Venue } from "../../api/types";
import { useRegions } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, ErrorView, Loading, Select } from "../../components/ui";
import { fmtNumber } from "../../lib/format";
import { useAdminAction, useAdminGeoReview } from "./hooks";

function CityReviewRow({ city }: { city: City }) {
  const regions = useRegions(city.country_id);
  const [regionId, setRegionId] = useState(city.region_id ? String(city.region_id) : "");
  const save = useAdminAction(
    () => api.patch(`/api/cities/${city.id}`, regionId ? { region_id: Number(regionId) } : { needs_review: false }),
    `${city.name} gespeichert`,
  );
  return (
    <div className="review-row">
      <MapPin size={16} />
      <span className="review-text">
        <strong>{city.name}</strong>
        <span className="muted">
          {city.country_name}
          {city.region_name ? ` · ${city.region_name}` : " · keine Region"}
          {city.population ? ` · ${fmtNumber(city.population)} Einw.` : ""}
          {city.is_auto ? " · vom Crawler angelegt" : " · von Benutzer angelegt"}
        </span>
      </span>
      <Select
        aria-label="Region"
        value={regionId}
        onChange={setRegionId}
        options={[{ value: "", label: "– Region wählen –" }, ...(regions.data ?? []).map((r) => ({ value: String(r.id), label: r.name }))]}
      />
      <Button size="sm" variant="accent" icon={<Check size={14} />} loading={save.isPending} onClick={() => save.mutate()}>
        {regionId ? "Zuordnen" : "Als geprüft markieren"}
      </Button>
    </div>
  );
}

function VenueReviewRow({ venue }: { venue: Venue }) {
  const save = useAdminAction(() => api.patch(`/api/venues/${venue.id}`, { needs_review: false }), `${venue.name} als geprüft markiert`);
  return (
    <div className="review-row">
      <MapPin size={16} />
      <span className="review-text">
        <strong>{venue.name}</strong>
        <span className="muted">{[venue.city_name, venue.region_name, venue.country_name].filter(Boolean).join(" · ") || "Ort unbekannt"}</span>
      </span>
      {venue.is_auto && <Badge tone="info">automatisch</Badge>}
      <Button size="sm" icon={<Check size={14} />} loading={save.isPending} onClick={() => save.mutate()}>
        Geprüft
      </Button>
    </div>
  );
}

export function GeoReviewSection() {
  const { data, isLoading, error, refetch } = useAdminGeoReview();
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorView error={error} retry={refetch} />;
  return (
    <div className="stack">
      <Card title={`Städte ohne sichere Zuordnung (${data.cities.length})`} subtitle="Erst mit Region greifen Regionsfilter wie „Saarland komplett“ zuverlässig.">
        {!data.cities.length && <EmptyState compact title="Nichts zu prüfen" />}
        {data.cities.map((c) => (
          <CityReviewRow key={c.id} city={c} />
        ))}
      </Card>
      <Card title={`Veranstaltungsorte zur Prüfung (${data.venues.length})`}>
        {!data.venues.length && <EmptyState compact title="Nichts zu prüfen" />}
        {data.venues.map((v) => (
          <VenueReviewRow key={v.id} venue={v} />
        ))}
      </Card>
    </div>
  );
}
