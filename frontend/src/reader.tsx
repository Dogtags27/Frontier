import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API, ApiError, api, type Facet, type Facets, type Neighbor, type Neighbors } from "./api";
import { useToken } from "./hooks";
import { Badge, Icon, Skeleton } from "./ui";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type Term = {
  kind: "task" | "method" | "dataset" | "metric" | "claim";
  name: string;
  slug?: string;
  hint?: string;
  tag?: string;
};

const MEANING: Record<Exclude<Term["kind"], "claim">, string> = {
  task: "A problem this paper works on. Other papers tackling the same task are linked in the graph.",
  method: "A technique this paper uses or proposes. Papers built on it share this node in the graph.",
  dataset: "A dataset this paper evaluates on or introduces. Papers using it are directly comparable.",
  metric: "A measure this paper reports. Use it to line results up against other papers.",
};

export type Claim = { id: string; kind: string; label: string; sentence: string };
export type OutlineItem = { id: string; text: string; level: number };

const KIND_HREF: Record<Term["kind"], string | null> = {
  task: "task",
  method: "method",
  dataset: "dataset",
  metric: "metric",
  claim: null,
};

export function termsFrom(facets?: Facets | null, claims: Claim[] = []): Term[] {
  const out: Term[] = [];
  const seen = new Set<string>();
  const push = (term: Term) => {
    const key = `${term.kind}:${term.name.toLowerCase()}`;
    if (term.name.trim().length < 3 || seen.has(key)) return;
    seen.add(key);
    out.push(term);
  };
  const groups: [keyof Facets, Term["kind"]][] = [
    ["tasks", "task"],
    ["methods", "method"],
    ["datasets", "dataset"],
    ["metrics", "metric"],
  ];
  for (const [key, kind] of groups) {
    for (const item of (facets?.[key] as Facet[] | undefined) || []) {
      push({ kind, name: item.name, slug: item.slug, hint: MEANING[kind as Exclude<Term["kind"], "claim">] });
    }
  }
  void claims;
  return out.sort((a, b) => b.name.length - a.name.length);
}

