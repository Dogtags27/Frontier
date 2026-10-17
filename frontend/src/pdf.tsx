import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API, ApiError } from "./api";
import { useToken } from "./hooks";
import { Icon } from "./ui";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type Highlight = { text: string; label?: string };

type Piece = { str: string; transform: number[]; width: number; height: number };

const STEP = 4;

function squash(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function locate(norm: string, needle: string) {
  if (needle.length < 18) return -1;
  const head = needle.slice(0, 120);
  const at = norm.indexOf(head);
  if (at >= 0) return at;
  for (const size of [48, 28]) {
    const part = needle.slice(0, size);
    if (part.length < size) continue;
    const found = norm.indexOf(part);
    if (found >= 0) return found;
  }
  return -1;
}

function paint(wrap: HTMLDivElement, page: PDFPageProxy, viewport: ReturnType<PDFPageProxy["getViewport"]>, pieces: Piece[], highlights: Highlight[]) {
  wrap.querySelectorAll(".hit").forEach((node) => node.remove());
  let norm = "";
  const owner: number[] = [];
  pieces.forEach((piece, index) => {
    const token = squash(piece.str);
    for (let i = 0; i < token.length; i += 1) owner.push(index);
    norm += token;
  });
  const taken = new Set<number>();
  for (const item of highlights) {
    const needle = squash(item.text);
    const start = locate(norm, needle);
    if (start < 0) continue;
    const end = Math.min(norm.length - 1, start + Math.max(needle.length - 1, 24));
    for (let index = owner[start]; index <= owner[end]; index += 1) {
      if (taken.has(index)) continue;
      const piece = pieces[index];
      if (!piece?.str.trim()) continue;
      taken.add(index);
      const tx = pdfjs.Util.transform(viewport.transform, piece.transform);
      const height = Math.hypot(tx[2], tx[3]) || 10;
      const box = document.createElement("span");
      box.className = "hit";
      if (item.label) box.title = item.label;
      box.style.left = `${(tx[4] / viewport.width) * 100}%`;
      box.style.top = `${((tx[5] - height * 0.92) / viewport.height) * 100}%`;
      box.style.width = `${((piece.width * viewport.scale) / viewport.width) * 100}%`;
      box.style.height = `${((height * 1.15) / viewport.height) * 100}%`;
      wrap.appendChild(box);
    }
  }
}

async function drawPage(doc: PDFDocumentProxy, number: number, width: number, highlights: Highlight[]) {
  const page = await doc.getPage(number);
  const base = page.getViewport({ scale: 1 });
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const scale = Math.max((width / base.width) * ratio, 1);
  const viewport = page.getViewport({ scale });
  const wrap = document.createElement("div");
  wrap.className = "pdf-page";
  wrap.id = `pdf-page-${number}`;
  wrap.style.aspectRatio = `${base.width} / ${base.height}`;
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  wrap.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  if (!ctx) return wrap;
  await page.render({ canvasContext: ctx, viewport, canvas } as never).promise;
  const content = await page.getTextContent();
  const pieces: Piece[] = [];
  for (const raw of content.items) {
    if ("str" in raw) pieces.push(raw as Piece);
  }
  paint(wrap, page, viewport, pieces, highlights);
  page.cleanup();
  return wrap;
}

export function PdfView({ path, highlights }: { path: string; highlights: Highlight[] }) {
  const token = useToken();
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [message, setMessage] = useState("");
  const [blobUrl, setBlobUrl] = useState("");
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(STEP);
  const [tick, setTick] = useState(0);
  const cache = useRef<{ doc: PDFDocumentProxy; url: string } | null>(null);
  const marks = useRef(highlights);
  marks.current = highlights;

  useEffect(() => {
    if (!token || !path) return;
    let live = true;
    setStatus("loading");
    setMessage("");
    setLimit(STEP);
    setBlobUrl("");
    host.current?.replaceChildren();
    (async () => {
      const urls = [`${API}${path}`];
      if (API.includes("localhost") || API.includes("127.0.0.1")) urls.push(`/api${path}`);
      let res: Response | null = null;
      let last = "";
      for (const url of urls) {
        try {
          const next = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
          if (next.ok) {
            res = next;
            break;
          }
          last = next.statusText;
        } catch (err) {
          last = err instanceof Error ? err.message : "network error";
        }
      }
      if (!res) throw new ApiError(0, last || "The PDF could not be fetched");
      const buffer = await res.arrayBuffer();
      if (!live) return;
      const bytes = new Uint8Array(buffer.slice(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
      const doc = await pdfjs.getDocument({ data: bytes, disableRange: true, disableStream: true }).promise;
      if (!live) {
        doc.destroy();
        URL.revokeObjectURL(url);
        return;
      }
      cache.current?.doc.destroy();
      if (cache.current?.url) URL.revokeObjectURL(cache.current.url);
      cache.current = { doc, url };
      setBlobUrl(url);
      setTotal(doc.numPages);
      setTick((value) => value + 1);
    })().catch((err) => {
      if (!live) return;
      setMessage(err instanceof Error ? err.message : "");
      setStatus("failed");
    });
    return () => {
      live = false;
    };
  }, [path, token]);

  useEffect(
    () => () => {
      cache.current?.doc.destroy();
      if (cache.current?.url) URL.revokeObjectURL(cache.current.url);
      cache.current = null;
    },
    [],
  );

  useEffect(() => {
    const node = host.current;
    const loaded = cache.current?.doc;
    if (!node || !loaded || tick === 0) return;
    let live = true;
    setStatus("loading");
    (async () => {
      const width = node.clientWidth || 720;
      const start = node.childElementCount;
      for (let number = start + 1; number <= Math.min(loaded.numPages, limit); number += 1) {
        if (!live) return;
        node.appendChild(await drawPage(loaded, number, width, marks.current));
      }
      if (live) setStatus("ready");
    })().catch((err) => {
      if (!live) return;
      setMessage(err instanceof Error ? err.message : "");
      setStatus("failed");
    });
    return () => {
      live = false;
    };
  }, [tick, limit]);

  useEffect(() => {
    if (status !== "ready") return;
    const node = host.current;
    const loaded = cache.current?.doc;
    if (!node || !loaded) return;
    (async () => {
      for (let number = 1; number <= node.childElementCount; number += 1) {
        const wrap = node.children[number - 1] as HTMLDivElement;
        const page = await loaded.getPage(number);
        const content = await page.getTextContent();
        const pieces: Piece[] = [];
        for (const raw of content.items) {
          if ("str" in raw) pieces.push(raw as Piece);
        }
        const base = page.getViewport({ scale: 1 });
        const ratio = wrap.clientWidth / base.width;
        paint(wrap, page, page.getViewport({ scale: ratio || 1 }), pieces, highlights);
        page.cleanup();
      }
    })().catch(() => undefined);
  }, [highlights, status]);

  return (
    <div className="pdf-wrap">
      <div className="row between small muted" style={{ marginBottom: "0.6rem" }}>
        <span>
          <mark className="legend-hit" /> Claims and key sentences are highlighted on the page.
        </span>
        {blobUrl && (
          <a className="row" href={blobUrl} target="_blank" rel="noreferrer">
            Open in new tab
            <Icon name="external" />
          </a>
        )}
      </div>
      {status === "loading" && <div className="pdf-state">Loading the paper...</div>}
      {status === "failed" && (
        <div className="pdf-state">
          {blobUrl ? (
            <>
              The page renderer failed{message ? ` (${message})` : ""}. Opening the original file below.
              <iframe className="pdf-frame" title="Paper PDF" src={blobUrl} />
            </>
          ) : (
            <>The PDF could not be opened{message ? ` (${message})` : ""}.</>
          )}
        </div>
      )}
      <div ref={host} />
      {status === "ready" && total > limit && (
        <div style={{ textAlign: "center" }}>
          <button className="btn ghost sm" type="button" onClick={() => setLimit(limit + STEP)}>
            Show more pages ({Math.min(limit, total)} of {total})
          </button>
        </div>
      )}
    </div>
  );
}
