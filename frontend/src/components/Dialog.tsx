// Modal dialog (rendered into <body>), ESC/backdrop to close, simple focus handling.
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useUi } from "../state/ui";
import { Button, cx } from "./ui";

interface DialogProps {
  open: boolean;
  title: ReactNode;
  onClose(): void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function Dialog({ open, title, onClose, children, footer, size = "md", className }: DialogProps) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
      }
    };
    window.addEventListener("keydown", onKey, true);
    const t = window.setTimeout(() => {
      const el = panel.current?.querySelector<HTMLElement>("[autofocus], input, select, textarea, button.btn-accent, button");
      el?.focus();
    }, 20);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.clearTimeout(t);
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} className={cx("dialog", `dialog-${size}`, className)} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <header className="dialog-head">
          <h2 className="dialog-title">{title}</h2>
          <button type="button" className="dialog-close" aria-label="Schließen" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/** Renders the promise based confirm dialogs requested through `confirmDialog()`. */
export function ConfirmHost() {
  const req = useUi((s) => s.confirmRequest);
  if (!req) return null;
  return (
    <Dialog
      open
      size="sm"
      title={req.title}
      onClose={() => req.resolve(false)}
      footer={
        <>
          <Button variant={req.danger ? "danger" : "accent"} onClick={() => req.resolve(true)}>
            {req.confirmLabel ?? "OK"}
          </Button>
          <Button onClick={() => req.resolve(false)}>{req.cancelLabel ?? "Abbrechen"}</Button>
        </>
      }
    >
      {req.message && <p className="dialog-message">{req.message}</p>}
    </Dialog>
  );
}
