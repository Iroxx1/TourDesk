// "Einstellungen" in the style of the Windows 11 settings app.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Building2,
  Camera,
  Check,
  ChevronLeft,
  Droplets,
  Image as ImageIcon,
  Info,
  KeyRound,
  LayoutGrid,
  LogOut,
  Map,
  Mic2,
  Moon,
  Palette,
  SlidersHorizontal,
  Sparkles,
  Sun,
  SunMoon,
  Trash2,
  UserRound,
} from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Me, Settings, Theme, User, ViewSettings } from "../api/types";
import { qk, useSettingsOptions, useUpdateSettings } from "../api/hooks";
import { useSession } from "../auth/session";
import { Avatar, Button, Card, InfoBar, Segmented, Select, SettingRow, TextField, Toggle, cx } from "../components/ui";
import { fmtDateTime } from "../lib/format";
import { useIsMobile } from "../lib/useMediaQuery";
import { wallpaperUrl } from "../lib/urls";
import { toast } from "../state/ui";
import { openApp } from "../state/windows";
import type { AppProps } from "./registry";

type Section = "home" | "account" | "design" | "wallpaper" | "view" | "notifications" | "about";

const NAV: { id: Section; label: string; icon: ReactNode }[] = [
  { id: "home", label: "Startseite", icon: <LayoutGrid size={17} /> },
  { id: "account", label: "Mein Konto", icon: <UserRound size={17} /> },
  { id: "design", label: "Design", icon: <Palette size={17} /> },
  { id: "wallpaper", label: "Desktop-Hintergrund", icon: <ImageIcon size={17} /> },
  { id: "view", label: "Ansicht", icon: <SlidersHorizontal size={17} /> },
  { id: "notifications", label: "Benachrichtigungen", icon: <Bell size={17} /> },
  { id: "about", label: "Info", icon: <Info size={17} /> },
];

function useSave() {
  const update = useUpdateSettings();
  return (patch: Partial<Settings>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });
}

