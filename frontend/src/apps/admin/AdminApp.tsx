// Administration window – integrated into the TourDesk design (Windows-settings-like navigation).
import { useEffect, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, CalendarSearch, ChevronLeft, Cog, Database, FileText, LayoutDashboard, Link2, MapPinned, Mic2, ScrollText, Users } from "lucide-react";
import { useIsMobile } from "../../lib/useMediaQuery";
import { cx } from "../../components/ui";
import type { AppProps } from "../registry";
import { OverviewSection } from "./Overview";
import { UsersSection } from "./Users";
import { CrawlerSection, ErrorsSection } from "./Crawler";
import { SourcesSection } from "./Sources";
import { EventsSection } from "./Events";
import { CatalogSection } from "./Catalog";
import { GeoReviewSection } from "./GeoReview";
import { AuditSection, LogsSection, SystemSection } from "./System";
import { CrawlerSettingsSection } from "./CrawlerSettings";

export type AdminSection =
  | "overview"
  | "users"
  | "crawler"
  | "errors"
  | "sources"
  | "events"
  | "catalog"
  | "geo"
  | "system"
  | "logs"
  | "audit"
  | "crawler-settings";

const NAV: { id: AdminSection; label: string; icon: ReactNode }[] = [
  { id: "overview", label: "Übersicht", icon: <LayoutDashboard size={17} /> },
  { id: "users", label: "Benutzer", icon: <Users size={17} /> },
  { id: "crawler", label: "Crawler", icon: <Activity size={17} /> },
  { id: "errors", label: "Crawler-Fehler", icon: <AlertTriangle size={17} /> },
  { id: "sources", label: "Quellen", icon: <Link2 size={17} /> },
  { id: "events", label: "Events", icon: <CalendarSearch size={17} /> },
  { id: "catalog", label: "Künstler-Katalog", icon: <Mic2 size={17} /> },
  { id: "geo", label: "Orte prüfen", icon: <MapPinned size={17} /> },
  { id: "system", label: "System & Datenbank", icon: <Database size={17} /> },
  { id: "logs", label: "Logs", icon: <FileText size={17} /> },
  { id: "audit", label: "Audit-Log", icon: <ScrollText size={17} /> },
  { id: "crawler-settings", label: "Crawler-Einstellungen", icon: <Cog size={17} /> },
];

export interface AdminNav {
  go(section: AdminSection, params?: Record<string, unknown>): void;
  params: Record<string, unknown>;
}

export default function AdminApp({ win }: AppProps) {
  const mobile = useIsMobile();
  const [section, setSection] = useState<AdminSection>((win.params.section as AdminSection) || "overview");
  const [params, setParams] = useState<Record<string, unknown>>({ userId: win.params.userId ?? null });
  const [mobileNav, setMobileNav] = useState(false);

  useEffect(() => {
    if (win.nonce === 0) return;
    if (win.params.section) setSection(win.params.section as AdminSection);
    setParams({ userId: win.params.userId ?? null });
  }, [win.nonce, win.params.section, win.params.userId]);

  const nav: AdminNav = {
    go: (s, p = {}) => {
      setSection(s);
      setParams(p);
      setMobileNav(false);
    },
    params,
  };
  const current = NAV.find((n) => n.id === section) ?? NAV[0];
  const showNav = !mobile || mobileNav;

  return (
    <div className={cx("admin-app", mobile && "is-mobile")}>
      {showNav && (
        <nav className="settings-nav admin-nav" aria-label="Administration">
          <div className="admin-nav-title">TourDesk Administration</div>
          {NAV.map((n) => (
            <button key={n.id} type="button" className={cx("settings-nav-item", section === n.id && "is-selected")} onClick={() => nav.go(n.id)}>
              {n.icon}
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
      )}
      {(!mobile || !mobileNav) && (
        <div className="settings-content admin-content">
          <header className="settings-head">
            {mobile && (
              <button type="button" className="settings-back" onClick={() => setMobileNav(true)} aria-label="Bereiche">
                <ChevronLeft size={20} />
              </button>
            )}
            <h2>{current.label}</h2>
          </header>
          {section === "overview" && <OverviewSection nav={nav} />}
          {section === "users" && <UsersSection nav={nav} />}
          {section === "crawler" && <CrawlerSection nav={nav} />}
          {section === "errors" && <ErrorsSection nav={nav} />}
          {section === "sources" && <SourcesSection nav={nav} />}
          {section === "events" && <EventsSection nav={nav} />}
          {section === "catalog" && <CatalogSection nav={nav} />}
          {section === "geo" && <GeoReviewSection />}
          {section === "system" && <SystemSection />}
          {section === "logs" && <LogsSection />}
          {section === "audit" && <AuditSection />}
          {section === "crawler-settings" && <CrawlerSettingsSection />}
        </div>
      )}
    </div>
  );
}
