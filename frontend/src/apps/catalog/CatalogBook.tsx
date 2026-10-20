// Künstlerkatalog als aufgeschlagenes Buch: Doppelseite (breit) bzw. Einzelseite (schmal), Umblättern mit
// 3D-Seitenumschlag (Ecke, Pfeiltasten, Wischen), Register A–Z (springt, man kann weiterblättern),
// Genre- und Herkunftsfilter. Ein Klick auf einen Eintrag öffnet die Karteikarte (CatalogDetail).
//
// Seitenfolge: Doppelseite 0 = Vorsatz | Titelseite, danach je zwei Katalogseiten. Die Position merkt sich
// „anchor“: -1 = Titel, sonst die Katalogseite (0-basiert) – so passt sie zu Doppel- und Einzelseite.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronLeft, ChevronRight, X } from "lucide-react";
import { catalogPageQuery, useCatalogMeta, useCatalogPage } from "../../api/hooks";
import type { CatalogEntry, CatalogMeta, CatalogOrigin, CatalogPage } from "../../api/types";
import { Segmented, cx } from "../../components/ui";
import { CatalogDetailCard } from "./CatalogDetail";
import { EntryImage, kindLabel, yearsLabel } from "./catalogFormat";

const LETTERS = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
const ORIGIN_OPTIONS: { value: CatalogOrigin; label: string }[] = [
  { value: "all", label: "Alle" },
  { value: "dach", label: "Deutschsprachig" },
  { value: "intl", label: "International" },
];
const ORIGIN_LABEL: Record<CatalogOrigin, string> = { all: "alle Herkünfte", dach: "deutschsprachig", intl: "international" };
const TURN_MS = 720;
const OPEN_FLY_MS = 460;
const OPEN_COVER_DELAY = 360;
const OPEN_COVER_MS = 900;

// Position und Filter bleiben zwischen zwei Öffnungen erhalten (nur für diese Sitzung)
const memory: { genre: string; origin: CatalogOrigin; anchor: number } = { genre: "", origin: "all", anchor: -1 };

type Mode = "spread" | "single";
type Leaf = { kind: "endpaper" } | { kind: "title" } | { kind: "catalog"; index: number } | { kind: "end" } | { kind: "blank" };
interface Turn {
  from: number;
  to: number;
  dir: 1 | -1;
}

const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const spreadOf = (anchor: number) => (anchor < 0 ? 0 : 1 + Math.floor(anchor / 2));
const anchorOfSpread = (s: number) => (s <= 0 ? -1 : 2 * (s - 1));

function spreadLeaves(s: number, pages: number): [Leaf, Leaf] {
  if (s <= 0) return [{ kind: "endpaper" }, { kind: "title" }];
  const l = 2 * (s - 1);
  const left: Leaf = l < pages ? { kind: "catalog", index: l } : { kind: "end" };
  const right: Leaf = l + 1 < pages ? { kind: "catalog", index: l + 1 } : l < pages ? { kind: "end" } : { kind: "blank" };
  return [left, right];
}

function singleLeaf(anchor: number, pages: number): Leaf {
  if (anchor < 0) return { kind: "title" };
  return anchor < pages ? { kind: "catalog", index: anchor } : { kind: "end" };
}

function leafKey(leaf: Leaf): string {
  return leaf.kind === "catalog" ? `c${leaf.index}` : leaf.kind;
}

const fmtNumber = (n: number) => n.toLocaleString("de-DE");

function editionLabel(meta: CatalogMeta | undefined): string {
  if (!meta?.imported_at) return "Erstausgabe";
  return `Ausgabe ${new Date(meta.imported_at).toLocaleDateString("de-DE", { month: "long", year: "numeric" })}`;
}

function shortName(sortName: string): string {
  const head = sortName.split(",")[0].trim();
  return head.length > 16 ? `${head.slice(0, 15)}…` : head;
}

// ------------------------------------------------------------------------------------------- Seiteninhalt
interface PageCtx {
  genre: string;
  origin: CatalogOrigin;
  genreLabel: string;
  meta: CatalogMeta | undefined;
  info: CatalogPage | undefined;
  cols: 1 | 2;
  mode: Mode;
  onPick(entry: CatalogEntry): void;
}

