// App registry: titles, icons and components for every window type.
import { lazy, type ComponentType } from "react";
import { Building2, CalendarDays, Map, Mic2, Settings, ShieldCheck, SlidersHorizontal, Ticket, type LucideIcon } from "lucide-react";
import type { AppKind, WindowState } from "../state/windows";
import { ArtistApp } from "./ArtistApp";
import { EventApp } from "./EventApp";
import { ArtistsApp } from "./ArtistsApp";
import { AgendaApp } from "./AgendaApp";
import { FiltersApp } from "./FiltersApp";
import { PlacesApp } from "./PlacesApp";
import { VenuesApp } from "./VenuesApp";
import { SettingsApp } from "./SettingsApp";
import { cx } from "../components/ui";

const AdminApp = lazy(() => import("./admin/AdminApp"));

export interface AppProps {
  win: WindowState;
}

export interface AppDef {
  title: string;
  icon: LucideIcon;
  tone: string;
  component: ComponentType<AppProps>;
}

export const APPS: Record<AppKind, AppDef> = {
  artist: { title: "Künstler", icon: Mic2, tone: "violet", component: ArtistApp },
  event: { title: "Termin", icon: Ticket, tone: "pink", component: EventApp },
  artists: { title: "Künstler", icon: Mic2, tone: "violet", component: ArtistsApp },
  agenda: { title: "Termine", icon: CalendarDays, tone: "blue", component: AgendaApp },
  filters: { title: "Filter", icon: SlidersHorizontal, tone: "teal", component: FiltersApp },
  places: { title: "Orte", icon: Map, tone: "green", component: PlacesApp },
  venues: { title: "Veranstaltungsorte", icon: Building2, tone: "orange", component: VenuesApp },
  settings: { title: "Einstellungen", icon: Settings, tone: "slate", component: SettingsApp },
  admin: { title: "Administration", icon: ShieldCheck, tone: "red", component: AdminApp },
};

export function AppIcon({ kind, size = 32, className }: { kind: AppKind; size?: number; className?: string }) {
  const def = APPS[kind];
  const Icon = def.icon;
  return (
    <span className={cx("app-icon", `tone-${def.tone}`, className)} style={{ width: size, height: size }} aria-hidden>
      <Icon size={Math.round(size * 0.56)} strokeWidth={2} />
    </span>
  );
}
