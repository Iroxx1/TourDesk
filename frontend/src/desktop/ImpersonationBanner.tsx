// Clearly marks that an admin is looking at another user's desktop.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, LogOut } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Me } from "../api/types";
import { qk } from "../api/hooks";
import { useSession } from "../auth/session";
import { Button } from "../components/ui";
import { toast } from "../state/ui";
import { openApp, useWindows } from "../state/windows";

export function ImpersonationBanner() {
  const { me } = useSession();
  const qc = useQueryClient();
  const stop = useMutation({
    mutationFn: () => api.post<Me>("/api/admin/impersonation/stop"),
    onSuccess: (next) => {
      useWindows.getState().closeAll();
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(qk.me, next);
      openApp("admin", { section: "users", userId: me.user.id });
      toast("Benutzeransicht beendet", "success");
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  if (!me.impersonation) return null;
  const name = me.user.display_name || me.user.username;
  return (
    <div className="impersonation-banner" role="alert">
      <Eye size={18} aria-hidden />
      <div className="impersonation-text">
        <strong>Ansicht als Benutzer: {name}</strong>
        <span>
          Du siehst die Oberfläche von „{me.user.username}“ als Administrator „{me.impersonation.admin.username}“. Änderungen sind deaktiviert (nur Lesezugriff).
        </span>
      </div>
      <Button size="sm" variant="default" icon={<LogOut size={14} />} loading={stop.isPending} onClick={() => stop.mutate()}>
        Ansicht beenden
      </Button>
    </div>
  );
}
