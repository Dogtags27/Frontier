import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, errorText, streamChat, type Conversation, type Evidence, type Job, type Mark, type TraceStep, type Turn } from "./api";
import { useAuth } from "./auth";
import { copyText, dataChanged, useToast } from "./hooks";
import { Badge, Icon, ago, titleCase } from "./ui";

type Msg = {
  id: number;
  role: "student" | "assistant";
  text: string;
  marks: Mark[];
  evidence: Evidence[];
  trace: TraceStep[];
  caveats: string[];
  intent: string;
  streaming: boolean;
  failed: boolean;
  job: string;
  jobStatus: string;
  jobText: string;
};

type ChatValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
  ask: (text: string) => void;
  pending: string;
  consume: () => void;
};

const ChatContext = createContext<ChatValue | null>(null);
const LAST_KEY = "frontier.conversation";

export function ChatProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(() => {
    const saved = localStorage.getItem("frontier.dock");
    if (saved) return saved === "1";
    return window.innerWidth >= 1320;
  });
  const [pending, setPending] = useState("");

  const update = useCallback((next: boolean) => {
    localStorage.setItem("frontier.dock", next ? "1" : "0");
    setOpen(next);
  }, []);

  const value = useMemo<ChatValue>(
    () => ({
      open,
      setOpen: update,
      ask: (text: string) => {
        update(true);
        setPending(text);
      },
      pending,
      consume: () => setPending(""),
    }),
    [open, pending, update],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const value = useContext(ChatContext);
  if (!value) throw new Error("chat missing");
  return value;
}

const STARTERS = [
  { icon: "book", text: "Where do I start with large language models?" },
  { icon: "search", text: "Find papers on graph neural networks after 2020" },
  { icon: "flag", text: "Find gaps around my reading" },
  { icon: "clock", text: "Where did I leave off last time?" },
];

const QUIET_INTENTS = new Set(["clarify", "smalltalk", "refuse", ""]);
const EMPTY = { marks: [] as Mark[], evidence: [] as Evidence[], trace: [] as TraceStep[], caveats: [] as string[], intent: "", streaming: false, failed: false, job: "", jobStatus: "", jobText: "" };

