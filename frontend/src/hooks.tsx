import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, errorText } from "./api";
import { useAuth } from "./auth";
import { Icon } from "./ui";

export function useToken() {
  const { session } = useAuth();
  return session?.access_token || "";
}

export function useFetch<T>(path: string | null) {
  const token = useToken();
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const has = Boolean(token);
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: Boolean(path) });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path || !has) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    let live = true;
    setState((prev) => ({ ...prev, loading: true, error: "" }));
    api<T>(path, tokenRef.current)
      .then((data) => live && setState({ data, error: "", loading: false }))
      .catch((err) => live && setState((prev) => ({ ...prev, error: errorText(err), loading: false })));
    return () => {
      live = false;
    };
  }, [path, has, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { ...state, reload };
}

type Toast = { id: number; text: string; tone: "ok" | "error" };
type ToastValue = { notify: (text: string, tone?: "ok" | "error") => void };

const ToastContext = createContext<ToastValue>({ notify: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const counter = useRef(0);

  const notify = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    counter.current += 1;
    const id = counter.current;
    setItems((prev) => [...prev, { id, text, tone }]);
    setTimeout(() => setItems((prev) => prev.filter((item) => item.id !== id)), 3600);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast ${item.tone === "error" ? "error" : ""}`}>
            <Icon name={item.tone === "error" ? "alert" : "check"} />
            {item.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext).notify;
}

export function useDebounced<T>(value: T, ms = 220) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