function CatalogLeaf({ index, side, ctx }: { index: number; side: "left" | "right" | "single"; ctx: PageCtx }) {
  const { data, isLoading } = useCatalogPage(ctx.genre, ctx.origin, index);
  const items = data?.items ?? [];
  const first = items[0];
  const last = items[items.length - 1];
  const slots = 12;
  const running = first && last ? `${shortName(first.sort_name)} – ${shortName(last.sort_name)}` : "";
  return (
    <>
      {first && (
        <span className="cat-watermark" aria-hidden>
          {first.letter}
        </span>
      )}
      <header className={cx("cat-head", side === "left" && "is-left")}>
        <span className="cat-head-run">{running}</span>
        <span className="cat-head-sel">{ctx.genreLabel}</span>
      </header>
      <div className={cx("cat-grid", `cols-${ctx.cols}`)}>
        {isLoading
          ? Array.from({ length: slots }, (_, i) => <span key={i} className="cat-entry is-skeleton" aria-hidden />)
          : Array.from({ length: slots }, (_, i) => {
              const e = items[i];
              if (!e) return <span key={`empty-${i}`} className="cat-entry is-empty" aria-hidden />;
              const prev = items[i - 1];
              const firstOfLetter = (prev ? prev.letter !== e.letter : data?.letters[e.letter] === index) && ctx.cols === 2;
              const meta = [kindLabel(e.kind), e.country, yearsLabel(e)].filter(Boolean).join(" · ");
              return (
                <button
                  key={e.mbid}
                  type="button"
                  className={cx("cat-entry", e.followed && "is-followed")}
                  onClick={() => ctx.onPick(e)}
                  aria-label={`${e.name}${meta ? `, ${meta}` : ""}${e.followed ? ", wird überwacht" : ""} – Details öffnen`}
                >
                  {firstOfLetter && (
                    <span className="cat-entry-letter" aria-hidden>
                      {e.letter}
                    </span>
                  )}
                  <EntryImage entry={e} className="cat-entry-photo" />
                  <span className="cat-entry-text">
                    <span className="cat-entry-name">{e.name}</span>
                    {meta && <span className="cat-entry-meta">{meta}</span>}
                    {e.genres.length > 0 && <span className="cat-entry-genres">{e.genres.slice(0, 2).join(" · ")}</span>}
                  </span>
                  {e.followed && (
                    <span className="cat-stamp" aria-hidden>
                      ✓ überwacht
                    </span>
                  )}
                </button>
              );
            })}
      </div>
      <footer className={cx("cat-foot", side === "left" && "is-left")}>
        <span className="cat-foot-num">{index + 2}</span>
        <span>TourDesk · Künstlerkatalog</span>
      </footer>
    </>
  );
}

function TitleLeaf({ ctx }: { ctx: PageCtx }) {
  const { meta, info } = ctx;
  const building = meta && (!meta.ready || meta.importing);
  return (
    <div className="cat-title">
      <span className="cat-title-brand">TourDesk</span>
      <h1 className="cat-title-main">Künstler&shy;katalog</h1>
      <span className="cat-title-orn" aria-hidden>
        ❦
      </span>
      <span className="cat-title-edition">{editionLabel(meta)}</span>
      {info && meta?.ready && (
        <p className="cat-title-sel">
          {ctx.genreLabel} · {ORIGIN_LABEL[ctx.origin]}
          <br />
          {info.total ? `${fmtNumber(info.total)} Künstler auf ${fmtNumber(info.pages)} Seiten` : "Keine Künstler in dieser Auswahl"}
        </p>
      )}
      {building && meta && (
        <div className="cat-title-build" role="status">
          <span>
            {meta.ready ? "Der Katalog wird gerade ergänzt" : "Der Katalog wird gerade aufgebaut"} – {meta.progress.done} von {meta.progress.total} Genres
          </span>
          <span className="cat-title-bar">
            <span style={{ width: `${Math.round((meta.progress.done / Math.max(1, meta.progress.total)) * 100)}%` }} />
          </span>
        </div>
      )}
      {!building && meta && meta.images?.pending > 0 && meta.total > 0 && (
        <div className="cat-title-build" role="status">
          <span>
            Künstlerbilder werden gesammelt – {fmtNumber(meta.total - meta.images.pending)} von {fmtNumber(meta.total)}
          </span>
          <span className="cat-title-bar">
            <span style={{ width: `${Math.round(((meta.total - meta.images.pending) / meta.total) * 100)}%` }} />
          </span>
        </div>
      )}
      <p className="cat-title-hint">
        {ctx.mode === "spread" ? "Register am Rand" : "Buchstaben oben"}: zum Buchstaben springen · {ctx.mode === "spread" ? "Ecke anklicken, Pfeiltasten oder Wischen" : "Wischen oder Pfeile unten"}: umblättern · Eintrag antippen: Details
      </p>
    </div>
  );
}