function squash(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function escapeRe(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const SKIP = "math, a, h1, h2, h3, h4, h5, h6, mark.term:not(.term-claim), .ltx_bibliography, .ltx_bibitem, .ltx_authors, .ltx_tag, .ltx_ERROR, pre, code";
const CLAIM_SKIP = "math, h1, h2, h3, h4, h5, h6, mark.term:not(.term-claim), .ltx_bibliography, .ltx_bibitem, .ltx_authors, .ltx_tag, .ltx_ERROR, .ltx_abstract .ltx_title, figure, table, pre";
const PER_TERM = 10;

type Slot = { node: Text; offset: number };

function textSlots(root: HTMLElement) {
  const slots: Slot[] = [];
  let chars = "";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !node.nodeValue) return NodeFilter.FILTER_REJECT;
      return parent.closest(CLAIM_SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const value = node.nodeValue || "";
    for (let i = 0; i < value.length; i += 1) {
      const ch = value[i].toLowerCase();
      if ((ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9")) {
        chars += ch;
        slots.push({ node, offset: i });
      }
    }
  }
  return { chars, slots };
}

function highlightClaim(root: HTMLElement, claim: Claim) {
  const sentence = (claim.sentence || "").trim();
  const needle = squash(sentence);
  if (needle.length < 24) return false;
  const { chars, slots } = textSlots(root);
  let start = -1;
  for (const size of [40, 28, 20]) {
    if (needle.length < size) continue;
    start = chars.indexOf(needle.slice(0, size));
    if (start >= 0) break;
  }
  if (start < 0) return false;
  let end = Math.min(start + needle.length, chars.length);
  if (needle.length >= 70) {
    const tail = needle.slice(-24);
    const at = chars.indexOf(tail, start + 24);
    if (at >= 0 && at - start <= needle.length * 1.7 + 60) end = at + tail.length;
  }
  end = Math.min(end, start + 1400, chars.length);
  const range = slots.slice(start, end);
  if (range.length < 16 || range.some((slot) => slot.node.parentElement?.closest("mark.term-claim"))) return false;
  const spans = new Map<Text, { from: number; to: number }>();
  for (const slot of range) {
    const found = spans.get(slot.node);
    if (found) found.to = slot.offset + 1;
    else spans.set(slot.node, { from: slot.offset, to: slot.offset + 1 });
  }
  const tag = claim.kind ? claim.kind.replace(/_/g, " ") : "claim";
  for (const [node, { from, to }] of spans) {
    const mid = from > 0 ? node.splitText(from) : node;
    if (to - from < mid.length) mid.splitText(to - from);
    const mark = document.createElement("mark");
    mark.className = "term term-claim";
    mark.tabIndex = 0;
    mark.dataset.kind = "claim";
    mark.dataset.name = claim.label || tag;
    mark.dataset.tag = tag;
    mark.dataset.hint = "A claim the graph extracted from this paper. This passage is where the authors make it.";
    mid.replaceWith(mark);
    mark.append(mid);
  }
  return true;
}

function annotate(root: HTMLElement, terms: Term[], claims: Claim[]) {
  for (const claim of claims) highlightClaim(root, claim);
  const usable = terms.filter((term) => term.kind !== "claim" && term.name.trim().length >= 3);
  if (usable.length) {
    const lookup = new Map<string, Term>();
    for (const term of usable) lookup.set(term.name.trim().toLowerCase(), term);
    const pattern = new RegExp(`(?<![A-Za-z0-9])(${usable.map((term) => escapeRe(term.name.trim())).join("|")})(?![A-Za-z0-9])`, "gi");
    const counts = new Map<string, number>();
    const nodes: Text[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || !node.nodeValue || node.nodeValue.trim().length < 3) return NodeFilter.FILTER_REJECT;
        return parent.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) nodes.push(walker.currentNode as Text);
    for (const node of nodes) {
      const text = node.nodeValue || "";
      pattern.lastIndex = 0;
      let match: RegExpExecArray | null;
      let last = 0;
      let fragment: DocumentFragment | null = null;
      while ((match = pattern.exec(text))) {
        const key = match[1].toLowerCase();
        const term = lookup.get(key);
        if (!term) continue;
        const used = counts.get(key) || 0;
        if (used >= PER_TERM) continue;
        counts.set(key, used + 1);
        fragment ||= document.createDocumentFragment();
        if (match.index > last) fragment.append(text.slice(last, match.index));
        const mark = document.createElement("mark");
        mark.className = `term term-${term.kind}`;
        mark.tabIndex = 0;
        mark.dataset.kind = term.kind;
        mark.dataset.name = term.name;
        if (term.slug) mark.dataset.slug = term.slug;
        if (term.hint) mark.dataset.hint = term.hint;
        mark.textContent = match[1];
        fragment.append(mark);
        last = match.index + match[1].length;
      }
      if (fragment) {
        if (last < text.length) fragment.append(text.slice(last));
        node.replaceWith(fragment);
      }
    }
  }
}

function outlineOf(root: HTMLElement): OutlineItem[] {
  const items: OutlineItem[] = [];
  root.querySelectorAll(".ltx_title_section, .ltx_title_appendix, .ltx_title_subsection, .ltx_title_bibliography").forEach((node) => {
    const section = node.closest("section");
    const id = section?.id || (node as HTMLElement).id;
    const text = (node.textContent || "").replace(/\s+/g, " ").trim();
    if (!id || !text) return;
    items.push({ id, text, level: node.classList.contains("ltx_title_subsection") ? 2 : 1 });
  });
  return items;
}

export function Tip({ term, x, y, onStay, onLeave }: { term: Term; x: number; y: number; onStay: () => void; onLeave: () => void }) {
  const hrefKind = KIND_HREF[term.kind];
  const href = hrefKind && term.slug ? `/papers?${hrefKind}=${encodeURIComponent(term.slug)}` : hrefKind ? `/papers?q=${encodeURIComponent(term.name)}` : null;
  const left = Math.max(8, Math.min(x, window.innerWidth - 280));
  const top = Math.min(y, window.innerHeight - 150);
  return (
    <div className="term-tip" style={{ left, top }} onMouseEnter={onStay} onMouseLeave={onLeave} role="tooltip">
      <div className="row" style={{ marginBottom: "0.35rem" }}>
        <Badge tone={term.kind === "claim" ? "accent" : "brand"}>{term.kind === "claim" ? `claim${term.tag && term.tag !== "claim" ? ` Â· ${term.tag}` : ""}` : term.kind}</Badge>
      </div>
      <strong>{term.name}</strong>
      {term.hint && <p>{term.hint}</p>}
      {href && (
        <Link to={href} onClick={onLeave}>
          Find papers with this {term.kind}
        </Link>
      )}
    </div>
  );
}

function useTip() {
  const [tip, setTip] = useState<{ term: Term; x: number; y: number } | null>(null);
  const hide = useRef(0);
  const stay = () => window.clearTimeout(hide.current);
  const leave = () => {
    window.clearTimeout(hide.current);
    hide.current = window.setTimeout(() => setTip(null), 260);
  };
  const over = (target: HTMLElement) => {
    const mark = target.closest("mark.term") as HTMLElement | null;
    if (!mark) return;
    window.clearTimeout(hide.current);
    const box = mark.getBoundingClientRect();
    setTip({
      term: {
        kind: (mark.dataset.kind as Term["kind"]) || "task",
        name: mark.dataset.name || mark.textContent || "",
        slug: mark.dataset.slug,
        hint: mark.dataset.hint,
        tag: mark.dataset.tag,
      },
      x: box.left,
      y: box.bottom + 8,
    });
  };
  return { tip, over, leave, stay };
}

export function ArticleBody({ html, terms, claims, onOutline }: { html: string; terms: Term[]; claims: Claim[]; onOutline?: (items: OutlineItem[]) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<{ src: string; alt: string } | null>(null);
  const { tip, over, leave, stay } = useTip();
  const report = useRef(onOutline);
  report.current = onOutline;
  const latest = useRef({ terms, claims });
  latest.current = { terms, claims };
  const signature = useMemo(() => JSON.stringify([terms.map((term) => `${term.kind}:${term.name}`), claims.map((claim) => claim.id)]), [terms, claims]);

  useLayoutEffect(() => {
    const node = host.current;
    if (!node) return;
    node.innerHTML = html;
    annotate(node, latest.current.terms, latest.current.claims);
    report.current?.(outlineOf(node));
  }, [html, signature]);

  useEffect(() => {
    if (!zoom) return;
    const close = (event: KeyboardEvent) => event.key === "Escape" && setZoom(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [zoom]);

  function click(event: ReactMouseEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement;
    const link = target.closest("a") as HTMLAnchorElement | null;
    if (link) {
      const href = link.getAttribute("href") || "";
      if (href.startsWith("#")) {
        event.preventDefault();
        const dest = host.current?.querySelector(`[id="${CSS.escape(href.slice(1))}"]`) as HTMLElement | null;
        if (dest) {
          dest.scrollIntoView({ behavior: "smooth", block: "center" });
          dest.classList.add("flash");
          window.setTimeout(() => dest.classList.remove("flash"), 1600);
        }
        return;
      }
      if (href) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      return;
    }
    const img = target.closest("img") as HTMLImageElement | null;
    if (img && img.closest("figure")) setZoom({ src: img.src, alt: img.alt });
  }

  return (
    <>
      <div
        ref={host}
        className="paper"
        onClick={click}
        onMouseOver={(event) => over(event.target as HTMLElement)}
        onMouseOut={(event) => (event.target as HTMLElement).closest("mark.term") && leave()}
        onFocus={(event) => over(event.target as HTMLElement)}
        onBlur={leave}
      />
      {tip && <Tip term={tip.term} x={tip.x} y={tip.y} onStay={stay} onLeave={leave} />}
      {zoom && (
        <div className="lightbox" role="dialog" aria-label="Figure" onClick={() => setZoom(null)}>
          <img src={zoom.src} alt={zoom.alt} />
          <button className="btn ghost sm" type="button" onClick={() => setZoom(null)}>
            <Icon name="x" />
            Close
          </button>
        </div>
      )}
    </>
  );
}

function PdfPage({ doc, number, width }: { doc: PDFDocumentProxy; number: number; width: number }) {
  const slot = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ratio, setRatio] = useState(1.3);
  const [seen, setSeen] = useState(number <= 2);
  const drawn = useRef(0);

  useEffect(() => {
    doc.getPage(number).then((page) => {
      const base = page.getViewport({ scale: 1 });
      setRatio(base.height / base.width);
      page.cleanup();
    });
  }, [doc, number]);

  useEffect(() => {
    const node = slot.current;
    if (!node || seen) return;
    const watcher = new IntersectionObserver((entries) => entries.some((entry) => entry.isIntersecting) && setSeen(true), { rootMargin: "900px 0px" });
    watcher.observe(node);
    return () => watcher.disconnect();
  }, [seen]);

  useEffect(() => {
    if (!seen || !canvas.current || width < 200 || Math.abs(drawn.current - width) < 24) return;
    let live = true;
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null;
    (async () => {
      const page = await doc.getPage(number);
      if (!live) return;
      const base = page.getViewport({ scale: 1 });
      const scale = (width / base.width) * Math.min(Math.max(window.devicePixelRatio || 1, 2), 3);
      const viewport = page.getViewport({ scale });
      const target = canvas.current;
      if (!target) return;
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      const ctx = target.getContext("2d");
      if (!ctx) return;
      task = page.render({ canvasContext: ctx, viewport, canvas: target } as never);
      await task.promise;
      drawn.current = width;
      page.cleanup();
    })().catch(() => undefined);
    return () => {
      live = false;
      task?.cancel();
    };
  }, [seen, width, doc, number]);

  return (
    <div className="pdf-sheet" ref={slot} style={{ aspectRatio: `1 / ${ratio}` }}>
      <canvas ref={canvas} />
      <span className="pdf-no">{number}</span>
    </div>
  );
}

export function PdfPages({ load, onFail }: { load: () => Promise<Uint8Array>; onFail: () => void }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [width, setWidth] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    let opened: PDFDocumentProxy | null = null;
    load()
      .then((bytes) => pdfjs.getDocument({ data: bytes, disableRange: true, disableStream: true }).promise)
      .then((next) => {
        if (!live) {
          next.destroy();
          return;
        }
        opened = next;
        setDoc(next);
      })
      .catch(() => live && onFail());
    return () => {
      live = false;
      opened?.destroy();
    };
  }, []);

  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    const measure = () => setWidth(Math.floor(node.clientWidth));
    measure();
    const watcher = new ResizeObserver(measure);
    watcher.observe(node);
    return () => watcher.disconnect();
  }, [doc]);

  return (
    <div className="pdf-stack" ref={box}>
      {!doc && (
        <div className="pdf-sheet" style={{ aspectRatio: "1 / 1.3" }}>
          <Skeleton h="100%" />
        </div>
      )}
      {doc && Array.from({ length: doc.numPages }, (_, index) => <PdfPage key={index} doc={doc} number={index + 1} width={width} />)}
    </div>
  );
}

