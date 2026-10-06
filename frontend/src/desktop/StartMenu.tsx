// Windows 11 style Start menu: search, pinned apps, artists, account + power.
import { useState, type ReactNode } from "react";
import { LogOut, Moon, Palette, Image as ImageIcon, Search, Sun, SunMoon, UserRound } from "lucide-react";
import { useArtists, useUpdateSettings } from "../api/hooks";
import { useSession } from "../auth/session";
import { AppIcon } from "../apps/registry";
import { ArtistImage } from "../components/ArtistImage";
import { Avatar, cx } from "../components/ui";
import { nextTheme, THEME_LABELS } from "../lib/theme";
import { useUi } from "../state/ui";
import { openApp, openArtist, type AppKind } from "../state/windows";
import { sortedArtists } from "./Taskbar";

interface PinnedItem {
  label: string;
  kind: AppKind;
  icon?: ReactNode;
  onClick(): void;
}

export function StartMenu() {
  const { me, logout, readOnly } = useSession();
  const close = () => useUi.getState().setFlyout(null);
  const openSearch = useUi((s) => s.openSearch);
  const { data: artists } = useArtists();
  const updateSettings = useUpdateSettings();
  const [query, setQuery] = useState("");
  const list = sortedArtists(artists);
  const theme = me.settings.theme;

  const run = (fn: () => void) => () => {
    fn();
    close();
  };

  const pinned: PinnedItem[] = [
    { label: "Künstler", kind: "artists", onClick: run(() => openApp("artists")) },
    { label: "Termine", kind: "agenda", onClick: run(() => openApp("agenda")) },
    { label: "Filter", kind: "filters", onClick: run(() => openApp("filters")) },
    { label: "Orte", kind: "places", onClick: run(() => openApp("places")) },
    { label: "Veranstaltungsorte", kind: "venues", onClick: run(() => openApp("venues")) },
    { label: "Einstellungen", kind: "settings", onClick: run(() => openApp("settings", { section: "home" })) },
    {
      label: "Benutzerkonto",
      kind: "settings",
      icon: <span className="app-icon tone-cyan pinned-icon"><UserRound size={20} /></span>,
      onClick: run(() => openApp("settings", { section: "account" })),
    },
    {
      label: "Design",
      kind: "settings",
      icon: <span className="app-icon tone-pink pinned-icon"><Palette size={20} /></span>,
      onClick: run(() => openApp("settings", { section: "design" })),
    },
    {
      label: "Desktop-Hintergrund",
      kind: "settings",
      icon: <span className="app-icon tone-indigo pinned-icon"><ImageIcon size={20} /></span>,
      onClick: run(() => openApp("settings", { section: "wallpaper" })),
    },
  ];
  if (me.is_admin) pinned.push({ label: "Administration", kind: "admin", onClick: run(() => openApp("admin", { section: "overview" })) });

  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : SunMoon;

  return (
    <div className="flyout start-menu" role="dialog" aria-label="Startmenü">
      <form
        className="start-search"
        onSubmit={(e) => {
          e.preventDefault();
          openSearch(query);
        }}
      >
        <Search size={16} aria-hidden />
        <input
          autoFocus
          className="start-search-input"
          placeholder="Künstler, Orte und Termine durchsuchen"
          aria-label="Suchen"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (e.target.value.trim().length >= 2) openSearch(e.target.value);
          }}
        />
      </form>

      <section className="start-section">
        <div className="start-section-head">
          <h2>Angeheftet</h2>
        </div>
        <div className="start-grid">
          {pinned.map((p) => (
            <button key={p.label} type="button" className="start-app" onClick={p.onClick}>
              {p.icon ?? <AppIcon kind={p.kind} size={40} />}
              <span>{p.label}</span>
            </button>
          ))}
          <button
            type="button"
            className="start-app"
            disabled={readOnly}
            onClick={() => updateSettings.mutate({ theme: nextTheme(theme) })}
            title="Dark Mode umschalten (Hell → Dunkel → System)"
          >
            <span className={cx("app-icon", "pinned-icon", theme === "dark" ? "tone-night" : "tone-sun")}>
              <ThemeIcon size={20} />
            </span>
            <span>Dark Mode: {THEME_LABELS[theme]}</span>
          </button>
        </div>
      </section>

      <section className="start-section start-artists">
        <div className="start-section-head">
          <h2>Meine Künstler</h2>
          <button type="button" className="start-link" onClick={run(() => openApp("artists"))}>
            Alle verwalten ›
          </button>
        </div>
        {list.length ? (
          <div className="start-artist-grid">
            {list.slice(0, 8).map((a) => (
              <button key={a.id} type="button" className="start-artist" onClick={run(() => openArtist(a.id, a.name, a.images.thumb))}>
                <ArtistImage artist={a} variant="thumb" className="start-artist-img" />
                <span className="start-artist-text">
                  <span className="start-artist-name">{a.name}</span>
                  <span className="start-artist-sub">{a.genre || (a.subscription?.is_active === false ? "inaktiv" : "Künstler")}</span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="start-empty">Noch keine Künstler. Öffne „Künstler“, um den ersten hinzuzufügen.</p>
        )}
      </section>

      <footer className="start-footer">
        <button type="button" className="start-user" onClick={run(() => openApp("settings", { section: "account" }))}>
          <Avatar user={me.user} size={32} />
          <span className="start-user-text">
            <span className="start-user-name">{me.user.display_name || me.user.username}</span>
            <span className="start-user-role">{me.is_admin ? "Administrator" : "Benutzer"}</span>
          </span>
        </button>
        <button type="button" className="start-power" onClick={() => void logout()} title="Abmelden" aria-label="Abmelden">
          <LogOut size={18} />
          <span>Abmelden</span>
        </button>
      </footer>
    </div>
  );
}
