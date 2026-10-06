// Only http(s) links may ever end up in an href (protects against javascript: URLs from crawled data).
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
  } catch {
    /* invalid */
  }
  return undefined;
}

export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** Same-origin media path (artist images, avatars). */
export function mediaSrc(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  return path.startsWith("/media/") ? path : undefined;
}

export const wallpaperUrl = (key: string, thumb = false) => `/wallpapers/${encodeURIComponent(key)}${thumb ? "-thumb" : ""}.webp`;
