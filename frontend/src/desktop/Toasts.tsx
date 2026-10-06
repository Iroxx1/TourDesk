import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useUi } from "../state/ui";
import { cx } from "../components/ui";

export function Toasts() {
  const toasts = useUi((s) => s.toasts);
  const dismiss = useUi((s) => s.dismissToast);
  if (!toasts.length) return null;
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => {
        const Icon = t.kind === "success" ? CheckCircle2 : t.kind === "error" ? AlertCircle : Info;
        return (
          <div key={t.id} className={cx("toast", `toast-${t.kind}`)} role={t.kind === "error" ? "alert" : "status"}>
            <Icon size={18} className="toast-icon" aria-hidden />
            <span className="toast-text">{t.message}</span>
            <button type="button" className="toast-close" aria-label="Schließen" onClick={() => dismiss(t.id)}>
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
