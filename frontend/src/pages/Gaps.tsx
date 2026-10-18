import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, errorText, post, type GapDetail, type GapItem, type Progress } from "../api";
import { useChat } from "../chat";
import { useFetch, useToast, useToken } from "../hooks";
import { PaperPicker } from "../picker";
import { Badge, Empty, ErrorNote, GAP_HINT, GapBar, Icon, Lifecycle, NEXT_STATUS, PageHead, SkeletonList, ago } from "../ui";

const FILTERS = [
  ["all", "All"],
  ["open", "Open"],
  ["adopted", "Adopted"],
  ["closed", "Closed"],
] as const;

const ACTION: Record<string, { label: string; icon: string; danger?: boolean }> = {
  challenged: { label: "Send to challenge", icon: "shield" },
  alive: { label: "It survived", icon: "check" },
  killed: { label: "Kill this gap", icon: "x", danger: true },
  adopted: { label: "Adopt as my direction", icon: "flag" },
};

function matches(filter: string, status: string) {
  if (filter === "open") return ["candidate", "challenged", "alive"].includes(status);
  if (filter === "adopted") return status === "adopted";
  if (filter === "closed") return ["killed", "scooped"].includes(status);
  return true;
}

export function Gaps() {
  const { id } = useParams();
  const chat = useChat();
  const list = useFetch<{ items: GapItem[] }>("/students/me/gaps");
  const progress = useFetch<Progress>("/students/me/progress");
  const [filter, setFilter] = useState<string>("all");
  const [proposing, setProposing] = useState(false);

  const items = list.data?.items || [];
  const shown = items.filter((item) => matches(filter, item.status));
  const evidence = new Map((progress.data?.open_gaps || []).map((gap) => [gap.id, gap.evidence]));

  function refresh() {
    list.reload();
    progress.reload();
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="Research gaps"
        title="Open questions"
        sub="A gap is something the papers you read have not answered yet, so it could be worth working on. Track each one from idea to adopted, or drop it when the evidence says no."
        actions={
          <>
            <button className="btn ghost" type="button" onClick={() => chat.ask("Find gaps around my reading")}>
              <Icon name="spark" />
              Find gaps
            </button>
            <button className="btn" type="button" onClick={() => setProposing((value) => !value)}>
              <Icon name="plus" />
              Propose a gap
            </button>
          </>
        }
      />

      {proposing && <ProposeForm onDone={() => { setProposing(false); refresh(); }} onCancel={() => setProposing(false)} />}

      {progress.data && progress.data.graph.gaps > 0 && (
        <div className="card" style={{ marginBottom: "1.25rem" }}>
          <GapBar counts={progress.data.gaps} />
        </div>
      )}

      <ErrorNote text={list.error} />

      <div className="split wide-right">
        <section className="col">
          <div className="segmented" style={{ alignSelf: "flex-start" }}>
            {FILTERS.map(([value, label]) => (
              <button key={value} type="button" className={filter === value ? "on" : ""} onClick={() => setFilter(value)}>
                {label}
              </button>
            ))}
          </div>
          {list.loading && !list.data ? (
            <SkeletonList rows={4} h="4.4rem" />
          ) : shown.length ? (
            <div className="col gap-sm">
              {shown.map((item) => (
                <Link key={item.id} to={`/gaps/${item.id}`} className={`gap-item ${item.id === id ? "on" : ""}`} data-s={item.status}>
                  <div className="row between" style={{ alignItems: "flex-start" }}>
                    <div className="gap-title clamp-3">{item.text || item.id}</div>
                    <Badge tone={item.status} dot>
                      {item.status}
                    </Badge>
                  </div>
                  <div className="row wrap small faint" style={{ marginTop: "0.35rem" }}>
                    {evidence.has(item.id) && <span>{evidence.get(item.id)} evidence</span>}
                    {item.score !== null && item.score !== undefined && <span className="score">score {Number(item.score).toFixed(2)}</span>}
                    <span>{ago(item.at)}</span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <Empty
              icon="flag"
              title={items.length ? "Nothing in this view" : "No gaps yet"}
              text={items.length ? "Try another filter." : "Ask the assistant to search for gaps, or propose one of your own."}
            />
          )}
        </section>

        <section>{id ? <Detail key={id} id={id} onChange={refresh} plan={progress.data?.reading.plans.find((plan) => plan.gap_id === id)?.summary || ""} /> : <Placeholder />}</section>
      </div>
    </div>
  );
}

function Placeholder() {
  return (
    <div className="card tint sticky">
      <div className="card-title" style={{ marginBottom: "0.8rem" }}>
        How a gap earns its place
      </div>
      <ol className="ladder">
        {(["candidate", "challenged", "alive", "adopted"] as const).map((status, index) => (
          <li key={status}>
            <span className="ladder-num">{index + 1}</span>
            <div>
              <Badge tone={status} dot>
                {status}
              </Badge>
              <p className="small muted" style={{ marginTop: "0.25rem" }}>
                {GAP_HINT[status]}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <p className="small muted">A gap can also end as killed or scooped. Select one on the left to work on it.</p>
    </div>
  );
}

function ProposeForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const token = useToken();
  const notify = useToast();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      const created = await post<{ id?: string; status?: string }>("/students/me/gaps", token, { text: text.trim(), task_id: "" });
      notify(created.status && created.status !== "candidate" ? `Gap added and reviewed: ${created.status}` : "Gap added as a candidate");
      onDone();
      if (created.id) navigate(`/gaps/${created.id}`);
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card col" style={{ marginBottom: "1.25rem" }} onSubmit={submit}>
      <div className="field">
        <label htmlFor="gap-text">Describe the gap</label>
        <textarea id="gap-text" className="textarea" rows={3} autoFocus value={text} onChange={(event) => setText(event.target.value)} placeholder="Nobody has applied X to Y under constraint Z" />
      </div>
      <div className="row">
        <button className="btn" type="submit" disabled={busy || !text.trim()}>
          {busy ? "Reviewing..." : "Add and review"}
        </button>
        <button className="btn ghost" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const CHECK_LABEL: Record<string, string> = {
  occupancy: "Is the pairing already published?",
  prior_art: "Does a paper name the method in its title?",
  adjacency: "How close is the nearest work?",
  later_work: "Did later papers revisit it?",
  scope: "Scope",
  idea_review: "Has this idea already been published?",
};

function Detail({ id, onChange, plan }: { id: string; onChange: () => void; plan: string }) {
  const token = useToken();
  const notify = useToast();
  const gap = useFetch<GapDetail>(`/students/me/gaps/${id}`);
  const [refId, setRefId] = useState("");
  const [reason, setReason] = useState("");
  const [kind, setKind] = useState("adopt");
  const [busy, setBusy] = useState("");
  const [planText, setPlanText] = useState("");

  const data = gap.data;

  async function act(name: string, run: () => Promise<unknown>, success: string) {
    setBusy(name);
    try {
      await run();
      notify(success);
      gap.reload();
      onChange();
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        notify("This gap changed elsewhere. Refreshed.", "error");
        gap.reload();
        onChange();
      } else {
        notify(errorText(err), "error");
      }
      return false;
    } finally {
      setBusy("");
    }
  }

  if (gap.loading && !data) return <SkeletonList rows={3} h="7rem" />;
  if (!data) return <Empty icon="flag" title="Gap not found" text={gap.error || "It may have been removed."} action={<Link className="btn sm" to="/gaps">Back to gaps</Link>} />;

  const refs = data.refs || [];
  const count = data.evidence ?? refs.length;
  const closed = data.status === "killed" || data.status === "scooped";
  const next = NEXT_STATUS[data.status] || [];
  const shownPlan = planText || plan;

  return (
    <div className="col gap-lg">
      <div className="card">
        <div className="row between wrap" style={{ alignItems: "flex-start" }}>
          <Badge tone={data.status} dot>
            {data.status}
          </Badge>
          <span className="small faint">
            opened {ago(data.at)} · v{data.version}
          </span>
        </div>
        <h2 className="section-title mt" style={{ fontSize: "1.35rem", lineHeight: 1.3 }}>
          {data.text || data.id}
        </h2>
        <p className="muted small" style={{ marginTop: "0.4rem" }}>
          {GAP_HINT[data.status]}
        </p>
        <div className="mt">
          <Lifecycle status={data.status} />
        </div>
        {data.task_id && (
          <div className="chips mt">
            <span className="chip task">{data.task_id}</span>
          </div>
        )}
        {next.length > 0 && (
          <div className="row wrap mt">
            {next.map((status) => {
              const spec = ACTION[status];
              return (
                <button
                  key={status}
                  className={`btn ${spec.danger ? "danger" : ""}`}
                  type="button"
                  disabled={Boolean(busy)}
                  onClick={() => {
                    if (status === "killed" && !window.confirm("Kill this gap? This cannot be undone.")) return;
                    act(status, () => post(`/students/me/gaps/${id}/transition`, token, { to: status, version: data.version }), `Gap is now ${status}`);
                  }}
                >
                  <Icon name={spec.icon} />
                  {busy === status ? "Working..." : spec.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="card-title row">
            <Icon name="shield" />
            Adversary review
          </span>
          {(data.status === "candidate" || data.status === "challenged") && count >= 2 && (
            <button
              className="btn ghost sm"
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                act(
                  "challenge",
                  async () => {
                    await post(`/students/me/gaps/${id}/challenge`, token, {});
                    await new Promise((resolve) => setTimeout(resolve, 2500));
                  },
                  "Check started",
                )
              }
            >
              {busy === "challenge" ? "Checking..." : "Run the checks"}
            </button>
          )}
        </div>
        {(data.checks || []).length ? (
          <ol className="checks">
            {(data.checks || []).map((check, index) => (
              <li key={index} className={check.result}>
                <span className="check-dot" />
                <div>
                  <strong>{CHECK_LABEL[check.name] || check.name}</strong>
                  <p className="small muted">{check.reason}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted small">Not checked yet. The adversary tries to disprove each gap by looking for papers that already do it. Gaps found by the assistant are checked automatically.</p>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="card-title row">
            <Icon name="doc" />
            Evidence
          </span>
          <Badge tone={count >= 2 ? "alive" : "challenged"}>{count} of 2 needed</Badge>
        </div>
        {refs.length ? (
          <div className="list" style={{ marginBottom: "0.9rem" }}>
            {refs.map((ref) => (
              <div className="list-item" key={`${ref.kind}-${ref.ref_id}`}>
                <Badge>{ref.kind}</Badge>
                {ref.kind === "paper" ? (
                  <Link className="mono" to={`/papers/${ref.ref_id}`}>
                    {ref.ref_id}
                  </Link>
                ) : (
                  <span className="mono">{ref.ref_id}</span>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="muted small" style={{ marginBottom: "0.9rem" }}>
            No evidence attached. A candidate needs two papers before the adversary can challenge it.
          </p>
        )}
        {!closed && (
          <form
            className="row"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!refId.trim()) return;
              const ok = await act("evidence", () => post(`/students/me/gaps/${id}/evidence`, token, { ref_id: refId.trim(), kind: "paper" }), "Evidence added");
              if (ok) setRefId("");
            }}
          >
            <div className="grow">
              <PaperPicker value={refId} onChange={setRefId} onPick={(hit) => setRefId(hit.arxiv_id)} placeholder="Add a paper as evidence" />
            </div>
            <button className="btn soft" type="submit" disabled={Boolean(busy) || !refId.trim()}>
              <Icon name="plus" />
              Add
            </button>
          </form>
        )}
      </div>

      {!closed && (
        <div className="card">
          <div className="card-head">
            <span className="card-title row">
              <Icon name="flask" />
              Smallest experiment
            </span>
            <button
              className="btn ghost sm"
              type="button"
              disabled={Boolean(busy)}
              onClick={() =>
                act(
                  "plan",
                  async () => {
                    const result = await post<{ text?: string }>("/agents/scoper", token, { gap_id: id });
                    setPlanText(result.text || "");
                  },
                  "Experiment plan ready",
                )
              }
            >
              {busy === "plan" ? "Planning..." : shownPlan ? "Replan" : "Plan experiment"}
            </button>
          </div>
          {shownPlan ? <p className="muted">{shownPlan}</p> : <p className="muted small">The scoper proposes the cheapest experiment using a dataset, metric, and baseline already in the corpus.</p>}
        </div>
      )}

      <form
        className="card col"
        onSubmit={async (event) => {
          event.preventDefault();
          const ok = await act("decision", () => post("/students/me/decisions", token, { kind, reason: reason.trim(), gap_id: id }), "Decision recorded");
          if (ok) setReason("");
        }}
      >
        <span className="card-title row">
          <Icon name="check" />
          Record a decision
        </span>
        <div className="row">
          <select className="select sm" style={{ width: "auto" }} value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Decision kind">
            <option value="adopt">Adopt</option>
            <option value="defer">Defer</option>
            <option value="drop">Drop</option>
          </select>
          <input className="input sm" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why? Your supervisor can see this." aria-label="Reason" />
          <button className="btn soft sm" type="submit" disabled={Boolean(busy)}>
            Save
          </button>
        </div>
      </form>
    </div>
  );
}
