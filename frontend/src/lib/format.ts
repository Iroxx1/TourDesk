// German formatting helpers and display labels.
import type { EventStatus, EventType, TourEvent } from "../api/types";

const LOCALE = "de-DE";

/** Parse "YYYY-MM-DD" as a local calendar date (no timezone shift). */
export function parseDay(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function isoDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

const dateFmt = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit", year: "numeric" });
const dateShortFmt = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit" });
const weekdayShortFmt = new Intl.DateTimeFormat(LOCALE, { weekday: "short" });
const weekdayLongFmt = new Intl.DateTimeFormat(LOCALE, { weekday: "long" });
const monthShortFmt = new Intl.DateTimeFormat(LOCALE, { month: "short" });
const monthYearFmt = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" });
const longDateFmt = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });
const numberFmt = new Intl.NumberFormat(LOCALE);

export const fmtDate = (day: string | null | undefined) => (day ? dateFmt.format(parseDay(day)) : "–");
export const fmtDateShort = (day: string) => dateShortFmt.format(parseDay(day));
export const fmtWeekdayShort = (day: string) => weekdayShortFmt.format(parseDay(day)).replace(".", "");
export const fmtWeekday = (day: string) => weekdayLongFmt.format(parseDay(day));
export const fmtMonthShort = (day: string) => monthShortFmt.format(parseDay(day)).replace(".", "");
export const fmtMonthYear = (day: string) => monthYearFmt.format(parseDay(day));
export const fmtLongDate = (day: string) => longDateFmt.format(parseDay(day));
export const fmtNumber = (n: number | null | undefined) => (n === null || n === undefined ? "–" : numberFmt.format(n));

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : dateTimeFmt.format(d);
}

export function fmtClock(date: Date): string {
  return timeFmt.format(date);
}

/** "20:00:00" -> "20:00" */
export function fmtTime(value: string | null | undefined): string | null {
  if (!value) return null;
  return value.slice(0, 5);
}

export function fmtDateRange(start: string | null, end: string | null): string {
  if (!start) return "";
  if (!end || end === start) return fmtDate(start);
  const s = parseDay(start);
  const e = parseDay(end);
  if (s.getFullYear() === e.getFullYear()) return `${fmtDateShort(start)} – ${fmtDate(end)}`;
  return `${fmtDate(start)} – ${fmtDate(end)}`;
}

export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "noch nie";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "–";
  const diff = Math.round((now - t) / 1000);
  const future = diff < 0;
  const abs = Math.abs(diff);
  const wrap = (s: string) => (future ? `in ${s}` : `vor ${s}`);
  if (abs < 45) return future ? "gleich" : "gerade eben";
  if (abs < 3600) return wrap(`${Math.max(1, Math.round(abs / 60))} Min.`);
  if (abs < 86400) return wrap(`${Math.round(abs / 3600)} Std.`);
  const days = Math.round(abs / 86400);
  if (days === 1) return future ? "morgen" : "gestern";
  if (days < 30) return wrap(`${days} Tagen`);
  return fmtDateTime(iso);
}

/** Days from today until the given day (negative = past). */
export function daysUntil(day: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((parseDay(day).getTime() - today.getTime()) / 86400000);
}

