// Künstlerkatalog: kleine Anzeige-Helfer (Bezeichnungen, Jahre, Land, Bild mit Initialen als Ersatz).
import { useState, type CSSProperties } from "react";
import type { CatalogEntry } from "../../api/types";
import { cx } from "../../components/ui";

const KIND_LABELS: Record<string, string> = {
  Group: "Band",
  Person: "Künstler/in",
  Orchestra: "Orchester",
  Choir: "Chor",
  Character: "Figur",
};

export function kindLabel(kind: string | null): string | null {
  if (!kind) return null;
  return KIND_LABELS[kind] ?? null;
}

let regionNames: Intl.DisplayNames | null = null;
export function countryName(code: string | null): string | null {
  if (!code) return null;
  try {
    regionNames ??= new Intl.DisplayNames(["de"], { type: "region" });
    return regionNames.of(code) ?? code;
  } catch {
    return code;
  }
}

/** „seit 2008“, „1964–1996“; bei Personen „geb. 1949“ bzw. „1942–2016“. */
export function yearsLabel(e: Pick<CatalogEntry, "kind" | "begin_year" | "end_year" | "ended">): string | null {
  if (!e.begin_year) return e.ended ? "aufgelöst" : null;
  if (e.end_year) return `${e.begin_year}–${e.end_year}`;
  if (e.kind === "Person") return `geb. ${e.begin_year}`;
  return `seit ${e.begin_year}`;
}

export function initials(name: string): string {
  const words = name.replace(/&/g, " ").split(/\s+/).filter((w) => /^[\p{L}\p{N}]/u.test(w));
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function hue(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) % 360;
  return h;
}

export function EntryImage({ entry, className }: { entry: Pick<CatalogEntry, "mbid" | "name" | "image">; className?: string }) {
  const [failed, setFailed] = useState(false);
  // Initialen liegen immer darunter; das Bild kommt erst, wenn der Server es schon gefunden hat
  return (
    <span className={cx("cat-photo", className)} style={{ "--cat-hue": hue(entry.name) } as CSSProperties}>
      <span className="cat-photo-initials" aria-hidden>
        {initials(entry.name)}
      </span>
      {entry.image === "ok" && !failed && (
        <img src={`/api/catalog/entries/${entry.mbid}/image`} alt="" decoding="async" onError={() => setFailed(true)} />
      )}
    </span>
  );
}
