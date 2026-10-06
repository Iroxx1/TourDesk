// The TourDesk desktop: wallpaper, desktop icons, tiles, windows, taskbar, flyouts.
import { useEffect } from "react";
import { Bell, CalendarDays, Search } from "lucide-react";
import { useNotifications } from "../api/hooks";
import { useSession } from "../auth/session";
import { AppIcon } from "../apps/registry";
import { ConfirmHost } from "../components/Dialog";
import { Logo } from "../components/Logo";
import { cx } from "../components/ui";
import { useIsMobile } from "../lib/useMediaQuery";
import { useUi } from "../state/ui";
import { openApp, useWindows, type AppKind } from "../state/windows";
import { Flyouts } from "./Flyouts";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { Taskbar } from "./Taskbar";
import { TileGrid } from "./TileGrid";
import { Toasts } from "./Toasts";
import { Wallpaper } from "./Wallpaper";
import { WindowLayer } from "./WindowLayer";

const SHORTCUTS: { kind: Exclude<AppKind, "artist" | "event">; label: string }[] = [
  { kind: "agenda", label: "Termine" },
  { kind: "artists", label: "Künstler" },
  { kind: "filters", label: "Filter" },
  { kind: "places", label: "Orte" },
  { kind: "venues", label: "Veranstaltungsorte" },
  { kind: "settings", label: "Einstellungen" },
];

function DesktopIcons({ admin }: { admin: boolean }) {
  const items = admin ? [...SHORTCUTS, { kind: "admin" as const, label: "Administration" }] : SHORTCUTS;
  return (
    <nav className="desktop-icons" aria-label="Desktop-Verknüpfungen">
      {items.map((s) => (
        <button key={s.kind} type="button" className="desktop-icon" onClick={() => openApp(s.kind)} onDoubleClick={(e) => e.preventDefault()}>
          <AppIcon kind={s.kind} size={44} />
          <span>{s.label}</span>
        </button>
      ))}
    </nav>
  );
}

function MobileNav() {
  const flyout = useUi((s) => s.flyout);
  const toggleFlyout = useUi((s) => s.toggleFlyout);
  const windows = useWindows((s) => s.windows);
  const unread = useNotifications().data?.unread ?? 0;
  const agendaOpen = windows.some((w) => w.kind === "agenda" && !w.minimized);
  return (
    <nav className="mobile-nav" aria-label="Navigation">
      <button
        type="button"
        className={cx("mobile-nav-btn", !windows.some((w) => !w.minimized) && !flyout && "is-active")}
        onClick={() => {
          useWindows.getState().closeAll();
          useUi.getState().setFlyout(null);
        }}
      >
        <Logo size={24} />
        <span>Start</span>
      </button>
      <button type="button" className={cx("mobile-nav-btn", flyout === "search" && "is-active")} data-flyout-toggle="search" onClick={() => toggleFlyout("search")}>
        <Search size={22} />
        <span>Suche</span>
      </button>
      <button type="button" className={cx("mobile-nav-btn", agendaOpen && "is-active")} onClick={() => openApp("agenda")}>
        <CalendarDays size={22} />
        <span>Termine</span>
      </button>
      <button
        type="button"
        className={cx("mobile-nav-btn", flyout === "notifications" && "is-active")}
        data-flyout-toggle="notifications"
        onClick={() => toggleFlyout("notifications")}
      >
        <span className="mobile-nav-bell">
          <Bell size={22} />
          {unread > 0 && <span className="tray-badge">{unread > 99 ? "99+" : unread}</span>}
        </span>
        <span>Mitteilungen</span>
      </button>
      <button type="button" className={cx("mobile-nav-btn", flyout === "start" && "is-active")} data-flyout-toggle="start" onClick={() => toggleFlyout("start")}>
        <span className="mobile-nav-menu" aria-hidden>
          <span />
          <span />
          <span />
        </span>
        <span>Menü</span>
      </button>
    </nav>
  );
}

export function Desktop() {
  const { me } = useSession();
  const mobile = useIsMobile();
  const setOpenMaximized = useWindows((s) => s.setOpenMaximized);

  useEffect(() => setOpenMaximized(me.settings.view.open_windows_maximized), [me.settings.view.open_windows_maximized, setOpenMaximized]);

  // Admins land on the administration overview after logging in (once per browser session).
  useEffect(() => {
    if (!me.is_admin || me.impersonation) return;
    try {
      const key = `td.adminOverview.${me.user.id}`;
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, "1");
    } catch {
      return;
    }
    if (!window.matchMedia("(max-width: 767px)").matches) openApp("admin", { section: "overview" });
  }, [me.is_admin, me.impersonation, me.user.id]);

  return (
    <div className={cx("desktop", mobile && "is-mobile", me.impersonation && "is-impersonating")}>
      <Wallpaper wallpaper={me.settings.wallpaper} />
      <ImpersonationBanner />
      <main className="desktop-area" id="desktop">
        {!mobile && <DesktopIcons admin={me.is_admin} />}
        <TileGrid />
      </main>
      <WindowLayer />
      <Flyouts />
      {mobile ? <MobileNav /> : <Taskbar />}
      <Toasts />
      <ConfirmHost />
    </div>
  );
}
