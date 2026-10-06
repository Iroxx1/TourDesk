// Auth gate: first-run setup → login → forced password change → desktop.
import { useCallback, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, api, errorMessage, onAuthProblem, setCsrfToken } from "./api/client";
import { qk, useMe, useSetupStatus } from "./api/hooks";
import { LoginScreen, PasswordChangeScreen, SetupScreen } from "./auth/AuthScreens";
import { SessionContext, type SessionValue } from "./auth/session";
import { Logo } from "./components/Logo";
import { Button, Spinner } from "./components/ui";
import { Desktop } from "./desktop/Desktop";
import { useDesign } from "./lib/theme";
import { useUi } from "./state/ui";
import { useWindows } from "./state/windows";

function Splash({ error, retry }: { error?: unknown; retry?: () => void }) {
  return (
    <div className="splash">
      <Logo size={72} />
      {error ? (
        <div className="splash-error">
          <p>TourDesk ist gerade nicht erreichbar.</p>
          <p className="muted">{errorMessage(error)}</p>
          {retry && <Button onClick={retry}>Erneut versuchen</Button>}
        </div>
      ) : (
        <Spinner size={22} label="TourDesk wird geladen" />
      )}
    </div>
  );
}

export function App() {
  const qc = useQueryClient();
  const setup = useSetupStatus();
  const needsSetup = setup.data?.needs_setup ?? false;
  const me = useMe(setup.isSuccess && !needsSetup);
  const sessionExpired = useUi((s) => s.sessionExpired);
  useDesign(me.data?.settings);

  useEffect(() => {
    if (me.data) {
      setCsrfToken(me.data.csrf_token);
      if (useUi.getState().sessionExpired) useUi.getState().setSessionExpired(false);
    }
  }, [me.data]);

  useEffect(
    () =>
      onAuthProblem((status, detail) => {
        if (status === 401) {
          if (qc.getQueryData(qk.me)) {
            useUi.getState().setSessionExpired(true);
            useUi.getState().setFlyout(null);
            useWindows.getState().closeAll();
            qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "setup-status" });
          }
        } else if (detail === "password_change_required") {
          qc.invalidateQueries({ queryKey: qk.me });
        }
      }),
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* session may already be gone */
    }
    setCsrfToken(null);
    useUi.getState().setFlyout(null);
    useWindows.getState().closeAll();
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "setup-status" });
  }, [qc]);

  const session = useMemo<SessionValue | null>(
    () => (me.data ? { me: me.data, readOnly: Boolean(me.data.impersonation), logout } : null),
    [me.data, logout],
  );

  if (setup.isLoading) return <Splash />;
  if (setup.error) return <Splash error={setup.error} retry={() => setup.refetch()} />;
  if (needsSetup) return <SetupScreen allowed={Boolean(setup.data?.setup_allowed)} version={setup.data?.version} />;
  if (me.isLoading) return <Splash />;
  if (me.error) {
    if (me.error instanceof ApiError && me.error.status === 401) return <LoginScreen version={setup.data?.version} expired={sessionExpired} />;
    return <Splash error={me.error} retry={() => me.refetch()} />;
  }
  if (!session) return <LoginScreen version={setup.data?.version} expired={sessionExpired} />;
  if (session.me.user.must_change_password && !session.me.impersonation) return <PasswordChangeScreen me={session.me} onLogout={() => void logout()} />;
  return (
    <SessionContext.Provider value={session}>
      <Desktop />
    </SessionContext.Provider>
  );
}
