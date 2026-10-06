// Window manager: open/focus/close/minimize/maximize, z-order and remembered geometry.
import { create } from "zustand";
import { readJson, writeJson } from "../lib/storage";

export type AppKind =
  | "artist"
  | "event"
  | "artists"
  | "agenda"
  | "filters"
  | "places"
  | "venues"
  | "settings"
  | "admin";

export type WinParams = Record<string, string | number | boolean | null | undefined>;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface WindowState extends Rect {
  id: string;
  kind: AppKind;
  params: WinParams;
  title: string;
  icon: string | null;
  z: number;
  minimized: boolean;
  maximized: boolean;
  /** bumps whenever the window is (re)opened with new params, lets apps react */
  nonce: number;
}

export interface OpenOptions {
  key?: string | number;
  params?: WinParams;
  title?: string;
  icon?: string | null;
  maximized?: boolean;
}

const DEFAULT_SIZE: Record<AppKind, { w: number; h: number }> = {
  artist: { w: 900, h: 700 },
  event: { w: 620, h: 700 },
  artists: { w: 860, h: 680 },
  agenda: { w: 860, h: 700 },
  filters: { w: 940, h: 720 },
  places: { w: 920, h: 660 },
  venues: { w: 900, h: 680 },
  settings: { w: 960, h: 700 },
  admin: { w: 1240, h: 800 },
};

export const MIN_W = 360;
export const MIN_H = 260;
const TASKBAR = 48;
const GEOMETRY_KEY = "td.win.geometry";

type GeometryCache = Partial<Record<AppKind, { w: number; h: number }>>;

function desktopSize() {
  return { vw: window.innerWidth, vh: Math.max(300, window.innerHeight - TASKBAR) };
}

export function clampRect(r: Rect): Rect {
  const { vw, vh } = desktopSize();
  const w = Math.max(Math.min(r.w, vw - 16), Math.min(MIN_W, vw));
  const h = Math.max(Math.min(r.h, vh - 16), Math.min(MIN_H, vh));
  // keep at least the title bar reachable
  const x = Math.min(Math.max(r.x, -w + 120), vw - 120);
  const y = Math.min(Math.max(r.y, 0), vh - 40);
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
}

function initialRect(kind: AppKind, existing: WindowState[]): Rect {
  const { vw, vh } = desktopSize();
  const remembered = readJson<GeometryCache>(GEOMETRY_KEY, {})[kind];
  const size = remembered ?? DEFAULT_SIZE[kind];
  const w = Math.min(size.w, vw - 32);
  const h = Math.min(size.h, vh - 32);
  const visible = existing.filter((win) => !win.minimized && !win.maximized);
  const step = 30;
  const n = visible.length % 8;
  const x = Math.max(16, Math.round((vw - w) / 2) - 90 + n * step);
  const y = Math.max(12, Math.round((vh - h) / 2) - 60 + n * step);
  return clampRect({ x, y, w, h });
}

function rememberSize(kind: AppKind, w: number, h: number) {
  const cache = readJson<GeometryCache>(GEOMETRY_KEY, {});
  cache[kind] = { w, h };
  writeJson(GEOMETRY_KEY, cache);
}

const SINGLETONS: AppKind[] = ["artists", "agenda", "filters", "places", "venues", "settings", "admin"];

export function windowId(kind: AppKind, key?: string | number): string {
  if (SINGLETONS.includes(kind) || key === undefined) return kind;
  return `${kind}:${key}`;
}

interface WindowStore {
  windows: WindowState[];
  z: number;
  openMaximized: boolean;
  setOpenMaximized(v: boolean): void;
  open(kind: AppKind, opts?: OpenOptions): string;
  focus(id: string): void;
  close(id: string): void;
  closeAll(): void;
  minimize(id: string): void;
  toggleMaximize(id: string): void;
  setRect(id: string, rect: Rect, maximized?: boolean): void;
  setMeta(id: string, meta: { title?: string; icon?: string | null }): void;
  showDesktop(): void;
  clampAll(): void;
}