function Endpaper({ withPlate = true }: { withPlate?: boolean }) {
  return (
    <div className="cat-endpaper">
      {withPlate && (
        <div className="cat-plate">
          <span>Ex Libris</span>
          <strong>TourDesk</strong>
          <small>Konzerte & Tourtermine</small>
        </div>
      )}
    </div>
  );
}

function LeafContent({ leaf, side, ctx }: { leaf: Leaf; side: "left" | "right" | "single"; ctx: PageCtx }) {
  switch (leaf.kind) {
    case "endpaper":
      return <Endpaper />;
    case "title":
      return <TitleLeaf ctx={ctx} />;
    case "catalog":
      return <CatalogLeaf index={leaf.index} side={side} ctx={ctx} />;
    case "end":
      return (
        <div className="cat-endpage">
          <span className="cat-title-orn" aria-hidden>
            ❦
          </span>
          <strong>Ende des Katalogs</strong>
          <p>Nicht dabei? Über die Suche findest du jeden Künstler bei MusicBrainz – oder lege ihn manuell an.</p>
        </div>
      );
    default:
      return null;
  }
}

function Page({ leaf, side, ctx, className }: { leaf: Leaf; side: "left" | "right" | "single"; ctx: PageCtx; className?: string }) {
  return (
    <div className={cx("cat-page", `is-${side}`, leaf.kind === "endpaper" && "is-endpaper", className)} data-leaf={leafKey(leaf)}>
      <LeafContent leaf={leaf} side={side} ctx={ctx} />
    </div>
  );
}

function Cover() {
  return (
    <div className="cat-cover-face">
      <span className="cat-cover-brand">TourDesk</span>
      <span className="cat-cover-title">Künstler&shy;katalog</span>
      <span className="cat-cover-sub">A – Z</span>
    </div>
  );
}

// ------------------------------------------------------------------------------------------- Overlay
interface Props {
  originRect: DOMRect | null;
  onClose(): void;
}