export function fmtCountdown(day: string): string {
  const n = daysUntil(day);
  if (n === 0) return "heute";
  if (n === 1) return "morgen";
  if (n < 0) return n === -1 ? "gestern" : `vor ${-n} Tagen`;
  if (n < 60) return `in ${n} Tagen`;
  const months = Math.round(n / 30.4);
  return `in ${months} Monaten`;
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString(LOCALE, { maximumFractionDigits: i ? 1 : 0 })} ${units[i]}`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

export function greeting(date = new Date()): string {
  const h = date.getHours();
  if (h < 5) return "Gute Nacht";
  if (h < 11) return "Guten Morgen";
  if (h < 17) return "Hallo";
  if (h < 22) return "Guten Abend";
  return "Gute Nacht";
}

// ----------------------------------------------------------------------------- labels
export const EVENT_TYPE_LABELS: Record<EventType, string> = {
  concert: "Konzert",
  festival: "Festival",
  support: "Support-Act",
  special: "Special Event",
};

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  scheduled: "Geplant",
  cancelled: "Abgesagt",
  postponed: "Verschoben",
  rescheduled: "Neu terminiert",
};

export const TICKET_STATUS_LABELS: Record<string, string> = {
  unknown: "Ticketstatus unbekannt",
  available: "Tickets verfügbar",
  limited: "Wenige Tickets",
  sold_out: "Ausverkauft",
  not_on_sale: "Noch nicht im Verkauf",
  presale: "Vorverkauf",
  box_office: "Abendkasse",
  free: "Eintritt frei",
  cancelled: "Kein Verkauf",
};

export const CRAWL_STATUS_LABELS: Record<string, string> = {
  pending: "Wartet auf ersten Crawl",
  ok: "Erfolgreich",
  partial: "Teilweise erfolgreich",
  error: "Fehler",
  disabled: "Deaktiviert",
};

export const SOURCE_STATUS_LABELS: Record<string, string> = {
  new: "Neu",
  ok: "OK",
  warning: "Warnung",
  error: "Fehler",
  disabled: "Deaktiviert",
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "Wartend",
  running: "Läuft",
  succeeded: "Erfolgreich",
  partial: "Teilweise",
  failed: "Fehlgeschlagen",
  cancelled: "Abgebrochen",
};

export const RUN_STATUS_LABELS: Record<string, string> = {
  running: "Läuft",
  success: "Erfolgreich",
  partial: "Teilweise",
  failed: "Fehlgeschlagen",
};

export const JOB_TYPE_LABELS: Record<string, string> = {
  artist_crawl: "Künstler-Crawl",
  source_crawl: "Quellen-Crawl",
  artist_enrich: "Metadaten/Bild",
  source_check: "Quellenprüfung",
  maintenance: "Wartung",
};

export const TRIGGER_LABELS: Record<string, string> = {
  schedule: "Zeitplan",
  manual: "Manuell",
  new_artist: "Neuer Künstler",
  retry: "Wiederholung",
};

export const LEVEL_LABELS: Record<string, string> = {
  country: "Land",
  region: "Region",
  city: "Stadt",
  venue: "Veranstaltungsort",
};

export const SCOPE_LABELS: Record<string, string> = {
  artist: "Künstler",
  venue: "Veranstaltungsort",
  festival: "Festival",
  global: "Global",
};

export const ERROR_TYPE_LABELS: Record<string, string> = {
  http_error: "HTTP-Fehler",
  timeout: "Zeitüberschreitung",
  connection: "Verbindungsfehler",
  dns: "DNS-Fehler",
  tls: "TLS/SSL-Fehler",
  robots_blocked: "robots.txt",
  rate_limited: "Rate-Limit",
  too_large: "Antwort zu groß",
  ssrf_blocked: "Interne Adresse blockiert",
  parse_error: "Nicht auswertbar",
  no_events: "Keine Termine",
  config: "Konfiguration",
  auth: "Zugangsdaten",
  unsupported: "Nicht unterstützt",
  unknown: "Unbekannt",
};

export function placeLabel(e: Pick<TourEvent, "venue_name" | "city_name">): string {
  const parts = [e.venue_name, e.city_name].filter(Boolean) as string[];
  if (parts.length === 2 && parts[0].toLowerCase().includes(parts[1].toLowerCase())) return parts[0];
  return parts.join(", ") || "Ort unbekannt";
}

export function eventHeadline(e: TourEvent): string {
  if (e.event_type === "festival" && e.festival) return e.festival.name;
  return e.venue_name || e.city_name || e.title || "Termin";
}

export function eventSubline(e: TourEvent): string {
  const parts: string[] = [];
  if (e.event_type === "festival" && e.festival && e.venue_name && e.venue_name !== e.festival.name) parts.push(e.venue_name);
  if (e.city_name && (e.event_type === "festival" || e.venue_name)) parts.push(e.city_name);
  if (e.country && e.country.code) parts.push(e.country.code);
  return parts.join(" · ");
}

export function pluralize(n: number, one: string, many: string): string {
  return `${fmtNumber(n)} ${n === 1 ? one : many}`;
}

export function initials(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** Deterministic hue for fallback gradients. */
export function hueFor(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) % 360;
  return h;
}
