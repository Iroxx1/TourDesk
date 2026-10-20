// Festival switch for all followed artists (start page next to the status chips, artists window below the catalogue).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PartyPopper } from "lucide-react";
import { api, errorMessage } from "../api/client";
import { qk, useArtists } from "../api/hooks";
import { useSession } from "../auth/session";
import { toast } from "../state/ui";
import { cx } from "./ui";

export function FestivalSwitch({ variant = "chip" }: { variant?: "chip" | "panel" }) {
  const { data: artists } = useArtists();
  const { readOnly } = useSession();
  const qc = useQueryClient();
  const total = artists?.length ?? 0;
  const on = artists?.filter((a) => a.subscription?.show_festivals).length ?? 0;
  const all = total > 0 && on === total;
  const mixed = on > 0 && !all;
  const set = useMutation({
    // teilweise oder aus -> alle an, alle an -> alle aus
    mutationFn: () => api.post<{ show: boolean; changed: number }>("/api/artists/festivals", { show: !all }),
    onSuccess: (res) => {
      toast(res.show ? "Festivals bei allen Künstlern eingeschaltet" : "Festivals bei allen Künstlern ausgeschaltet", "success");
      qc.invalidateQueries({ queryKey: qk.artists });
      qc.invalidateQueries({ queryKey: qk.dashboard });
      qc.invalidateQueries({ queryKey: qk.filter });
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["artist"] });
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  if (!total) return null;
  const state = all ? "an" : mixed ? `${on} von ${total}` : "aus";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={all ? true : mixed ? "mixed" : false}
      className={cx("festival-switch", `festival-switch-${variant}`, variant === "chip" && "chip-stat", set.isPending && "is-busy")}
      disabled={readOnly || set.isPending}
      onClick={() => set.mutate()}
      title={all ? "Festivals bei allen Künstlern ausschalten" : "Festivals bei allen Künstlern einschalten"}
    >
      <PartyPopper size={15} aria-hidden />
      <span className="festival-switch-label">
        Festivals <span className="festival-switch-state">{state}</span>
      </span>
      <span className={cx("toggle", all && "is-on", mixed && "is-mixed")} aria-hidden>
        <span className="toggle-knob" />
      </span>
    </button>
  );
}
