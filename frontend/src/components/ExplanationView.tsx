// "Warum wird dieses Event (nicht) angezeigt?"
import { Check, Info, X } from "lucide-react";
import type { Explanation } from "../api/types";
import { cx } from "./ui";

export function ExplanationView({ explanation, heading = true }: { explanation: Explanation; heading?: boolean }) {
  return (
    <div className={cx("explain", explanation.shown ? "is-shown" : "is-hidden")}>
      {heading && (
        <div className="explain-head">
          <span className="explain-state">{explanation.shown ? "Wird angezeigt" : "Wird nicht angezeigt"}</span>
          <strong>{explanation.title}</strong>
        </div>
      )}
      <ul className="explain-list">
        {explanation.checks.map((c, i) => (
          <li key={`${c.code}-${i}`} className={cx("explain-item", c.ok === true ? "is-ok" : c.ok === false ? "is-fail" : "is-note")}>
            <span className="explain-icon" aria-hidden>
              {c.ok === true ? <Check size={14} /> : c.ok === false ? <X size={14} /> : <Info size={14} />}
            </span>
            <span>{c.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
