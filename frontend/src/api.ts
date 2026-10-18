export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type User = {
  id: string;
  email: string;
  role: string;
  signup_role: string;
  display_name: string;
  org_id: string | null;
  graph_status: string;
};

export type GapStatus = "candidate" | "challenged" | "alive" | "killed" | "adopted" | "scooped";

export type PaperHit = {
  arxiv_id: string;
  title: string;
  year?: number;
  category?: string;
};

export type SearchHit = PaperHit & {
  layer?: string;
  paper_kind?: string;
  score: number;
  matched_by: string[];
  claim: { id: string; kind: string; label: string; span: number } | null;
  snippet: string;
  status: "read" | "queued" | "unread" | string;
  citations: number;
};

export type SearchResult = { items: SearchHit[]; next_cursor: number | null; elapsed_ms: number };

export type Paper = PaperHit & { abstract?: string; categories?: string[]; layer?: string; paper_kind?: string };
export type Facet = { slug: string; name: string };
export type Facets = { tasks: Facet[]; methods: Facet[]; datasets: Facet[]; metrics: Facet[] };
export type Neighbor = { arxiv_id: string; title: string; year: number };
export type Neighbors = { cites: Neighbor[]; cited_by: Neighbor[]; cites_total?: number; cited_by_total?: number };
export type Mark = { start: number; end: number; kind: string; ref_id: string; title: string };
export type Evidence = { ref_type?: string; ref_id?: string; title?: string; status?: string };
export type TraceStep = { tool?: string; args?: Record<string, unknown>; result_summary?: string };

export type Progress = {
  gaps: Record<string, number>;
  open_gaps: { id: string; status: string; score: number; task_id: string; title: string; evidence: number }[];
  reading: {
    count: number;
    recent: { id: string; at: string; depth: string; note: string; paper_id: string; title: string }[];
    path: { paper_id: string; title: string }[];
    plans: { gap_id: string; summary: string }[];
  };
  notes: { note: string; paper_id: string; title?: string }[];
  decisions: { id: string; at: string; kind: string; reason: string; invalidated: boolean }[];
  timeline: { at: string; kind: string; ref: string; title: string }[];
  graph: { gaps: number; reads: number; decisions: number; concepts: number; plans: number };
};

export type GapItem = { id: string; status: GapStatus; version: number; score: number | null; task_id: string; text: string; at: string };
export type GapCheck = { name: string; result: string; reason: string; at: string };
export type GapDetail = GapItem & { evidence?: number; refs?: { kind: string; ref_id: string }[]; checks?: GapCheck[] };

export type Profile = {
  reads_by_day: { day: string; count: number }[];
  tasks: string[];
  gaps: Record<string, number>;
  interest: string;
  reading: Progress["reading"];
  graph: Progress["graph"];
};

export type Invite = { code: string; join_path: string; expires_at: string; max_uses: number; used: number };
export type Org = { id: string; name: string; supervisor: string; joined_at: string; members: number };
export type OrgInfo = { id: string; name: string; members: number };
export type Student = { id: string; display_name: string };
export type MemoryItem = { id: string; kind: string; text: string; entity: string; valid_from: string };
export type Job = { id: string; type: string; status: string; result: { text?: string; summary?: string; evidence?: Evidence[]; caveats?: string[]; trace?: TraceStep[] } | null; error: string; created: number; finished: number };
export type Conversation = { id: string; at: string; title: string; turns: number };
export type Turn = { id: string; at: string; role: string; text: string; evidence?: Evidence[]; intent?: string };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.message || res.statusText;
  } catch {
    return res.statusText || "Request failed";
  }
}

export async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return res.json() as Promise<T>;
}

export function post<T>(path: string, token: string, body: unknown): Promise<T> {
  return api<T>(path, token, { method: "POST", body: JSON.stringify(body) });
}

export function errorText(err: unknown, fallback = "Something went wrong.") {
  return err instanceof Error && err.message ? err.message : fallback;
}

export type ChatEvent = { event: string; data: Record<string, unknown> };

export async function streamChat(
  token: string,
  message: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  conversationId = "",
): Promise<void> {
  const res = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await parseError(res));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    buf += decoder.decode(step.value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop() || "";
    for (const block of blocks) {
      const name = block.match(/^event: (.+)$/m)?.[1] || "message";
      const raw = block.match(/^data: (.+)$/m)?.[1];
      if (!raw) continue;
      onEvent({ event: name, data: JSON.parse(raw) as Record<string, unknown> });
    }
  }
}
