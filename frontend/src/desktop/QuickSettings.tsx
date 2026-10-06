// Quick settings (Windows 11 style): theme, transparency, animations, crawler state.
import { Droplets, Image as ImageIcon, Moon, Radar, Settings, Sparkles, Sun, SunMoon } from "lucide-react";
import type { Settings as UserSettings, Theme } from "../api/types";
import { useCrawlerStatus, useSettingsOptions, useUpdateSettings } from "../api/hooks";
import { errorMessage } from "../api/client";
import { useSession } from "../auth/session";
import { cx } from "../components/ui";
import { fmtRelative } from "../lib/format";
import { wallpaperUrl } from "../lib/urls";
import { toast, useUi } from "../state/ui";
import { openApp } from "../state/windows";

export function QuickSettings() {
  const { me, readOnly } = useSession();
  const update = useUpdateSettings();
  const options = useSettingsOptions();
  const crawler = useCrawlerStatus();
  const s = me.settings;
  const close = () => useUi.getState().setFlyout(null);
  const set = (patch: Partial<UserSettings>) => update.mutate(patch, { onError: (e) => toast(errorMessage(e), "error") });

  const themes: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Hell", icon: Sun },
    { value: "dark", label: "Dunkel", icon: Moon },
    { value: "system", label: "System", icon: SunMoon },
  ];
  const busy = (crawler.data?.running.length ?? 0) + (crawler.data?.queued.length ?? 0);

  return (
    <div className="flyout quick-settings" role="dialog" aria-label="Schnelleinstellungen">
      <div className="qs-grid">
        {themes.map((t) => (
          <button
            key={t.value}
            type="button"
            className={cx("qs-tile", s.theme === t.value && "is-on")}
            aria-pressed={s.theme === t.value}
            disabled={readOnly}
            onClick={() => set({ theme: t.value })}
          >
            <t.icon size={18} />
            <span>{t.label}</span>
          </button>
        ))}
        <button type="button" className={cx("qs-tile", s.transparency && "is-on")} aria-pressed={s.transparency} disabled={readOnly} onClick={() => set({ transparency: !s.transparency })}>
          <Droplets size={18} />
          <span>Transparenz</span>
        </button>
        <button type="button" className={cx("qs-tile", s.animations && "is-on")} aria-pressed={s.animations} disabled={readOnly} onClick={() => set({ animations: !s.animations })}>
          <Sparkles size={18} />
          <span>Animationen</span>
        </button>
        <button type="button" className="qs-tile" onClick={() => { openApp("settings", { section: "wallpaper" }); close(); }}>
          <ImageIcon size={18} />
          <span>Hintergrund</span>
        </button>
      </div>

      {options.data && (
        <div className="qs-wallpapers" aria-label="Hintergrund wählen">
          {options.data.wallpapers.slice(0, 6).map((w) => (
            <button
              key={w.key}
              type="button"
              className={cx("qs-wallpaper", s.wallpaper === w.key && "is-selected")}
              title={w.name}
              disabled={readOnly}
              onClick={() => set({ wallpaper: w.key })}
            >
              <img src={wallpaperUrl(w.key, true)} alt={w.name} loading="lazy" />
            </button>
          ))}
        </div>
      )}

      <footer className="qs-foot">
        <span className={cx("qs-crawler", busy > 0 && "is-busy")}>
          <Radar size={15} className={busy ? "pulse" : undefined} />
          {busy > 0 ? `Crawler sucht gerade (${busy})` : `Letzter Crawl ${fmtRelative(crawler.data?.last_run_at ?? null)}`}
        </span>
        <button type="button" className="qs-settings" aria-label="Alle Einstellungen" title="Alle Einstellungen" onClick={() => { openApp("settings", { section: "home" }); close(); }}>
          <Settings size={16} />
        </button>
      </footer>
    </div>
  );
}