export const useWindows = create<WindowStore>((set, get) => ({
  windows: [],
  z: 10,
  openMaximized: false,
  setOpenMaximized: (v) => set({ openMaximized: v }),

  open(kind, opts = {}) {
    const id = windowId(kind, opts.key);
    const state = get();
    const z = state.z + 1;
    const existing = state.windows.find((w) => w.id === id);
    if (existing) {
      set({
        z,
        windows: state.windows.map((w) =>
          w.id === id
            ? {
                ...w,
                z,
                minimized: false,
                params: opts.params ? { ...w.params, ...opts.params } : w.params,
                title: opts.title ?? w.title,
                icon: opts.icon !== undefined ? opts.icon : w.icon,
                nonce: w.nonce + 1,
              }
            : w,
        ),
      });
      return id;
    }
    const rect = initialRect(kind, state.windows);
    const win: WindowState = {
      id,
      kind,
      params: opts.params ?? {},
      title: opts.title ?? "",
      icon: opts.icon ?? null,
      ...rect,
      z,
      minimized: false,
      maximized: opts.maximized ?? state.openMaximized,
      nonce: 0,
    };
    set({ z, windows: [...state.windows, win] });
    return id;
  },

  focus(id) {
    const state = get();
    const target = state.windows.find((w) => w.id === id);
    if (!target) return;
    const top = topWindow(state.windows);
    if (top && top.id === id && !target.minimized) return;
    const z = state.z + 1;
    set({ z, windows: state.windows.map((w) => (w.id === id ? { ...w, z, minimized: false } : w)) });
  },

  close(id) {
    set((s) => ({ windows: s.windows.filter((w) => w.id !== id) }));
  },

  closeAll() {
    set({ windows: [] });
  },

  minimize(id) {
    set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, minimized: true } : w)) }));
  },

  toggleMaximize(id) {
    set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, maximized: !w.maximized } : w)) }));
  },

  setRect(id, rect, maximized) {
    const clamped = clampRect(rect);
    const win = get().windows.find((w) => w.id === id);
    if (win && (clamped.w !== win.w || clamped.h !== win.h)) rememberSize(win.kind, clamped.w, clamped.h);
    set((s) => ({
      windows: s.windows.map((w) => (w.id === id ? { ...w, ...clamped, maximized: maximized ?? w.maximized } : w)),
    }));
  },

  setMeta(id, meta) {
    set((s) => ({
      windows: s.windows.map((w) =>
        w.id === id
          ? { ...w, title: meta.title ?? w.title, icon: meta.icon !== undefined ? meta.icon : w.icon }
          : w,
      ),
    }));
  },

  showDesktop() {
    const s = get();
    const anyVisible = s.windows.some((w) => !w.minimized);
    set({ windows: s.windows.map((w) => ({ ...w, minimized: anyVisible })) });
  },

  clampAll() {
    set((s) => ({ windows: s.windows.map((w) => ({ ...w, ...clampRect(w) })) }));
  },
}));

export function topWindow(windows: WindowState[]): WindowState | null {
  let top: WindowState | null = null;
  for (const w of windows) {
    if (w.minimized) continue;
    if (!top || w.z > top.z) top = w;
  }
  return top;
}

export const useActiveWindowId = () => useWindows((s) => topWindow(s.windows)?.id ?? null);

// convenience openers ---------------------------------------------------------------
export const openArtist = (artistId: number, name?: string, icon?: string | null) =>
  useWindows.getState().open("artist", { key: artistId, params: { artistId }, title: name, icon });

export const openEvent = (eventId: number, opts: { title?: string; adminUserId?: number | null; admin?: boolean } = {}) =>
  useWindows.getState().open("event", {
    key: opts.admin ? `${eventId}:admin:${opts.adminUserId ?? ""}` : eventId,
    params: { eventId, admin: opts.admin ?? false, adminUserId: opts.adminUserId ?? null },
    title: opts.title,
  });

export const openApp = (kind: Exclude<AppKind, "artist" | "event">, params?: WinParams) =>
  useWindows.getState().open(kind, { params });