function SentenceFallback({ sentences }: { sentences: { n: number; original: string }[] }) {
  if (!sentences.length) return <p className="muted">No readable text is stored for this paper. Use Open original PDF above.</p>;
  return (
    <article className="folio">
      {sentences.map((item) => (
        <p key={item.n}>{item.original}</p>
      ))}
    </article>
  );
}

type Mode = "loading" | "article" | "pdf" | "text";

export function PaperReader({
  id,
  abstract,
  terms,
  claims,
  sentences,
  onOutline,
}: {
  id: string;
  abstract?: string;
  terms: Term[];
  claims: Claim[];
  sentences: { n: number; original: string }[];
  onOutline?: (items: OutlineItem[]) => void;
}) {
  const token = useToken();
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const has = Boolean(token);
  const [mode, setMode] = useState<Mode>("loading");
  const [html, setHtml] = useState("");
  const [source, setSource] = useState("");

  useEffect(() => {
    if (!has || !id) return;
    let live = true;
    setMode("loading");
    setHtml("");
    onOutline?.([]);
    api<{ html: string; source: string }>(`/papers/${id}/article`, tokenRef.current)
      .then((body) => {
        if (!live) return;
        setHtml(body.html);
        setSource(body.source);
        setMode("article");
      })
      .catch(() => live && setMode("pdf"));
    return () => {
      live = false;
    };
  }, [id, has]);

  const loadPdf = useMemo(
    () => async () => {
      const urls = [`${API}/papers/${id}/pdf/file`];
      if (API.includes("localhost") || API.includes("127.0.0.1")) urls.push(`/api/papers/${id}/pdf/file`);
      let last = "";
      for (const url of urls) {
        try {
          const res = await fetch(url, { headers: { Authorization: `Bearer ${tokenRef.current}` } });
          if (res.ok) return new Uint8Array(await res.arrayBuffer());
          last = res.statusText;
        } catch (err) {
          last = err instanceof Error ? err.message : "network error";
        }
      }
      throw new ApiError(0, last || "pdf unavailable");
    },
    [id],
  );

  return (
    <div className="reader">
      <div className="reader-legend">
        <span className="small muted">
          {mode === "article" ? "Hover a marked term to see why it is in the graph. Click a figure to enlarge it." : mode === "pdf" ? "No web version exists for this paper, so these are the original pages." : " "}
        </span>
        {mode === "article" && (
          <div className="legend">
            <span>
              <i className="swatch task" />
              Task
            </span>
            <span>
              <i className="swatch method" />
              Method
            </span>
            <span>
              <i className="swatch dataset" />
              Dataset
            </span>
            <span>
              <i className="swatch metric" />
              Metric
            </span>
            <span>
              <i className="swatch claim" />
              Claim
            </span>
          </div>
        )}
      </div>

      {mode === "loading" && (
        <div className="paper-skeleton">
          <Skeleton h="1.4rem" w="45%" />
          <Skeleton h="0.9rem" />
          <Skeleton h="0.9rem" />
          <Skeleton h="0.9rem" w="82%" />
          <Skeleton h="11rem" />
        </div>
      )}

      {mode === "article" && (
        <>
          <ArticleBody html={html} terms={terms} claims={claims} onOutline={onOutline} />
          <p className="small faint paper-credit">Typeset from the arXiv HTML edition ({source}). Equations and figures come from the authors' LaTeX source.</p>
        </>
      )}

      {mode === "pdf" && (
        <>
          {abstract && (
            <article className="folio lead">
              <div className="folio-kicker">Abstract</div>
              <p>{abstract}</p>
            </article>
          )}
          <PdfPages load={loadPdf} onFail={() => setMode("text")} />
        </>
      )}

      {mode === "text" && (
        <>
          {abstract && (
            <article className="folio lead">
              <div className="folio-kicker">Abstract</div>
              <p>{abstract}</p>
            </article>
          )}
          <SentenceFallback sentences={sentences} />
        </>
      )}
    </div>
  );
}

