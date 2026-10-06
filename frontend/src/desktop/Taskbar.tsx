// Windows-like taskbar: Start (logo), search, artist apps, open windows, tray, clock.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Bell, ChevronUp, Moon, Radar, Search, Sun, SunMoon } from "lucide-react";
import type { Artist } from "../api/types";
import { useArtists, useCrawlerStatus, useNotifications } from "../api/hooks";
import { useSession } from "../auth/session";
import { AppIcon } from "../apps/registry";
import { ArtistImage } from "../components/ArtistImage";
import { Logo } from "../components/Logo";
import { cx } from "../components/ui";
import { fmtClock, fmtDate, isoDay } from "../lib/format";
import { useResolvedTheme } from "../lib/theme";
import { mediaSrc } from "../lib/urls";
import { useUi } from "../state/ui";
import { openArtist, topWindow, useWindows, type WindowState } from "../state/windows";

const ICON_W = 44;
const LABEL_W = 150;

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = () => setNow(new Date());
    const t = window.setInterval(tick, 15_000);
    return () => window.clearInterval(t);
  }, []);
  return now;
}

export function sortedArtists(artists: Artist[] | undefined): Artist[] {
  return [...(artists ?? [])].sort((a, b) => {
    const pa = a.subscription?.pinned ? 0 : 1;
    const pb = b.subscription?.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    return (a.subscription?.sort_order ?? 0) - (b.subscription?.sort_order ?? 0) || a.name.localeCompare(b.name, "de");
  });
}

/** Click on a taskbar entry: open, focus or minimize (like Windows). */
function activate(win: WindowState | undefined, topId: string | null, openFn: () => void) {
  const actions = useWindows.getState();
  if (!win) return openFn();
  if (win.minimized) return actions.focus(win.id);
  if (topId === win.id) return actions.minimize(win.id);
  actions.focus(win.id);
}

