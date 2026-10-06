// Shell UI state: flyouts, toasts, confirm dialogs, expanded tiles.
import { create } from "zustand";

export type Flyout = "start" | "search" | "notifications" | "quick" | "artists" | null;

export interface Toast {
  id: number;
  kind: "info" | "success" | "error";
  message: string;
}

export interface ConfirmRequest {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}

interface UiStore {
  flyout: Flyout;
  searchQuery: string;
  toasts: Toast[];
  confirmRequest: ConfirmRequest | null;
  expandedTiles: Record<number, boolean>;
  sessionExpired: boolean;
  setFlyout(f: Flyout): void;
  toggleFlyout(f: Exclude<Flyout, null>): void;
  openSearch(q?: string): void;
  setSearchQuery(q: string): void;
  toast(message: string, kind?: Toast["kind"]): void;
  dismissToast(id: number): void;
  setConfirm(req: ConfirmRequest | null): void;
  toggleTile(id: number): void;
  setSessionExpired(v: boolean): void;
}

let toastId = 0;

export const useUi = create<UiStore>((set, get) => ({
  flyout: null,
  searchQuery: "",
  toasts: [],
  confirmRequest: null,
  expandedTiles: {},
  sessionExpired: false,
  setFlyout: (flyout) => set({ flyout }),
  toggleFlyout: (f) => set({ flyout: get().flyout === f ? null : f }),
  openSearch: (q) => set({ flyout: "search", searchQuery: q ?? get().searchQuery }),
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  toast(message, kind = "info") {
    const id = ++toastId;
    set({ toasts: [...get().toasts.slice(-3), { id, kind, message }] });
    window.setTimeout(() => get().dismissToast(id), kind === "error" ? 7000 : 4000);
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  setConfirm: (confirmRequest) => set({ confirmRequest }),
  toggleTile: (id) => set({ expandedTiles: { ...get().expandedTiles, [id]: !get().expandedTiles[id] } }),
  setSessionExpired: (sessionExpired) => set({ sessionExpired }),
}));

export const toast = (message: string, kind?: Toast["kind"]) => useUi.getState().toast(message, kind);

/** Promise based confirmation dialog: `if (await confirmDialog({...})) ...` */
export function confirmDialog(req: Omit<ConfirmRequest, "resolve">): Promise<boolean> {
  return new Promise((resolve) => {
    useUi.getState().setConfirm({
      ...req,
      resolve: (ok) => {
        useUi.getState().setConfirm(null);
        resolve(ok);
      },
    });
  });
}