export function MixBar({ facets }: { facets?: Facets | null }) {
  const parts = [
    { key: "tasks", label: "Tasks", cls: "task", n: facets?.tasks.length || 0 },
    { key: "methods", label: "Methods", cls: "method", n: facets?.methods.length || 0 },
    { key: "datasets", label: "Datasets", cls: "dataset", n: facets?.datasets.length || 0 },
    { key: "metrics", label: "Metrics", cls: "metric", n: facets?.metrics.length || 0 },
  ];
  const total = parts.reduce((sum, part) => sum + part.n, 0);
  if (!total) return <p className="muted small">No extracted concepts yet.</p>;
  return (
    <div className="mix">
      <div className="mix-bar" aria-hidden="true">
        {parts.map((part) => (part.n ? <span key={part.key} className={part.cls} style={{ flex: part.n }} title={`${part.label}: ${part.n}`} /> : null))}
      </div>
      <div className="mix-legend">
        {parts.map((part) => (
          <span key={part.key}>
            <i className={`swatch ${part.cls}`} />
            {part.n} {part.label.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

function wrap(text: string, max = 26, lines = 2) {
  const words = text.split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let line = "";
  for (const word of words) {
    if (out.length === lines - 1 && (line + " " + word).trim().length > max) {
      line = `${(line + " " + word).trim().slice(0, max - 1)}…`;
      out.push(line);
      line = "";
      break;
    }
    if ((line + " " + word).trim().length > max && line) {
      out.push(line);
      line = word;
    } else line = (line + " " + word).trim();
  }
  if (line) out.push(line.length > max ? `${line.slice(0, max - 1)}…` : line);
  return out.slice(0, lines);
}

export function LineageMap({ current, title, neighbors }: { current: string; title?: string; neighbors?: Neighbors | null }) {
  const nav = useNavigate();
  const cites = neighbors?.cites || [];
  const later = neighbors?.cited_by || [];
  const citesTotal = Math.max(neighbors?.cites_total || 0, cites.length);
  const laterTotal = Math.max(neighbors?.cited_by_total || 0, later.length);
  const [hover, setHover] = useState("");
  const W = 800;
  const H = 540;
  const cx = W / 2;
  const cy = H / 2 + 10;
  const CORE = 52;

  const arrange = (items: Neighbor[], dir: -1 | 1) => {
    const rings = items.length > 16 ? (items.length > 40 ? 3 : 2) : 1;
    const sizes = Array.from({ length: rings }, (_, ring) => items.filter((_, index) => index % rings === ring).length);
    return items.map((item, index) => {
      const ring = index % rings;
      const slot = Math.floor(index / rings);
      const count = sizes[ring];
      const span = 66 + Math.min(items.length, 30) * 0.2;
      const angle = ((count === 1 ? 0 : -span + (2 * span * slot) / (count - 1)) * Math.PI) / 180;
      const rx = 250 + ring * 46;
      const ry = 190 + ring * 28;
      return { ...item, x: cx + dir * rx * Math.cos(angle), y: cy + ry * Math.sin(angle) };
    });
  };

  const left = arrange(cites, -1);
  const right = arrange(later, 1);
  const all = [...left.map((node) => ({ ...node, side: "prior" as const })), ...right.map((node) => ({ ...node, side: "next" as const }))];
  const focus = all.find((node) => node.arxiv_id === hover);
  const dotR = all.length > 40 ? 5 : 6.5;

  const edge = (node: (typeof all)[number]) => {
    const dx = node.x - cx;
    const dy = node.y - cy;
    const len = Math.hypot(dx, dy) || 1;
    return `M ${cx + (dx / len) * CORE} ${cy + (dy / len) * CORE} L ${node.x - (dx / len) * dotR} ${node.y - (dy / len) * dotR}`;
  };

  const cardW = 236;
  const cardX = focus ? Math.max(8, Math.min(focus.x - cardW / 2, W - cardW - 8)) : 0;
  const cardY = focus ? (focus.y < 90 ? focus.y + 18 : focus.y - 62) : 0;
  const cardLines = focus ? wrap(focus.title || focus.arxiv_id, 34, 2) : [];

  return (
    <div className="lineage-map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Citation neighborhood">
        <text x={24} y={30} className="map-caption">
          Builds on · {citesTotal}
        </text>
        <text x={W - 24} y={30} className="map-caption" textAnchor="end">
          Built on by · {laterTotal}
        </text>
        {citesTotal > cites.length && (
          <text x={24} y={46} className="map-note">
            Showing the {cites.length} most recent
          </text>
        )}
        {laterTotal > later.length && (
          <text x={W - 24} y={46} className="map-note" textAnchor="end">
            Showing the {later.length} most recent
          </text>
        )}

        {all.map((node) => (
          <path key={`e-${node.side}-${node.arxiv_id}`} d={edge(node)} className={`map-edge ${node.side} ${hover ? (hover === node.arxiv_id ? "hot" : "dim") : ""}`} />
        ))}

        {!cites.length && (
          <text x={150} y={cy} className="map-empty" textAnchor="middle">
            No cited papers in this corpus
          </text>
        )}
        {!later.length && (
          <text x={W - 150} y={cy} className="map-empty" textAnchor="middle">
            No later papers cite this yet
          </text>
        )}

        {all.map((node) => (
          <g
            key={`n-${node.side}-${node.arxiv_id}`}
            className={`map-dot ${node.side} ${hover ? (hover === node.arxiv_id ? "hot" : "dim") : ""}`}
            role="link"
            aria-label={node.title || node.arxiv_id}
            onClick={() => nav(`/papers/${node.arxiv_id}`)}
            onMouseEnter={() => setHover(node.arxiv_id)}
            onMouseLeave={() => setHover("")}
          >
            <circle cx={node.x} cy={node.y} r={dotR + 6} className="map-hit" />
            <circle cx={node.x} cy={node.y} r={hover === node.arxiv_id ? dotR + 3 : dotR} className="map-disc" />
          </g>
        ))}

        <g className="map-node core">
          <circle cx={cx} cy={cy} r={CORE} />
          <title>{title || current}</title>
          {wrap(title || "This paper", 13, 3).map((line, index, lines) => (
            <text key={index} x={cx} y={cy + (index - (lines.length - 1) / 2) * 13 + 3.5} textAnchor="middle">
              {line}
            </text>
          ))}
        </g>
        <text x={cx} y={cy + CORE + 18} textAnchor="middle" className="map-sub">
          {current}
        </text>

        {focus && (
          <g className="map-card" pointerEvents="none">
            <rect x={cardX} y={cardY} width={cardW} height={cardLines.length > 1 ? 46 : 32} rx={10} />
            {cardLines.map((line, index) => (
              <text key={index} x={cardX + 12} y={cardY + (cardLines.length > 1 ? 19 : 20) + index * 14}>
                {line}
              </text>
            ))}
            {focus.year ? (
              <text className="map-year" x={cardX + cardW - 10} y={cardY - 5} textAnchor="end">
                {focus.year}
              </text>
            ) : null}
          </g>
        )}
      </svg>
      <div className="map-tip">{focus ? focus.title || focus.arxiv_id : "Each dot is a paper. Hover to read its title, click to open it. Left came before this paper, right builds on it."}</div>
    </div>
  );
}