function AccountSection() {
  const { me, readOnly, logout } = useSession();
  const qc = useQueryClient();
  const user = me.user;
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [username, setUsername] = useState(user.username);
  const [email, setEmail] = useState(user.email);
  const [currentForProfile, setCurrentForProfile] = useState("");
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const fileRef = useRef<HTMLInputElement>(null);
  const setUser = (u: User) => qc.setQueryData<Me>(qk.me, (m) => (m ? { ...m, user: u } : m));

  const sensitive = username.trim() !== user.username || email.trim().toLowerCase() !== user.email.toLowerCase();
  const profile = useMutation({
    mutationFn: () =>
      api.patch<User>("/api/users/me", {
        display_name: displayName.trim() || null,
        username: username.trim(),
        email: email.trim(),
        current_password: sensitive ? currentForProfile : undefined,
      }),
    onSuccess: (u) => {
      setUser(u);
      setCurrentForProfile("");
      toast("Profil gespeichert", "success");
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const password = useMutation({
    mutationFn: () => api.post<{ detail?: string }>("/api/users/me/password", { current_password: pw.current, new_password: pw.next }),
    onSuccess: (r) => {
      setPw({ current: "", next: "", confirm: "" });
      toast(r?.detail || "Passwort geändert", "success");
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const avatar = useMutation({
    mutationFn: (file: File) => api.upload<User>("/api/users/me/avatar", file),
    onSuccess: (u) => {
      setUser(u);
      toast("Profilbild gespeichert", "success");
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const removeAvatar = useMutation({
    mutationFn: () => api.del<User>("/api/users/me/avatar"),
    onSuccess: (u) => setUser(u),
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const pwMismatch = pw.confirm.length > 0 && pw.next !== pw.confirm;

  return (
    <div className="stack">
      <div className="account-hero">
        <Avatar user={user} size={84} />
        <div>
          <h3>{user.display_name || user.username}</h3>
          <div className="muted">{user.email}</div>
          <div className="muted small">
            {me.is_admin ? "Administrator" : "Benutzer"} · Mitglied seit {fmtDateTime(user.created_at).slice(0, 10)}
          </div>
          <div className="button-row">
            <Button size="sm" icon={<Camera size={14} />} disabled={readOnly} loading={avatar.isPending} onClick={() => fileRef.current?.click()}>
              Profilbild ändern
            </Button>
            {user.avatar_url && (
              <Button size="sm" variant="subtle" icon={<Trash2 size={14} />} disabled={readOnly} onClick={() => removeAvatar.mutate()}>
                Entfernen
              </Button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) avatar.mutate(f);
                e.target.value = "";
              }}
            />
          </div>
        </div>
      </div>

      <Card title="Profil" icon={<UserRound size={16} />}>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            profile.mutate();
          }}
        >
          <TextField label="Anzeigename" value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={64} disabled={readOnly} />
          <TextField label="Benutzername" value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={32} required disabled={readOnly} autoComplete="username" />
          <TextField label="E-Mail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={readOnly} autoComplete="email" className="span-2" />
          {sensitive && (
            <TextField
              label="Aktuelles Passwort"
              type="password"
              value={currentForProfile}
              onChange={(e) => setCurrentForProfile(e.target.value)}
              hint="Zur Änderung von Benutzername oder E-Mail erforderlich."
              required
              autoComplete="current-password"
              className="span-2"
            />
          )}
          <div className="form-actions span-2">
            <Button type="submit" variant="accent" loading={profile.isPending} disabled={readOnly}>
              Speichern
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Passwort ändern" icon={<KeyRound size={16} />} subtitle="Mindestens 10 Zeichen. Andere Sitzungen werden danach abgemeldet.">
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            if (!pwMismatch) password.mutate();
          }}
        >
          <TextField label="Aktuelles Passwort" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required autoComplete="current-password" disabled={readOnly} className="span-2" />
          <TextField label="Neues Passwort" type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required minLength={10} autoComplete="new-password" disabled={readOnly} />
          <TextField
            label="Neues Passwort wiederholen"
            type="password"
            value={pw.confirm}
            onChange={(e) => setPw({ ...pw, confirm: e.target.value })}
            required
            autoComplete="new-password"
            error={pwMismatch ? "Die Passwörter stimmen nicht überein." : undefined}
            disabled={readOnly}
          />
          <div className="form-actions span-2">
            <Button type="submit" variant="accent" loading={password.isPending} disabled={readOnly || !pw.current || pw.next.length < 10 || pwMismatch}>
              Passwort ändern
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Sitzung">
        <SettingRow icon={<LogOut size={18} />} title="Abmelden" description={`Sitzung gültig bis ${fmtDateTime(me.session_expires_at)}`}>
          <Button onClick={() => void logout()}>Abmelden</Button>
        </SettingRow>
      </Card>
    </div>
  );
}

function DesignSection() {
  const { me, readOnly } = useSession();
  const options = useSettingsOptions();
  const save = useSave();
  const s = me.settings;
  const themes: { value: Theme; label: string; icon: ReactNode }[] = [
    { value: "light", label: "Hell", icon: <Sun size={18} /> },
    { value: "dark", label: "Dunkel", icon: <Moon size={18} /> },
    { value: "system", label: "System", icon: <SunMoon size={18} /> },
  ];
  return (
    <div className="stack">
      <Card title="Farbmodus" subtitle="Hell, Dunkel oder automatisch passend zum Betriebssystem.">
        <div className="theme-choices">
          {themes.map((t) => (
            <button key={t.value} type="button" className={cx("theme-choice", `theme-choice-${t.value}`, s.theme === t.value && "is-selected")} disabled={readOnly} onClick={() => save({ theme: t.value })}>
              <span className="theme-preview" aria-hidden>
                <span className="tp-window">
                  <span className="tp-bar" />
                  <span className="tp-line" />
                  <span className="tp-line short" />
                </span>
              </span>
              <span className="theme-label">
                {t.icon} {t.label}
                {s.theme === t.value && <Check size={14} />}
              </span>
            </button>
          ))}
        </div>
      </Card>
      <Card title="Akzentfarbe" subtitle="Für Schaltflächen, Auswahl und Hervorhebungen.">
        <div className="accent-swatches">
          <button type="button" className={cx("swatch", "swatch-auto", !s.accent_color && "is-selected")} title="Standard" disabled={readOnly} onClick={() => save({ accent_color: null })}>
            <span>Auto</span>
          </button>
          {(options.data?.accent_colors ?? []).map((c) => (
            <button
              key={c.key}
              type="button"
              className={cx("swatch", s.accent_color === c.key && "is-selected")}
              style={{ background: c.key }}
              title={c.name}
              aria-label={c.name}
              disabled={readOnly}
              onClick={() => save({ accent_color: c.key })}
            >
              {s.accent_color === c.key && <Check size={16} />}
            </button>
          ))}
        </div>
      </Card>
      <Card title="Effekte">
        <SettingRow icon={<Droplets size={18} />} title="Transparenzeffekte" description="Acrylic-/Glaseffekte für Fenster, Taskleiste und Menüs">
          <Toggle checked={s.transparency} disabled={readOnly} onChange={(v) => save({ transparency: v })} />
        </SettingRow>
        <SettingRow icon={<Sparkles size={18} />} title="Animationen" description="Fenster- und Menüanimationen">
          <Toggle checked={s.animations} disabled={readOnly} onChange={(v) => save({ animations: v })} />
        </SettingRow>
      </Card>
    </div>
  );
}

function WallpaperSection() {
  const { me, readOnly } = useSession();
  const options = useSettingsOptions();
  const save = useSave();
  return (
    <div className="stack">
      <div className="wallpaper-current">
        <img src={wallpaperUrl(me.settings.wallpaper, true)} alt="" />
        <div>
          <div className="muted small">Aktueller Hintergrund</div>
          <strong>{options.data?.wallpapers.find((w) => w.key === me.settings.wallpaper)?.name ?? me.settings.wallpaper}</strong>
        </div>
      </div>
      <div className="wallpaper-grid">
        {(options.data?.wallpapers ?? []).map((w) => (
          <button key={w.key} type="button" className={cx("wallpaper-option", me.settings.wallpaper === w.key && "is-selected")} disabled={readOnly} onClick={() => save({ wallpaper: w.key })}>
            <img src={wallpaperUrl(w.key, true)} alt="" loading="lazy" />
            <span className="wallpaper-name">
              {w.name}
              {me.settings.wallpaper === w.key && <Check size={14} />}
            </span>
            <span className="wallpaper-desc">{w.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ViewSection() {
  const { me, readOnly } = useSession();
  const save = useSave();
  const v = me.settings.view;
  const setView = (patch: Partial<ViewSettings>) => save({ view: { ...v, ...patch } });
  return (
    <div className="stack">
      <Card title="Desktop-Kacheln">
        <SettingRow title="Kachelgröße">
          <Segmented<ViewSettings["tile_size"]>
            value={v.tile_size}
            disabled={readOnly}
            onChange={(tile_size) => setView({ tile_size })}
            options={[
              { value: "small", label: "Klein" },
              { value: "medium", label: "Mittel" },
              { value: "large", label: "Groß" },
            ]}
          />
        </SettingRow>
        <SettingRow title="Sortierung">
          <Select
            aria-label="Sortierung"
            value={v.sort}
            disabled={readOnly}
            onChange={(sort) => setView({ sort: sort as ViewSettings["sort"] })}
            options={[
              { value: "next_event", label: "Nächster Termin" },
              { value: "name", label: "Name" },
              { value: "added", label: "Eigene Reihenfolge" },
            ]}
          />
        </SettingRow>
        <SettingRow title="Termine pro Kachel" description="Wie viele passende Termine direkt auf der Kachel stehen">
          <Select
            aria-label="Termine pro Kachel"
            value={String(v.tile_event_count)}
            disabled={readOnly}
            onChange={(n) => setView({ tile_event_count: Number(n) })}
            options={[1, 2, 3, 4, 5, 6, 8, 10].map((n) => ({ value: String(n), label: String(n) }))}
          />
        </SettingRow>
        <SettingRow title="Künstler ohne Termine anzeigen">
          <Toggle checked={v.show_artists_without_events} disabled={readOnly} onChange={(show_artists_without_events) => setView({ show_artists_without_events })} />
        </SettingRow>
      </Card>
      <Card title="Fenster & Taskleiste">
        <SettingRow title="Namen in der Taskleiste anzeigen" description="Zeigt neben den Künstlerbildern auch die Namen">
          <Toggle checked={v.taskbar_labels} disabled={readOnly} onChange={(taskbar_labels) => setView({ taskbar_labels })} />
        </SettingRow>
        <SettingRow title="Fenster maximiert öffnen">
          <Toggle checked={v.open_windows_maximized} disabled={readOnly} onChange={(open_windows_maximized) => setView({ open_windows_maximized })} />
        </SettingRow>
      </Card>
    </div>
  );
}

function NotificationsSection() {
  const { me, readOnly } = useSession();
  const options = useSettingsOptions();
  const save = useSave();
  const n = me.settings.notifications;
  return (
    <div className="stack">
      <Card title="Benachrichtigungen in TourDesk" subtitle="Erscheinen im Infobereich der Taskleiste (Glocke).">
        {(options.data?.notification_types ?? []).map((t) => (
          <SettingRow key={t.key} title={t.name}>
            <Toggle checked={n[t.key] !== false} disabled={readOnly} onChange={(v) => save({ notifications: { ...n, [t.key]: v } })} />
          </SettingRow>
        ))}
      </Card>
      <Card title="Weitere Kanäle" subtitle="Die Architektur ist vorbereitet – diese Kanäle können später angebunden werden.">
        {["E-Mail", "Push-Benachrichtigungen", "Telegram", "Discord", "WhatsApp"].map((c) => (
          <SettingRow key={c} title={c} description="In Vorbereitung">
            <Toggle checked={false} disabled onChange={() => undefined} />
          </SettingRow>
        ))}
      </Card>
    </div>
  );
}

function AboutSection() {
  const { me, readOnly } = useSession();
  const save = useSave();
  const zones = (() => {
    try {
      const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
      const list = fn ? fn("timeZone") : [];
      return list.length ? list : ["Europe/Berlin", "Europe/Luxembourg", "Europe/Paris", "Europe/Brussels", "Europe/Amsterdam", "Europe/Vienna", "Europe/Zurich", "UTC"];
    } catch {
      return ["Europe/Berlin", "UTC"];
    }
  })();
  return (
    <div className="stack">
      <Card title="TourDesk">
        <SettingRow title="Version" description="Persönliche Konzert- und Tourüberwachung">
          <strong>{me.version}</strong>
        </SettingRow>
        <SettingRow title="Zeitzone" description="Für Datums- und Uhrzeitangaben">
          <Select aria-label="Zeitzone" value={me.settings.timezone} disabled={readOnly} onChange={(timezone) => save({ timezone })} options={zones.map((z) => ({ value: z, label: z }))} />
        </SettingRow>
        <SettingRow title="Angemeldet als" description={me.user.email}>
          <span>{me.user.username}</span>
        </SettingRow>
      </Card>
      <InfoBar tone="info" title="Datenquellen">
        Termine stammen aus öffentlich erreichbaren Quellen (offizielle Websites, Veranstaltungsorte, Festivals, Ticketanbieter). Ticketlinks führen immer zur externen Originalseite.
      </InfoBar>
    </div>
  );
}

function Home({ go }: { go(s: Section): void }) {
  const { me } = useSession();
  const links: { label: string; desc: string; icon: ReactNode; onClick(): void }[] = [
    { label: "Mein Konto", desc: "Benutzername, E-Mail, Passwort, Profilbild", icon: <UserRound size={20} />, onClick: () => go("account") },
    { label: "Künstler", desc: "Hinzufügen, bearbeiten, löschen, aktiv/inaktiv, Festivals", icon: <Mic2 size={20} />, onClick: () => openApp("artists") },
    { label: "Regionen & Orte", desc: "Länder, Bundesländer, Regionen, Städte", icon: <Map size={20} />, onClick: () => openApp("places") },
    { label: "Veranstaltungsorte", desc: "Bevorzugte Venues hinzufügen und entfernen", icon: <Building2 size={20} />, onClick: () => openApp("venues") },
    { label: "Filter", desc: "Konzertfilter, Festivalfilter, Zeitraum, Orte", icon: <SlidersHorizontal size={20} />, onClick: () => openApp("filters") },
    { label: "Design", desc: "Dark Mode, Akzentfarbe, Animationen", icon: <Palette size={20} />, onClick: () => go("design") },
    { label: "Desktop-Hintergrund", desc: "12 Hintergründe zur Auswahl", icon: <ImageIcon size={20} />, onClick: () => go("wallpaper") },
    { label: "Ansicht", desc: "Kacheln, Sortierung, Taskleiste", icon: <LayoutGrid size={20} />, onClick: () => go("view") },
    { label: "Benachrichtigungen", desc: "Neue Termine, Ticketstarts, Absagen", icon: <Bell size={20} />, onClick: () => go("notifications") },
  ];
  return (
    <div className="stack">
      <div className="settings-home-user">
        <Avatar user={me.user} size={64} />
        <div>
          <h3>{me.user.display_name || me.user.username}</h3>
          <div className="muted">{me.user.email}</div>
        </div>
      </div>
      <div className="settings-home-grid">
        {links.map((l) => (
          <button key={l.label} type="button" className="settings-home-card" onClick={l.onClick}>
            <span className="settings-home-icon">{l.icon}</span>
            <span>
              <strong>{l.label}</strong>
              <span className="muted">{l.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function SettingsApp({ win }: AppProps) {
  const mobile = useIsMobile();
  const initial = (win.params.section as Section) || "home";
  const [section, setSection] = useState<Section>(initial);
  const [mobileNav, setMobileNav] = useState(initial === "home");
  useEffect(() => {
    if (win.params.section) {
      setSection(win.params.section as Section);
      setMobileNav(win.params.section === "home");
    }
  }, [win.nonce, win.params.section]);

  const go = (s: Section) => {
    setSection(s);
    setMobileNav(false);
  };
  const current = NAV.find((n) => n.id === section) ?? NAV[0];
  const showNav = !mobile || mobileNav;
  const showContent = !mobile || !mobileNav;

  return (
    <div className={cx("settings-app", mobile && "is-mobile")}>
      {showNav && (
        <nav className="settings-nav" aria-label="Einstellungen">
          {NAV.map((n) => (
            <button key={n.id} type="button" className={cx("settings-nav-item", section === n.id && !mobile && "is-selected")} onClick={() => go(n.id)}>
              {n.icon}
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
      )}
      {showContent && (
        <div className="settings-content">
          <header className="settings-head">
            {mobile && (
              <button type="button" className="settings-back" onClick={() => setMobileNav(true)} aria-label="Zurück">
                <ChevronLeft size={20} />
              </button>
            )}
            <h2>{current.label}</h2>
          </header>
          {section === "home" && <Home go={go} />}
          {section === "account" && <AccountSection />}
          {section === "design" && <DesignSection />}
          {section === "wallpaper" && <WallpaperSection />}
          {section === "view" && <ViewSection />}
          {section === "notifications" && <NotificationsSection />}
          {section === "about" && <AboutSection />}
        </div>
      )}
    </div>
  );
}
