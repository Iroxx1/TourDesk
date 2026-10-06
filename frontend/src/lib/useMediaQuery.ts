import { useSyncExternalStore } from "react";

function subscribe(query: string) {
  return (cb: () => void) => {
    const mql = window.matchMedia(query);
    mql.addEventListener("change", cb);
    return () => mql.removeEventListener("change", cb);
  };
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    subscribe(query),
    () => window.matchMedia(query).matches,
    () => false,
  );
}

export const MOBILE_QUERY = "(max-width: 767px)";
export const useIsMobile = () => useMediaQuery(MOBILE_QUERY);
export const usePrefersDark = () => useMediaQuery("(prefers-color-scheme: dark)");
export const isMobileNow = () => window.matchMedia(MOBILE_QUERY).matches;
