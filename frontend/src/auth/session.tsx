import { createContext, useContext } from "react";
import type { Me } from "../api/types";

export interface SessionValue {
  me: Me;
  /** true while an admin is viewing another user's desktop (server rejects writes) */
  readOnly: boolean;
  logout(): Promise<void>;
}

export const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession outside of SessionContext");
  return value;
}