const fold = (value: string) => value.replace(/[\u2018\u2019\u201c\u201d"]/g, "'").replace(/[\u2013\u2014]/g, "-");

function marksFromEvidence(text: string, evidence: Evidence[]): Mark[] {
  const folded = fold(text);
  const found: Mark[] = [];
  const used = new Set<string>();
  for (const item of evidence) {
    if (!item || typeof item !== "object") continue;
    const title = String(item.title || "");
    const refId = String(item.ref_id || "");
    let needle = title.length > 12 ? fold(title) : refId;
    let start = needle ? folded.indexOf(needle) : -1;
    if (start < 0 && refId) {
      needle = refId;
      start = folded.indexOf(needle);
    }
    if (start < 0 || used.has(needle)) continue;
    used.add(needle);
    found.push({ start, end: start + needle.length, kind: String(item.ref_type || "paper"), ref_id: refId, title: title || refId });
  }
  return found;
}

function fromTurns(turns: Turn[]): Msg[] {
  return turns
    .filter((turn) => turn.role === "student" || turn.role === "assistant")
    .map((turn, index) => {
      const evidence = Array.isArray(turn.evidence) ? turn.evidence : [];
      return {
        ...EMPTY,
        id: index + 1,
        role: turn.role as "student" | "assistant",
        text: turn.text,
        evidence,
        marks: turn.role === "assistant" ? marksFromEvidence(turn.text, evidence) : [],
        intent: turn.intent || "",
      };
    });
}

export function ChatDock() {
  const { session } = useAuth();
  const { open, setOpen, pending, consume } = useChat();
  const notify = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [convoId, setConvoId] = useState("");
  const [title, setTitle] = useState("Research assistant");
  const [history, setHistory] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const convoRef = useRef("");
  const boot = useRef(true);
  const loadedFor = useRef("");
  const token = session?.access_token || "";

  const remember = useCallback((id: string, heading = "") => {
    convoRef.current = id;
    setConvoId(id);
    if (heading) setTitle(heading);
    if (id) localStorage.setItem(LAST_KEY, id);
    else localStorage.removeItem(LAST_KEY);
  }, []);

  const listConvos = useCallback(async () => {
    if (!token) return;
    try {
      const body = await api<{ items: Conversation[] }>("/students/me/conversations", token);
      setConvos(body.items || []);
    } catch {
      return;
    }
  }, [token]);

  const openConvo = useCallback(
    async (id: string) => {
      if (!token || !id) return;
      const body = await api<{ id: string; title: string; turns: Turn[] }>(`/students/me/conversations/${id}`, token);
      remember(body.id, body.title || "Research assistant");
      const next = fromTurns(body.turns || []);
      counter.current = next.length;
      setMessages(next);
      setHistory(false);
    },
    [token, remember],
  );

  useEffect(() => {
    if (!token || loadedFor.current === token) return;
    loadedFor.current = token;
    (async () => {
      try {
        const body = await api<{ items: Conversation[] }>("/students/me/conversations", token);
        const items = body.items || [];
        setConvos(items);
        if (!boot.current) return;
        const saved = localStorage.getItem(LAST_KEY);
        const pick = items.find((item) => item.id === saved) || items.find((item) => item.turns > 0) || items[0];
        if (pick) await openConvo(pick.id);
      } catch {
        return;
      }
    })();
  }, [token, openConvo]);

  useEffect(() => {
    const node = thread.current;
    if (node) node.scrollTo({ top: node.scrollHeight });
  }, [messages]);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 128)}px`;
  }, [text]);

  const patch = useCallback((id: number, change: (msg: Msg) => Partial<Msg>) => {
    setMessages((prev) => prev.map((item) => (item.id === id ? { ...item, ...change(item) } : item)));
  }, []);

  const follow = useCallback(
    async (id: number, jobId: string) => {
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, attempt < 5 ? 1500 : 2500));
        try {
          const job = await api<Job>(`/students/me/jobs/${jobId}`, token);
          const body = job.result?.text || job.result?.summary || "";
          if (job.status === "failed") {
            patch(id, () => ({ jobStatus: "failed", jobText: job.error || "" }));
            return;
          }
          if (job.status === "done" || job.result) {
            const evidence = (job.result?.evidence as Evidence[]) || [];
            patch(id, () => ({ jobStatus: "done", jobText: "" }));
            counter.current += 1;
            const reply: Msg = {
              ...EMPTY,
              id: counter.current,
              role: "assistant",
              text: body,
              evidence,
              marks: marksFromEvidence(body, evidence),
              caveats: (job.result?.caveats as string[]) || [],
              trace: (job.result?.trace as TraceStep[]) || [],
              intent: "gap_result",
            };
            setMessages((prev) => [...prev, reply]);
            dataChanged();
            listConvos();
            return;
          }
          patch(id, () => ({ jobStatus: job.status }));
        } catch {
          return;
        }
      }
    },
    [token, patch, listConvos],
  );

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || !token || busy) return;
      boot.current = false;
      setText("");
      setBusy(true);
      counter.current += 2;
      const mine: Msg = { ...EMPTY, id: counter.current - 1, role: "student", text: message };
      const bot: Msg = { ...EMPTY, id: counter.current, role: "assistant", text: "", streaming: true };
      setMessages((prev) => [...prev, mine, bot]);
      const controller = new AbortController();
      abort.current = controller;
      const steps: TraceStep[] = [];
      try {
        await streamChat(
          token,
          message,
          (event) => {
            const data = event.data;
            if (event.event === "conversation") {
              remember(String(data.id || convoRef.current), String(data.title || ""));
            }
            if (event.event === "intent") patch(bot.id, () => ({ intent: String(data.intent || "") }));
            if (event.event === "tool_call") {
              steps.push({ tool: String(data.tool || ""), args: (data.args as Record<string, unknown>) || {} });
              patch(bot.id, () => ({ trace: [...steps] }));
            }
            if (event.event === "tool_result") {
              const open = steps.find((step) => step.tool === data.tool && !step.result_summary);
              if (open) open.result_summary = String(data.summary || "");
              patch(bot.id, () => ({ trace: [...steps] }));
            }
            if (event.event === "token") patch(bot.id, (item) => ({ text: item.text + String(data.text || "") }));
            if (event.event === "final") {
              const job = data.job_id ? String(data.job_id) : "";
              const trace = (data.trace as TraceStep[]) || [];
              if (data.conversation_id) remember(String(data.conversation_id), String(data.conversation_title || ""));
              patch(bot.id, (item) => ({
                text: String(data.text || item.text),
                marks: (data.marks as Mark[]) || [],
                evidence: (data.evidence as Evidence[]) || [],
                trace: trace.length ? trace : [...steps],
                caveats: (data.caveats as string[]) || [],
                streaming: false,
                job,
                jobStatus: job ? "open" : "",
              }));
              if (job) follow(bot.id, job);
              listConvos();
              dataChanged();
            }
          },
          controller.signal,
          convoRef.current,
        );
        patch(bot.id, () => ({ streaming: false }));
      } catch (err) {
        const stopped = controller.signal.aborted;
        patch(bot.id, (item) => ({
          streaming: false,
          failed: !stopped,
          text: item.text || (stopped ? "Stopped." : errorText(err, "The reply failed.")),
        }));
        if (!stopped) notify(errorText(err, "The reply failed."), "error");
      } finally {
        abort.current = null;
        setBusy(false);
        box.current?.focus();
      }
    },
    [token, busy, patch, follow, notify, remember, listConvos],
  );

  useEffect(() => {
    if (pending && !busy && token) {
      const next = pending;
      consume();
      send(next);
    }
  }, [pending, busy, token, consume, send]);

  function fresh() {
    boot.current = false;
    remember("");
    setTitle("Research assistant");
    setMessages([]);
    counter.current = 0;
    setHistory(false);
  }

  async function remove(id: string) {
    try {
      await api(`/students/me/conversations/${id}`, token, { method: "DELETE" });
      if (convoRef.current === id) fresh();
      listConvos();
    } catch (err) {
      notify(errorText(err), "error");
    }
  }

  return (
    <>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <aside className="chat-dock" style={open ? undefined : { display: "none" }} aria-label="Research assistant">
        <header className="chat-head">
          <span className="spark">
            <Icon name="spark" />
          </span>
          <div className="grow">
            <div className="card-title clamp-2">{title}</div>
            <div className="small faint">{convoId ? "Saved on your graph" : "New conversation"}</div>
          </div>
          <button className={`btn ghost sm icon-only ${history ? "on" : ""}`} type="button" title="Past conversations" onClick={() => { setHistory((value) => !value); listConvos(); }}>
            <Icon name="clock" />
          </button>
          <button className="btn ghost sm icon-only" type="button" title="Start a new chat" disabled={busy} onClick={fresh}>
            <Icon name="plus" />
          </button>
          <button className="btn ghost sm icon-only" type="button" title="Close" onClick={() => setOpen(false)}>
            <Icon name="x" />
          </button>
        </header>

        {history && (
          <div className="chat-history">
            {convos.length === 0 ? (
              <p className="small muted">No saved conversations yet. They appear here after you send a message.</p>
            ) : (
              convos.map((item) => (
                <div className={`chat-item ${item.id === convoId ? "on" : ""}`} key={item.id}>
                  <button type="button" className="grow" onClick={() => openConvo(item.id)} disabled={busy}>
                    <div className="clamp-2" style={{ fontWeight: 500 }}>
                      {item.title || "Untitled"}
                    </div>
                    <div className="small faint">
                      {item.turns} {item.turns === 1 ? "turn" : "turns"} · {ago(item.at)}
                    </div>
                  </button>
                  <button className="btn ghost sm icon-only" type="button" title="Delete" onClick={() => remove(item.id)}>
                    <Icon name="trash" />
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        <div className="thread" ref={thread}>
          {messages.length === 0 && (
            <div>
              <h3 className="section-title">What are you working on?</h3>
              <p className="muted small mt">Name a topic in plain words. You do not need an arXiv id.</p>
              <div className="starters">
                {STARTERS.map((item) => (
                  <button key={item.text} className="starter" type="button" onClick={() => send(item.text)}>
                    <Icon name={item.icon} />
                    {item.text}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((item) => (
            <Message key={item.id} item={item} />
          ))}
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            send(text);
          }}
        >
          <div className="composer-box">
            <textarea
              ref={box}
              rows={1}
              value={text}
              placeholder="Ask about a paper, a gap, or what to read"
              aria-label="Message"
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send(text);
                }
              }}
            />
            {busy ? (
              <button className="btn ghost icon-only" type="button" title="Stop" onClick={() => abort.current?.abort()}>
                <Icon name="stop" />
              </button>
            ) : (
              <button className="btn icon-only" type="submit" title="Send" disabled={!text.trim()}>
                <Icon name="send" />
              </button>
            )}
          </div>
          <p className="composer-hint">Enter to send · Past chats live on your private graph</p>
        </form>
      </aside>
    </>
  );
}

function Message({ item }: { item: Msg }) {
  const notify = useToast();
  if (item.role === "student") {
    return (
      <div className="msg mine">
        <div className="bubble">{item.text}</div>
      </div>
    );
  }
  const waiting = item.streaming && !item.text;
  return (
    <div className="msg bot">
      {!QUIET_INTENTS.has(item.intent) && item.intent && <Badge tone="brand">{titleCase(item.intent)}</Badge>}
      {item.trace.length > 0 && item.streaming && (
        <div className="small muted row">
          <Icon name="pulse" />
          Running {item.trace[item.trace.length - 1].tool}
        </div>
      )}
      <div className="bubble" style={item.failed ? { borderColor: "#ecc2c5", background: "var(--danger-soft)" } : undefined}>
        {waiting ? (
          <span className="typing" aria-label="Thinking">
            <i />
            <i />
            <i />
          </span>
        ) : item.streaming ? (
          item.text
        ) : (
          <Marked text={item.text} marks={item.marks} />
        )}
      </div>
      {!item.streaming && item.text && (
        <>
          {item.job && item.jobStatus !== "done" && (
            <div className="alert info small">
              <Icon name="flask" />
              <div>
                {item.jobStatus === "failed" ? (
                  <>
                    <strong>The gap search failed.</strong> {item.jobText || "Ask me to try again."}
                  </>
                ) : (
                  <>
                    <strong>Searching and challenging each gap</strong> The verdicts will appear here, and Open questions updates on its own.
                  </>
                )}
              </div>
            </div>
          )}
          {item.evidence.length > 0 && <EvidenceList items={item.evidence} />}
          {item.caveats.map((caveat, index) => (
            <p className="caveat" key={index}>
              {caveat}
            </p>
          ))}
          {item.trace.length > 0 && <TraceView steps={item.trace} />}
          <div className="msg-tools">
            <button
              className="link-btn small"
              type="button"
              onClick={async () => notify((await copyText(item.text)) ? "Copied to clipboard" : "Copy failed", "ok")}
            >
              Copy
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Marked({ text, marks }: { text: string; marks: Mark[] }) {
  if (!marks.length) return <>{text}</>;
  const ordered = [...marks].sort((a, b) => a.start - b.start);
  const parts: ReactNode[] = [];
  let cursor = 0;
  ordered.forEach((mark, index) => {
    if (mark.start < cursor || mark.end > text.length) return;
    parts.push(text.slice(cursor, mark.start));
    parts.push(
      <Link key={index} className="mark" to={mark.kind === "gap" && mark.ref_id ? `/gaps/${mark.ref_id}` : mark.kind === "paper" && mark.ref_id ? `/papers/${mark.ref_id}` : "/papers"} title={mark.title}>
        {text.slice(mark.start, mark.end)}
      </Link>,
    );
    cursor = mark.end;
  });
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

function EvidenceList({ items }: { items: Evidence[] }) {
  const [open, setOpen] = useState(false);
  const count = items.length;
  return (
    <div className={`sources ${open ? "open" : ""}`}>
      <button
        className="sources-btn"
        type="button"
        aria-expanded={open}
        title={`${count} ${count === 1 ? "reference was" : "references were"} used for this answer`}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="book" />
        Sources
        <span className="sources-n">{count}</span>
        <Icon name="arrow" />
      </button>
      <span className="sources-tip" role="tooltip">
        {count} {count === 1 ? "reference" : "references"} used for this answer
      </span>
      {open && (
        <ul className="sources-list">
          {items.map((item, index) => {
            const id = item.ref_id || "";
            const label = item.title || id || item.ref_type || "Evidence";
            return (
              <li key={`${id}-${index}`}>
                {item.ref_type === "paper" && id ? (
                  <Link to={`/papers/${id}`} title={label}>
                    <span>{label}</span>
                    <small className="mono">{id}</small>
                  </Link>
                ) : item.ref_type === "gap" && id ? (
                  <Link to={`/gaps/${id}`} title={label}>
                    <span>{label}</span>
                    {item.status && <small className={`gap-state ${item.status}`}>{item.status}</small>}
                  </Link>
                ) : (
                  <span className="plain">{label}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function TraceView({ steps }: { steps: TraceStep[] }) {
  return (
    <details className="trace">
      <summary>
        <Icon name="layers" />
        How I got this ({steps.length} {steps.length === 1 ? "step" : "steps"})
      </summary>
      <ol>
        {steps.map((step, index) => (
          <li key={index}>
            <Icon name="arrow" />
            <div>
              <div className="tool">{step.tool}</div>
              {step.args && Object.keys(step.args).length > 0 && (
                <div className="faint mono">
                  {Object.entries(step.args)
                    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
                    .join("  ")
                    .slice(0, 140)}
                </div>
              )}
              {step.result_summary && <div className="out">{step.result_summary}</div>}
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
