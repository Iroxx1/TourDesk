// Renders all open windows; on phones only the top-most one (full screen) with back-button support.
import { useEffect, useRef } from "react";
import { useIsMobile } from "../lib/useMediaQuery";
import { topWindow, useWindows } from "../state/windows";
import { WindowFrame } from "./WindowFrame";

export function WindowLayer() {
  const windows = useWindows((s) => s.windows);
  const mobile = useIsMobile();
  const top = topWindow(windows);
  const pushed = useRef<string[]>([]);

  // keep windows inside the viewport when the browser is resized
  useEffect(() => {
    let t = 0;
    const onResize = () => {
      window.clearTimeout(t);
      t = window.setTimeout(() => useWindows.getState().clampAll(), 150);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      window.clearTimeout(t);
    };
  }, []);

  // phones: every opened window gets a history entry so the system back button closes it
  useEffect(() => {
    if (!mobile) {
      pushed.current = [];
      return;
    }
    const open = windows.filter((w) => !w.minimized).map((w) => w.id);
    for (const id of open) {
      if (!pushed.current.includes(id)) {
        window.history.pushState({ tdWindow: id }, "");
        pushed.current.push(id);
      }
    }
    pushed.current = pushed.current.filter((id) => open.includes(id));
  }, [windows, mobile]);

  useEffect(() => {
    if (!mobile) return;
    const onPop = () => {
      const state = useWindows.getState();
      const t = topWindow(state.windows);
      if (t) {
        pushed.current = pushed.current.filter((id) => id !== t.id);
        state.close(t.id);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [mobile]);

  const mobileBack = () => {
    // use the history entry if we created one, so browser history stays consistent
    if (top && window.history.state?.tdWindow === top.id) window.history.back();
    else if (top) useWindows.getState().close(top.id);
  };

  const ordered = [...windows].sort((a, b) => (a.id < b.id ? -1 : 1));
  return (
    <div className="window-layer">
      {ordered.map((w) => (
        <WindowFrame key={w.id} win={w} active={top?.id === w.id} mobile={mobile} hidden={mobile && top?.id !== w.id} onMobileBack={mobileBack} />
      ))}
    </div>
  );
}
