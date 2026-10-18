import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { createClient } from "@supabase/supabase-js";
import { api, type User } from "./api";

const url = import.meta.env.VITE_SUPABASE_URL || "";
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY || "";
export const supabase = url && anon ? createClient(url, anon) : null;

type AuthValue = {
  session: Session | null;
  user: User | null;
  ready: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const tokenRef = useRef("");
  const userRef = useRef<User | null>(null);
  const sessionRef = useRef<Session | null>(null);

  async function load(next: Session | null) {
    tokenRef.current = next?.access_token || "";
    sessionRef.current = next;
    setSession(next);
    if (!next) {
      userRef.current = null;
      setUser(null);
      setReady(true);
      return;
    }
    try {
      const fresh = await api<User>("/me", next.access_token);
      const prev = userRef.current;
      userRef.current = prev && prev.id === fresh.id && JSON.stringify(prev) === JSON.stringify(fresh) ? prev : fresh;
      setUser(userRef.current);
    } catch {
      userRef.current = null;
      setUser(null);
    } finally {
      setReady(true);
    }
  }

  useEffect(() => {
    if (!supabase) {
      setReady(true);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      if ((data.session?.access_token || "") !== tokenRef.current || !sessionRef.current) void load(data.session);
    });
    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      const token = next?.access_token || "";
      if (token === tokenRef.current) return;
      if (next && userRef.current && event === "TOKEN_REFRESHED") {
        tokenRef.current = token;
        sessionRef.current = next;
        setSession(next);
        return;
      }
      if (!userRef.current) setReady(false);
      void load(next);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      session,
      user,
      ready,
      refresh: async () => load(sessionRef.current),
      signOut: async () => {
        await supabase?.auth.signOut();
      },
    }),
    [session, user, ready],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("auth missing");
  return value;
}
