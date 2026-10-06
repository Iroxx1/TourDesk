// A desktop window: title bar with drag & snap, resize handles, min/max/close.
import { Component, Suspense, useRef, useState, type ErrorInfo, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Copy, Minus, Square, X } from "lucide-react";
import { APPS, AppIcon } from "../apps/registry";
import { Button, Loading, cx } from "../components/ui";
import { mediaSrc } from "../lib/urls";
import { MIN_H, MIN_W, useWindows, type Rect, type WindowState } from "../state/windows";

type Snap = "max" | "left" | "right" | null;
type Dir = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
const DIRS: Dir[] = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
const TASKBAR = 48;

class WindowErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("TourDesk window crashed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="window-crash">
          <h3>Dieses Fenster hat einen Fehler verursacht.</h3>
          <p>{this.state.error.message}</p>
          <Button onClick={() => this.setState({ error: null })}>Erneut versuchen</Button>
        </div>
      );
    }
    return this.props.children;
  }
}

function desktopRect() {
  return { vw: window.innerWidth, vh: window.innerHeight - TASKBAR };
}

interface WindowFrameProps {
  win: WindowState;
  active: boolean;
  mobile: boolean;
  hidden: boolean;
  onMobileBack(): void;
}

export function WindowFrame({ win, active, mobile, hidden, onMobileBack }: WindowFrameProps) {
  const ref = useRef<HTMLElement>(null);
  const [snap, setSnap] = useState<Snap>(null);
  const def = APPS[win.kind];
  const AppComponent = def.component;
  const title = win.title || def.title;
  const iconSrc = mediaSrc(win.icon);
  const actions = useWindows.getState();

  const startDrag = (e: RPointerEvent<HTMLElement>) => {
    if (mobile || e.button !== 0) return;
    if ((e.target as HTMLElement).closest(".window-controls")) return;
    const el = ref.current;
    if (!el) return;
    actions.focus(win.id);
    const startX = e.clientX;
    const startY = e.clientY;
    let origin: Rect = { x: win.x, y: win.y, w: win.w, h: win.h };
    let maximized = win.maximized;
    let moved = false;
    let currentSnap: Snap = null;
    let last = origin;
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);

    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
      if (!moved) {
        moved = true;
        el.classList.add("is-dragging");
        document.body.classList.add("is-window-dragging");
      }
      if (maximized) {
        // restore from maximized, keep the grab point under the cursor
        const ratio = startX / window.innerWidth;
        origin = { ...origin, x: Math.round(ev.clientX - origin.w * ratio) - dx, y: -dy };
        maximized = false;
        el.classList.remove("is-maximized");
        el.style.width = `${origin.w}px`;
        el.style.height = `${origin.h}px`;
      }
      const { vw, vh } = desktopRect();
      const x = Math.min(Math.max(origin.x + dx, -origin.w + 120), vw - 120);
      const y = Math.min(Math.max(origin.y + dy, 0), vh - 40);
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      last = { ...origin, x, y };
      const nextSnap: Snap = ev.clientY <= 2 ? "max" : ev.clientX <= 2 ? "left" : ev.clientX >= window.innerWidth - 3 ? "right" : null;
      if (nextSnap !== currentSnap) {
        currentSnap = nextSnap;
        setSnap(nextSnap);
      }
    };
    const onUp = () => {
      target.releasePointerCapture?.(e.pointerId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      el.classList.remove("is-dragging");
      document.body.classList.remove("is-window-dragging");
      setSnap(null);
      if (!moved) return;
      const { vw, vh } = desktopRect();
      if (currentSnap === "max") {
        actions.setRect(win.id, { ...last, y: Math.max(8, last.y) }, true);
      } else if (currentSnap === "left") {
        actions.setRect(win.id, { x: 0, y: 0, w: Math.round(vw / 2), h: vh }, false);
      } else if (currentSnap === "right") {
        actions.setRect(win.id, { x: Math.round(vw / 2), y: 0, w: Math.round(vw / 2), h: vh }, false);
      } else {
        actions.setRect(win.id, last, false);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const startResize = (dir: Dir) => (e: RPointerEvent<HTMLDivElement>) => {
    if (mobile || e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const el = ref.current;
    if (!el) return;
    actions.focus(win.id);
    const startX = e.clientX;
    const startY = e.clientY;
    const o: Rect = { x: win.x, y: win.y, w: win.w, h: win.h };
    let last = o;
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    document.body.classList.add("is-window-dragging");
    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      let { x, y, w, h } = o;
      if (dir.includes("e")) w = Math.max(MIN_W, o.w + dx);
      if (dir.includes("s")) h = Math.max(MIN_H, o.h + dy);
      if (dir.includes("w")) {
        w = Math.max(MIN_W, o.w - dx);
        x = o.x + (o.w - w);
      }
      if (dir.includes("n")) {
        h = Math.max(MIN_H, o.h - dy);
        y = Math.max(0, o.y + (o.h - h));
        if (y === 0) h = o.y + o.h;
      }
      last = { x, y, w, h };
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
    };
    const onUp = () => {
      target.releasePointerCapture?.(e.pointerId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      document.body.classList.remove("is-window-dragging");
      actions.setRect(win.id, last, false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const maximized = win.maximized && !mobile;
  const style = mobile
    ? { zIndex: win.z }
    : maximized
      ? { zIndex: win.z }
      : { left: win.x, top: win.y, width: win.w, height: win.h, zIndex: win.z };

  return (
    <>
      <section
        ref={ref}
        className={cx(
          "window",
          active && "is-active",
          maximized && "is-maximized",
          mobile && "is-mobile",
          (win.minimized || hidden) && "is-hidden",
        )}
        style={style}
        role="dialog"
        aria-label={title}
        aria-hidden={win.minimized || hidden || undefined}
        onPointerDownCapture={() => !active && actions.focus(win.id)}
      >
        <header
          className="window-titlebar"
          onPointerDown={startDrag}
          onDoubleClick={(e) => {
            if (!mobile && !(e.target as HTMLElement).closest(".window-controls")) actions.toggleMaximize(win.id);
          }}
        >
          {mobile && (
            <button type="button" className="window-back" aria-label="Zurück" onClick={onMobileBack}>
              <ArrowLeft size={22} />
            </button>
          )}
          <span className="window-icon">
            {iconSrc ? <img src={iconSrc} alt="" draggable={false} /> : <AppIcon kind={win.kind} size={18} />}
          </span>
          <span className="window-title">{title}</span>
          {!mobile && (
            <div className="window-controls">
              <button type="button" className="wc wc-min" aria-label="Minimieren" title="Minimieren" onClick={() => actions.minimize(win.id)}>
                <Minus size={16} />
              </button>
              <button
                type="button"
                className="wc wc-max"
                aria-label={maximized ? "Verkleinern" : "Maximieren"}
                title={maximized ? "Verkleinern" : "Maximieren"}
                onClick={() => actions.toggleMaximize(win.id)}
              >
                {maximized ? <Copy size={13} className="flip-x" /> : <Square size={13} />}
              </button>
              <button type="button" className="wc wc-close" aria-label="Schließen" title="Schließen" onClick={() => actions.close(win.id)}>
                <X size={17} />
              </button>
            </div>
          )}
        </header>
        <div className="window-body">
          <WindowErrorBoundary>
            <Suspense fallback={<Loading />}>
              <AppComponent win={win} />
            </Suspense>
          </WindowErrorBoundary>
        </div>
        {!mobile && !maximized && DIRS.map((d) => <div key={d} className={`resize-handle rh-${d}`} onPointerDown={startResize(d)} />)}
      </section>
      {snap && createPortal(<div className={`snap-preview snap-${snap}`} aria-hidden />, document.body)}
    </>
  );
}
