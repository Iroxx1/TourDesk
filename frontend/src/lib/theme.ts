// Applies the personal design settings (theme, accent, transparency, animations) to <html>.
import { useEffect } from "react";
import type { Settings, Theme } from "../api/types";
import { readJson, writeJson } from "./storage";
import { usePrefersDark } from "./useMediaQuery";

export const DEFAULT_ACCENT = "#0067c0";
const CACHE_KEY = "td.design";

export interface DesignCache {
  theme: Theme;
  accent: string | null;
  wallpaper: string;
  transparency: boolean;
  animations: boolean;
}

export const DEFAULT_DESIGN: DesignCache = {
  theme: "system",
  accent: null,
  wallpaper: "bloom",
  transparency: true,
  animations: true,
};

export function cachedDesign(): DesignCache {
  return { ...DEFAULT_DESIGN, ...readJson<Partial<DesignCache>>(CACHE_KEY, {}) };
}

export function designFromSettings(s: Settings): DesignCache {
  return {
    theme: s.theme,
    accent: s.accent_color,
    wallpaper: s.wallpaper,
    transparency: s.transparency,
    animations: s.animations,
  };
}

export function resolveTheme(theme: Theme, systemDark: boolean): "light" | "dark" {
  return theme === "system" ? (systemDark ? "dark" : "light") : theme;
}

function applyDesign(d: DesignCache, systemDark: boolean) {
  const root = document.documentElement;
  const resolved = resolveTheme(d.theme, systemDark);
  root.dataset.theme = resolved;
  const accent = d.accent && /^#[0-9a-f]{6}$/i.test(d.accent) ? d.accent : DEFAULT_ACCENT;
  root.style.setProperty("--accent-base", accent);
  root.classList.toggle("no-transparency", !d.transparency);
  root.classList.toggle("no-animations", !d.animations);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", resolved === "dark" ? "#1c1c20" : "#eef1f7");
}

/** Keeps <html> in sync with the given design (or the cached one before login). */
export function useDesign(settings: Settings | null | undefined) {
  const systemDark = usePrefersDark();
  useEffect(() => {
    const design = settings ? designFromSettings(settings) : cachedDesign();
    applyDesign(design, systemDark);
    if (settings) writeJson(CACHE_KEY, design);
  }, [settings, systemDark]);
}

export function useResolvedTheme(settings: Settings | null | undefined): "light" | "dark" {
  const systemDark = usePrefersDark();
  return resolveTheme(settings?.theme ?? cachedDesign().theme, systemDark);
}

export const THEME_LABELS: Record<Theme, string> = { light: "Hell", dark: "Dunkel", system: "System" };

export function nextTheme(theme: Theme): Theme {
  return theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
}
