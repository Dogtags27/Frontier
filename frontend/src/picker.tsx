import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useDebounced, useToken } from "./hooks";
import { Icon } from "./ui";

type Hit = { arxiv_id: string; title: string; year: number };

export function PaperPicker({
  value,
  onChange,
  onPick,
  placeholder = "Search by title or paste an arXiv id",
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  onPick: (hit: Hit) => void;
  placeholder?: string;
  id?: string;
}) {
  const token = useToken();
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const debounced = useDebounced(value, 240);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const text = debounced.trim();
    if (!token || text.length < 3) {
      setHits([]);
      return;
    }
    let live = true;
    api<{ items: Hit[] }>(`/vocab/suggest?kind=paper&q=${encodeURIComponent(text)}&limit=6`, token)
      .then((body) => live && setHits(body.items || []))
      .catch(() => live && setHits([]));
    return () => {
      live = false;
    };
  }, [debounced, token]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (host.current && !host.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function pick(hit: Hit) {
    onPick(hit);
    setOpen(false);
    setHits([]);
  }

  return (
    <div className="input-wrap" ref={host}>
      <Icon name="doc" />
      <input
        id={id}
        className="input"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setCursor(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (!open || !hits.length) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setCursor((current) => (current + 1) % hits.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setCursor((current) => (current - 1 + hits.length) % hits.length);
          } else if (event.key === "Enter") {
            event.preventDefault();
            pick(hits[cursor]);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && hits.length > 0 && (
        <div className="suggest" role="listbox">
          {hits.map((hit, index) => (
            <button key={hit.arxiv_id} type="button" className={index === cursor ? "on" : ""} onMouseEnter={() => setCursor(index)} onClick={() => pick(hit)}>
              <div className="clamp-2" style={{ fontWeight: 500 }}>
                {hit.title}
              </div>
              <div className="small faint">
                <span className="mono">{hit.arxiv_id}</span>
                {hit.year ? ` · ${hit.year}` : ""}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