export function Taskbar() {
  const { me } = useSession();
  const windows = useWindows((s) => s.windows);
  const top = topWindow(windows);
  const flyout = useUi((s) => s.flyout);
  const toggleFlyout = useUi((s) => s.toggleFlyout);
  const { data: artists } = useArtists();
  const notifications = useNotifications();
  const crawler = useCrawlerStatus();
  const now = useClock();
  const theme = useResolvedTheme(me.settings);
  const labels = me.settings.view.taskbar_labels;

  const listRef = useRef<HTMLDivElement>(null);
  const [capacity, setCapacity] = useState(8);
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const measure = () => setCapacity(Math.max(1, Math.floor(el.clientWidth / (labels ? LABEL_W : ICON_W))));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [labels]);

  const artistList = useMemo(() => sortedArtists(artists), [artists]);
  const otherWindows = windows.filter((w) => w.kind !== "artist");
  const artistWindows = new Map(windows.filter((w) => w.kind === "artist").map((w) => [Number(w.params.artistId), w]));
  // artists with an open window always get a slot
  const slots = Math.max(0, capacity - otherWindows.length - 1);
  let visible = artistList.slice(0, slots);
  const missingOpen = artistList.filter((a) => artistWindows.has(a.id) && !visible.includes(a));
  if (missingOpen.length) visible = [...visible.slice(0, Math.max(0, slots - missingOpen.length)), ...missingOpen];
  const hidden = artistList.length - visible.length;
  const unread = notifications.data?.unread ?? 0;
  const busy = (crawler.data?.running.length ?? 0) + (crawler.data?.queued.length ?? 0);

  return (
    <footer className={cx("taskbar", labels && "with-labels")} role="toolbar" aria-label="Taskleiste">
      <div className="taskbar-left">
        <button
          type="button"
          className={cx("tb-btn", "tb-start", flyout === "start" && "is-open")}
          aria-label="Start"
          title="Start"
          aria-expanded={flyout === "start"}
          data-flyout-toggle="start"
          onClick={() => toggleFlyout("start")}
        >
          <Logo size={26} />
        </button>
        <button
          type="button"
          className={cx("tb-btn", "tb-search", flyout === "search" && "is-open")}
          aria-label="Suche"
          title="Suche (Strg+K)"
          data-flyout-toggle="search"
          onClick={() => toggleFlyout("search")}
        >
          <Search size={18} />
          <span className="tb-search-label">Suchen</span>
        </button>
        <div className="tb-sep" aria-hidden />
        <div className="tb-apps" ref={listRef}>
          {visible.map((a) => {
            const win = artistWindows.get(a.id);
            const isTop = top?.id === win?.id && Boolean(win);
            const inactive = a.subscription && !a.subscription.is_active;
            return (
              <button
                key={a.id}
                type="button"
                className={cx("tb-btn", "tb-artist", win && "is-running", isTop && "is-active", inactive && "is-dim")}
                title={a.name}
                aria-label={a.name}
                onClick={() => activate(win, top?.id ?? null, () => openArtist(a.id, a.name, a.images.thumb))}
              >
                <ArtistImage artist={a} variant="thumb" className="tb-artist-img" />
                {labels && <span className="tb-label">{a.name}</span>}
                <span className="tb-indicator" aria-hidden />
              </button>
            );
          })}
          {hidden > 0 && (
            <button
              type="button"
              className={cx("tb-btn", "tb-more", flyout === "artists" && "is-open")}
              title={`${hidden} weitere Künstler`}
              aria-label={`${hidden} weitere Künstler`}
              data-flyout-toggle="artists"
              onClick={() => toggleFlyout("artists")}
            >
              <ChevronUp size={16} />
              <span className="tb-more-count">+{hidden}</span>
            </button>
          )}
          {otherWindows.length > 0 && artistList.length > 0 && <div className="tb-sep" aria-hidden />}
          {otherWindows.map((w) => {
            const isTop = top?.id === w.id;
            const icon = w.kind === "event" ? undefined : mediaSrc(w.icon);
            return (
              <button
                key={w.id}
                type="button"
                className={cx("tb-btn", "tb-window", "is-running", isTop && "is-active")}
                title={w.title}
                aria-label={w.title}
                onClick={() => activate(w, top?.id ?? null, () => undefined)}
              >
                {icon ? <img className="tb-window-img" src={icon} alt="" /> : <AppIcon kind={w.kind} size={26} />}
                {labels && <span className="tb-label">{w.title}</span>}
                <span className="tb-indicator" aria-hidden />
              </button>
            );
          })}
        </div>
      </div>

      <div className="taskbar-tray">
        {busy > 0 && (
          <span className="tray-item tray-busy" title={`Crawler aktiv: ${busy} Künstler`}>
            <Radar size={16} className="pulse" />
          </span>
        )}
        <button
          type="button"
          className={cx("tb-btn", "tray-btn", flyout === "quick" && "is-open")}
          aria-label="Schnelleinstellungen"
          title="Schnelleinstellungen"
          data-flyout-toggle="quick"
          onClick={() => toggleFlyout("quick")}
        >
          {me.settings.theme === "system" ? <SunMoon size={17} /> : theme === "dark" ? <Moon size={17} /> : <Sun size={17} />}
        </button>
        <button
          type="button"
          className={cx("tb-btn", "tray-btn", "tray-bell", flyout === "notifications" && "is-open")}
          aria-label={unread ? `Benachrichtigungen (${unread} ungelesen)` : "Benachrichtigungen"}
          title="Benachrichtigungen"
          data-flyout-toggle="notifications"
          onClick={() => toggleFlyout("notifications")}
        >
          <Bell size={17} />
          {unread > 0 && <span className="tray-badge">{unread > 99 ? "99+" : unread}</span>}
        </button>
        <button
          type="button"
          className={cx("tb-btn", "tray-clock", flyout === "notifications" && "is-open")}
          title={fmtDate(isoDay(now))}
          data-flyout-toggle="notifications"
          onClick={() => toggleFlyout("notifications")}
        >
          <span className="clock-time">{fmtClock(now)}</span>
          <span className="clock-date">{fmtDate(isoDay(now))}</span>
        </button>
        <button type="button" className="tb-show-desktop" aria-label="Desktop anzeigen" title="Desktop anzeigen" onClick={() => useWindows.getState().showDesktop()} />
      </div>
    </footer>
  );
}