export function CatalogBook({ originRect, onClose }: Props) {
  const qc = useQueryClient();
  const meta = useCatalogMeta();
  const [genre, setGenre] = useState(memory.genre);
  const [origin, setOrigin] = useState<CatalogOrigin>(memory.origin);
  const [anchor, setAnchor] = useState(memory.anchor);
  const [turn, setTurn] = useState<Turn | null>(null);
  const [picked, setPicked] = useState<CatalogEntry | null>(null);
  const [phase, setPhase] = useState<"opening" | "open" | "closing">(prefersReducedMotion() ? "open" : "opening");
  const [pendingLetter, setPendingLetter] = useState<string | null | undefined>(undefined);
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const stageRef = useRef<HTMLDivElement>(null);
  const bookRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const swipe = useRef<{ x: number; y: number; id: number } | null>(null);
  const suppressClick = useRef(false);

  const first = useCatalogPage(genre, origin, 0);
  const info = first.data;
  // solange die erste Seite einer neuen Auswahl lädt, Platzhalterseiten statt „Ende des Katalogs“ zeigen
  const pages = info ? (info.total ? info.pages : 0) : Math.max(2, anchor + 4);
  const genreLabel = meta.data?.genres.find((g) => g.key === genre)?.label ?? "Alle Genres";

  // ---- Größe der Bühne → Doppel- oder Einzelseite, Seitenmaße und Schriftgröße
  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const measure = () => setStage({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => {
    const { w, h } = stage;
    const spreadH = Math.min(h - 56, ((w - 2 * 76 - 40) / 2) / 0.72, 860);
    const spreadW = spreadH * 0.72;
    if (w >= 880 && h >= 460 && spreadW >= 320) {
      return { mode: "spread" as Mode, pw: Math.floor(spreadW), ph: Math.floor(spreadH), font: Math.max(10.5, spreadW / 34), cols: 2 as const };
    }
    const pw = Math.floor(Math.min(w - 20, 640));
    const ph = Math.floor(Math.min(h - 22, pw * 1.75));
    return { mode: "single" as Mode, pw, ph, font: Math.max(12, Math.min(16, pw / 30)), cols: (pw >= 520 ? 2 : 1) as 1 | 2 };
  }, [stage]);
  const mode = geo.mode;

  // ---- Navigation
  const maxAnchor = mode === "spread" ? anchorOfSpread(1 + Math.ceil(pages / 2) - 1) : pages > 0 ? pages : -1;
  const lastSpread = Math.ceil(pages / 2);
  const leavesFor = useCallback(
    (a: number): Leaf[] => (mode === "spread" ? spreadLeaves(spreadOf(a), pages) : [singleLeaf(a, pages)]),
    [mode, pages],
  );

  const turnTo = useCallback(
    async (target: number, dir: 1 | -1) => {
      if (turn || phase === "closing") return;
      // wer während des Aufschlagens schon blättert oder springt, soll nicht warten müssen
      if (phase === "opening") setPhase("open");
      // Zielseiten vorher laden, damit beim Umblättern kein leeres Blatt erscheint
      const needed = leavesFor(target).filter((l): l is { kind: "catalog"; index: number } => l.kind === "catalog");
      await Promise.race([
        Promise.all(needed.map((l) => qc.ensureQueryData(catalogPageQuery(genre, origin, l.index)))).catch(() => undefined),
        new Promise((r) => window.setTimeout(r, 1500)),
      ]);
      if (prefersReducedMotion()) {
        setAnchor(target);
        return;
      }
      setTurn({ from: anchor, to: target, dir });
    },
    [turn, phase, leavesFor, qc, genre, origin, anchor],
  );

  const canPrev = mode === "spread" ? spreadOf(anchor) > 0 : anchor > -1;
  const canNext = mode === "spread" ? spreadOf(anchor) < lastSpread : anchor < maxAnchor;
  const next = useCallback(() => {
    if (!canNext) return;
    void turnTo(mode === "spread" ? anchorOfSpread(spreadOf(anchor) + 1) : anchor + 1, 1);
  }, [canNext, turnTo, mode, anchor]);
  const prev = useCallback(() => {
    if (!canPrev) return;
    void turnTo(mode === "spread" ? anchorOfSpread(spreadOf(anchor) - 1) : anchor - 1, -1);
  }, [canPrev, turnTo, mode, anchor]);

  const jumpToPage = useCallback(
    (page: number) => {
      const target = mode === "spread" ? anchorOfSpread(spreadOf(page)) : page;
      const same = mode === "spread" ? spreadOf(target) === spreadOf(anchor) : target === anchor;
      if (same) return;
      void turnTo(target, target > anchor ? 1 : -1);
    },
    [mode, anchor, turnTo],
  );

  // ändert sich der Katalog (Import läuft), stimmen Seiten und Register nicht mehr → neu laden
  const knownTotal = useRef<number | null>(null);
  useEffect(() => {
    const total = meta.data?.total;
    if (total === undefined) return;
    if (knownTotal.current !== null && knownTotal.current !== total) void qc.invalidateQueries({ queryKey: ["catalog", "page"] });
    knownTotal.current = total;
  }, [meta.data?.total, qc]);

  // Position merken; nach Filterwechsel oder Moduswechsel gültig halten
  useEffect(() => {
    memory.anchor = anchor;
  }, [anchor]);
  useEffect(() => {
    if (!info || pendingLetter !== undefined) return;
    if (anchor > maxAnchor) setAnchor(maxAnchor);
  }, [info, anchor, maxAnchor, pendingLetter]);

  // Buchstabe der aufgeschlagenen Seiten (Register, Filterwechsel): der zuletzt angeklickte, solange er
  // zu sehen ist, sonst der des ersten Eintrags
  const visibleIdx = (mode === "spread" ? spreadLeaves(spreadOf(anchor), pages) : [singleLeaf(anchor, pages)])
    .filter((l): l is { kind: "catalog"; index: number } => l.kind === "catalog")
    .map((l) => l.index);
  const pageA = useCatalogPage(genre, origin, visibleIdx[0] ?? -1, visibleIdx[0] !== undefined);
  const pageB = useCatalogPage(genre, origin, visibleIdx[1] ?? -1, visibleIdx[1] !== undefined);
  const [jumpLetter, setJumpLetter] = useState<string | null>(null);
  const visibleLetters = new Set([...(pageA.data?.items ?? []), ...(pageB.data?.items ?? [])].map((i) => i.letter));
  const firstLetter = visibleIdx.length ? pageA.data?.items[0]?.letter ?? null : null;
  const currentLetter = jumpLetter && visibleLetters.has(jumpLetter) ? jumpLetter : firstLetter;
  const jumpToLetter = async (letter: string) => {
    let letters = info?.letters;
    // läuft gerade ein Import, verschieben sich die Seiten laufend: Register vorher frisch holen
    if (meta.data?.importing || !meta.data?.ready) {
      const fresh = await qc.fetchQuery({ ...catalogPageQuery(genre, origin, 0), staleTime: 0 }).catch(() => undefined);
      if (fresh) {
        if (info && fresh.total !== info.total) await qc.invalidateQueries({ queryKey: ["catalog", "page"] });
        letters = fresh.letters;
      }
    }
    const page = letters?.[letter];
    if (page === null || page === undefined) return;
    setJumpLetter(letter);
    jumpToPage(page);
  };

  const changeFilter = (nextGenre: string, nextOrigin: CatalogOrigin) => {
    memory.genre = nextGenre;
    memory.origin = nextOrigin;
    setPendingLetter(currentLetter);
    setGenre(nextGenre);
    setOrigin(nextOrigin);
  };
  // nach dem Filterwechsel beim selben Buchstaben aufschlagen (oder dem nächsten vorhandenen)
  useEffect(() => {
    if (pendingLetter === undefined || !info || first.isPlaceholderData) return;
    let target = -1;
    if (pendingLetter && info.total) {
      const start = LETTERS.indexOf(pendingLetter);
      const hit = LETTERS.slice(Math.max(0, start)).find((l) => info.letters[l] !== null && info.letters[l] !== undefined);
      if (hit) target = info.letters[hit] as number;
    }
    setAnchor(mode === "spread" && target >= 0 ? anchorOfSpread(spreadOf(target)) : target);
    setPendingLetter(undefined);
  }, [pendingLetter, info, first.isPlaceholderData, mode]);

  // Nachbarseiten vorladen
  useEffect(() => {
    if (!pages) return;
    const around = mode === "spread" ? [anchor - 2, anchor - 1, anchor + 2, anchor + 3] : [anchor - 1, anchor + 1, anchor + 2];
    for (const p of around) if (p >= 0 && p < pages) void qc.prefetchQuery(catalogPageQuery(genre, origin, p));
  }, [anchor, pages, mode, genre, origin, qc]);

  // ---- Öffnen (Buch fliegt aus dem Knopf, Deckel schlägt auf) und Schließen
  useLayoutEffect(() => {
    if (phase !== "opening") return;
    const book = bookRef.current;
    if (!book || !stage.w) return;
    const target = (book.querySelector(mode === "spread" ? ".cat-page.is-right" : ".cat-page") as HTMLElement | null)?.getBoundingClientRect();
    if (originRect && target && target.width) {
      const s = Math.max(0.06, originRect.height / target.height);
      const dx = originRect.left + originRect.width / 2 - (target.left + target.width / 2);
      const dy = originRect.top + originRect.height / 2 - (target.top + target.height / 2);
      book.animate(
        [
          { transform: `translate(${dx}px, ${dy}px) scale(${s})`, opacity: 0.4 },
          { transform: "none", opacity: 1 },
        ],
        { duration: OPEN_FLY_MS, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
    }
    const t = window.setTimeout(() => setPhase("open"), OPEN_COVER_DELAY + OPEN_COVER_MS);
    return () => window.clearTimeout(t);
    // nur einmal beim Öffnen, sobald die Bühne vermessen ist
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage.w > 0]);

  const close = useCallback(() => {
    if (phase === "closing") return;
    if (prefersReducedMotion()) {
      onClose();
      return;
    }
    setPhase("closing");
    window.setTimeout(onClose, 230);
  }, [phase, onClose]);

  // ---- Tastatur
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (picked) setPicked(null);
        else close();
        return;
      }
      if (picked) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        prev();
      } else if (e.key === "Home") {
        e.preventDefault();
        if (anchor !== -1) void turnTo(-1, -1);
      } else if (e.key === "End") {
        e.preventDefault();
        if (anchor !== maxAnchor) void turnTo(maxAnchor, 1);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [picked, close, next, prev, anchor, maxAnchor, turnTo]);

  useEffect(() => {
    overlayRef.current?.focus();
  }, []);

  // ---- Wischen
  const onPointerDown = (e: ReactPointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    swipe.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
  };
  const onPointerUp = (e: ReactPointerEvent) => {
    const s = swipe.current;
    swipe.current = null;
    if (!s || s.id !== e.pointerId) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) > 56 && Math.abs(dx) > Math.abs(dy) * 1.4) {
      suppressClick.current = true;
      window.setTimeout(() => (suppressClick.current = false), 0);
      if (dx < 0) next();
      else prev();
    }
  };

  // ---- Darstellung
  const ctx: PageCtx = { genre, origin, genreLabel, meta: meta.data, info, cols: geo.cols, mode, onPick: setPicked };
  const style = { "--pw": `${geo.pw}px`, "--ph": `${geo.ph}px`, "--turn-ms": `${TURN_MS}ms`, fontSize: `${geo.font}px` } as CSSProperties;
  const shown = turn ? turn.from : anchor;
  const finishTurn = () => {
    if (!turn) return;
    setAnchor(turn.to);
    setTurn(null);
  };

  let book: ReactNode;
  if (mode === "spread") {
    const [l0, r0] = spreadLeaves(spreadOf(shown), pages);
    const [l1, r1] = turn ? spreadLeaves(spreadOf(turn.to), pages) : [l0, r0];
    const underLeft = turn?.dir === -1 ? l1 : l0;
    const underRight = turn?.dir === 1 ? r1 : r0;
    book = (
      <>
        <div className="cat-board is-left" />
        <div className="cat-board is-right" />
        <Page leaf={underLeft} side="left" ctx={ctx} />
        <Page leaf={underRight} side="right" ctx={ctx} />
        <div className="cat-gutter" aria-hidden />
        {turn && (
          <div className={cx("cat-leaf", turn.dir === 1 ? "turn-next" : "turn-prev")} onAnimationEnd={finishTurn} aria-hidden>
            <div className="cat-face is-front">
              <Page leaf={turn.dir === 1 ? r0 : l0} side={turn.dir === 1 ? "right" : "left"} ctx={ctx} />
            </div>
            <div className="cat-face is-back">
              <Page leaf={turn.dir === 1 ? l1 : r1} side={turn.dir === 1 ? "left" : "right"} ctx={ctx} />
            </div>
          </div>
        )}
        {phase === "opening" && (
          <div className="cat-leaf cat-cover turn-next" aria-hidden>
            <div className="cat-face is-front">
              <Cover />
            </div>
            <div className="cat-face is-back">
              <div className="cat-page is-left is-endpaper">
                <Endpaper withPlate={false} />
              </div>
            </div>
          </div>
        )}
        {!turn && canNext && (
          <button type="button" className="cat-corner is-next" aria-label="Umblättern" onClick={next}>
            <span />
          </button>
        )}
        {!turn && canPrev && (
          <button type="button" className="cat-corner is-prev" aria-label="Zurückblättern" onClick={prev}>
            <span />
          </button>
        )}
        <nav className="cat-register" aria-label="Register">
          {LETTERS.map((l) => {
            const page = info?.letters[l];
            return (
              <button
                key={l}
                type="button"
                className={cx("cat-tab", l === currentLetter && "is-active")}
                disabled={page === null || page === undefined || !pages}
                onClick={() => jumpToLetter(l)}
                aria-label={l === "#" ? "Ziffern und Sonderzeichen" : `Buchstabe ${l}`}
              >
                {l}
              </button>
            );
          })}
        </nav>
      </>
    );
  } else {
    const current = singleLeaf(shown, pages);
    const target = turn ? singleLeaf(turn.to, pages) : current;
    book = (
      <>
        <div className="cat-board is-single" />
        <Page leaf={turn?.dir === 1 ? target : current} side="single" ctx={ctx} />
        {turn && (
          <div className={cx("cat-leaf", "is-single", turn.dir === 1 ? "turn-next" : "turn-in")} onAnimationEnd={finishTurn} aria-hidden>
            <div className="cat-face is-front">
              <Page leaf={turn.dir === 1 ? current : target} side="single" ctx={ctx} />
            </div>
            <div className="cat-face is-back">
              <div className="cat-page is-single is-paperback" />
            </div>
          </div>
        )}
        {phase === "opening" && (
          <div className="cat-leaf cat-cover is-single turn-next" aria-hidden>
            <div className="cat-face is-front">
              <Cover />
            </div>
            <div className="cat-face is-back">
              <div className="cat-page is-single is-endpaper">
                <Endpaper withPlate={false} />
              </div>
            </div>
          </div>
        )}
        {!turn && canNext && (
          <button type="button" className="cat-corner is-next" aria-label="Umblättern" onClick={next}>
            <span />
          </button>
        )}
      </>
    );
  }

  const pageLabel = (() => {
    if (!info || !pages) return "";
    if (mode === "spread") {
      const s = spreadOf(anchor);
      if (s === 0) return `Titel · ${fmtNumber(pages)} Seiten`;
      const a = 2 * (s - 1) + 2;
      return `Seite ${a}${2 * (s - 1) + 1 < pages ? `–${a + 1}` : ""} von ${fmtNumber(pages + 1)}`;
    }
    return anchor < 0 ? `Titel · ${fmtNumber(pages)} Seiten` : `Seite ${Math.min(anchor, pages - 1) + 2} von ${fmtNumber(pages + 1)}`;
  })();

  return createPortal(
    <div
      ref={overlayRef}
      className={cx("cat-overlay", `phase-${phase}`, `mode-${mode}`)}
      role="dialog"
      aria-modal="true"
      aria-label="Künstlerkatalog"
      tabIndex={-1}
    >
      <div className="cat-toolbar">
        <div className="cat-toolbar-title">
          <BookOpen size={20} aria-hidden /> Künstlerkatalog
        </div>
        <label className="cat-select-wrap">
          <span className="sr-only">Genre</span>
          <select className="cat-select" value={genre} onChange={(e) => changeFilter(e.target.value, origin)} aria-label="Genre">
            <option value="">Alle Genres{meta.data ? ` (${fmtNumber(meta.data.total)})` : ""}</option>
            {meta.data?.genres.map((g) => (
              <option key={g.key} value={g.key} disabled={!g.count}>
                {g.label} ({fmtNumber(g.count)})
              </option>
            ))}
          </select>
        </label>
        <Segmented<CatalogOrigin> className="cat-origin" label="Herkunft" value={origin} onChange={(o) => changeFilter(genre, o)} options={ORIGIN_OPTIONS} />
        <span className="cat-indicator">{pageLabel}</span>
        <button type="button" className="cat-close" aria-label="Katalog schließen" onClick={close}>
          <X size={20} />
        </button>
      </div>
      {mode === "single" && (
        <nav className="cat-register-inline" aria-label="Register">
          {LETTERS.map((l) => {
            const page = info?.letters[l];
            return (
              <button
                key={l}
                type="button"
                className={cx(l === currentLetter && "is-active")}
                disabled={page === null || page === undefined || !pages}
                onClick={() => jumpToLetter(l)}
                aria-label={l === "#" ? "Ziffern und Sonderzeichen" : `Buchstabe ${l}`}
              >
                {l}
              </button>
            );
          })}
        </nav>
      )}
      <div
        ref={stageRef}
        className="cat-stage"
        onMouseDown={(e) => e.target === e.currentTarget && close()}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (swipe.current = null)}
        onClickCapture={(e) => {
          if (suppressClick.current) {
            e.stopPropagation();
            e.preventDefault();
          }
        }}
      >
        {stage.w > 0 && (
          <>
            {mode === "spread" && (
              <button type="button" className="cat-nav is-prev" aria-label="Vorherige Seite" onClick={prev} disabled={!canPrev || Boolean(turn)}>
                <ChevronLeft size={26} />
              </button>
            )}
            <div ref={bookRef} className={cx("cat-book", `mode-${mode}`, phase === "opening" && "is-opening", turn && "is-turning")} style={style}>
              {book}
            </div>
            {mode === "spread" && (
              <button type="button" className="cat-nav is-next" aria-label="Nächste Seite" onClick={next} disabled={!canNext || Boolean(turn)}>
                <ChevronRight size={26} />
              </button>
            )}
          </>
        )}
        {picked && <CatalogDetailCard entry={picked} onClose={() => setPicked(null)} />}
      </div>
      {mode === "single" && (
        <div className="cat-bottombar">
          <button type="button" className="cat-nav is-inline" aria-label="Vorherige Seite" onClick={prev} disabled={!canPrev || Boolean(turn)}>
            <ChevronLeft size={22} />
          </button>
          <span className="cat-indicator">{pageLabel}</span>
          <button type="button" className="cat-nav is-inline" aria-label="Nächste Seite" onClick={next} disabled={!canNext || Boolean(turn)}>
            <ChevronRight size={22} />
          </button>
        </div>
      )}
    </div>,
    document.body,
  );
}
