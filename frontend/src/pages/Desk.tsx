import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorText, post, type Job, type Progress } from "../api";
import { useAuth } from "../auth";
import { useChat } from "../chat";
import { useFetch, useToast, useToken } from "../hooks";
import { GapRow, Timeline } from "../parts";
import { Badge, Contours, Empty, ErrorNote, GapBar, Icon, SkeletonList, Stat, ago, titleCase } from "../ui";

const ARXIV = /^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?\/\d{7})$/i;

function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "Burning the midnight oil";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function Desk() {
  const { user } = useAuth();
  const token = useToken();
  const notify = useToast();
  const navigate = useNavigate();
  const chat = useChat();
  const progress = useFetch<Progress>("/students/me/progress");
  const brief = useFetch<{ text: string }>("/students/me/brief");
  const jobs = useFetch<{ items: Job[] }>("/students/me/jobs");
  const [query, setQuery] = useState("");
  const [marking, setMarking] = useState("");

  const data = progress.data;
  const path = data?.reading.path || [];
  const gaps = data?.open_gaps || [];
  const first = (user?.display_name || "").split(" ")[0];
  const fresh = data && !path.length && !gaps.length && !data.graph.reads;
  const open = (data?.gaps.candidate || 0) + (data?.gaps.challenged || 0) + (data?.gaps.alive || 0);
  const recentJobs = (jobs.data?.items || []).slice(0, 3);

  function go(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (!value) return;
    navigate(ARXIV.test(value) ? `/papers/${value}` : `/papers?q=${encodeURIComponent(value)}`);
  }

  async function markRead(paperId: string) {
    setMarking(paperId);
    try {
      await post("/students/me/reads", token, { paper_id: paperId, depth: "read", note: "" });
      notify("Marked as read");
      progress.reload();
      brief.reload();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setMarking("");
    }
  }

  return (
    <div className="page">
      <section className="hero">
        <Contours />
        <p className="eyebrow" style={{ color: "var(--accent)", position: "relative" }}>
          Your desk
        </p>
        <h1 style={{ position: "relative" }}>
          {greeting()}
          {first ? `, ${first}` : ""}.
        </h1>
        <p style={{ position: "relative" }}>
          {brief.data?.text && brief.data.text !== "Nothing recorded yet."
            ? brief.data.text
            : "Ask the assistant a topic. It will hand you a path, then the holes in it."}
        </p>
        <form className="hero-actions" onSubmit={go}>
          <div className="input-wrap grow" style={{ minWidth: "16rem" }}>
            <Icon name="search" />
            <input className="input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search papers, or paste an arXiv id" aria-label="Search papers" />
          </div>
          <button className="btn accent" type="submit">
            Search
          </button>
          <button className="btn ghost" type="button" onClick={() => navigate(`/field${query.trim() && !ARXIV.test(query.trim()) ? `?topic=${encodeURIComponent(query.trim())}` : ""}`)}>
            <Icon name="map" />
            Map this topic
          </button>
        </form>
      </section>

      <ErrorNote text={progress.error} />

      <div className="stats mt-lg">
        {progress.loading && !data ? (
          Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton" style={{ height: "6.2rem", borderRadius: "14px" }} />)
        ) : (
          <>
            <Stat icon="book" label="Papers read" value={data?.graph.reads ?? 0} tone="var(--brand-soft)" />
            <Stat icon="flag" label="Open gaps" value={open} note={`${data?.graph.gaps ?? 0} ever opened`} tone="var(--accent-soft)" />
            <Stat icon="check" label="Decisions" value={data?.graph.decisions ?? 0} tone="var(--adopted-soft)" />
            <Stat icon="layers" label="Concepts known" value={data?.graph.concepts ?? 0} tone="var(--candidate-soft)" />
          </>
        )}
      </div>

      {fresh ? (
        <div className="mt-lg">
          <Empty
            icon="compass"
            title="Your desk is empty"
            text="Start by mapping a topic. The cartographer builds a reading path from the citation graph, and gaps follow as you read."
            action={
              <div className="row wrap" style={{ justifyContent: "center" }}>
                <Link className="btn" to="/field">
                  <Icon name="map" />
                  Map a topic
                </Link>
                <button className="btn ghost" type="button" onClick={() => chat.ask("What should I read next?")}>
                  <Icon name="spark" />
                  Ask the assistant
                </button>
              </div>
            }
          />
        </div>
      ) : (
        <div className="split mt-lg">
          <section>
            <div className="section-head">
              <h2 className="section-title">
                <Icon name="book" />
                Reading path
              </h2>
              <Link className="small" to="/field">
                Remap
              </Link>
            </div>
            <div className="card">
              {progress.loading && !data ? (
                <SkeletonList rows={3} h="2.6rem" />
              ) : path.length ? (
                <ol className="ladder">
                  {path.map((item, index) => (
                    <li key={item.paper_id}>
                      <span className="ladder-num">{index + 1}</span>
                      <div className="grow">
                        <div className="ladder-title">
                          <Link to={`/papers/${item.paper_id}`}>{item.title || item.paper_id}</Link>
                        </div>
                        <div className="row small" style={{ marginTop: "0.25rem" }}>
                          <span className="mono faint">{item.paper_id}</span>
                          {index === 0 && <Badge tone="accent">Up next</Badge>}
                        </div>
                      </div>
                      <button className="btn ghost sm" type="button" disabled={marking === item.paper_id} onClick={() => markRead(item.paper_id)}>
                        <Icon name="check" />
                        {marking === item.paper_id ? "Saving" : "Read"}
                      </button>
                    </li>
                  ))}
                </ol>
              ) : (
                <Empty icon="map" title="No reading path yet" text="Map a topic or a seed paper to get an ordered list of what to read." action={<Link className="btn sm" to="/field">Map a topic</Link>} />
              )}
            </div>

            {data?.reading.plans?.[0] && (
              <div className="card tint mt">
                <div className="card-head">
                  <span className="card-title row">
                    <Icon name="flask" />
                    Latest experiment plan
                  </span>
                  <Link className="small" to={`/gaps/${data.reading.plans[0].gap_id}`}>
                    View gap
                  </Link>
                </div>
                <p className="muted">{data.reading.plans[0].summary}</p>
              </div>
            )}

            <div className="section-head">
              <h2 className="section-title">
                <Icon name="pulse" />
                Recent activity
              </h2>
            </div>
            <div className="card">
              {data?.timeline.length ? <Timeline items={data.timeline} limit={6} /> : <p className="muted small">Reads, gap changes, and decisions will appear here.</p>}
            </div>
          </section>

          <section>
            <div className="section-head">
              <h2 className="section-title">
                <Icon name="flag" />
                Open gaps
              </h2>
              <Link className="small" to="/gaps">
                All gaps
              </Link>
            </div>
            <div className="col gap-sm">
              {progress.loading && !data ? (
                <SkeletonList rows={2} h="4.2rem" />
              ) : gaps.length ? (
                gaps.slice(0, 5).map((gap) => <GapRow key={gap.id} id={gap.id} title={gap.title} status={gap.status} evidence={gap.evidence} score={gap.score} />)
              ) : (
                <Empty icon="flag" title="No open gaps" text="Ask the assistant to find gaps around what you have read." action={<button className="btn sm" type="button" onClick={() => chat.ask("Find gaps around my reading")}>Find gaps</button>} />
              )}
            </div>

            {data && data.graph.gaps > 0 && (
              <div className="card mt">
                <div className="card-title" style={{ marginBottom: "0.7rem" }}>
                  Gap lifecycle
                </div>
                <GapBar counts={data.gaps} />
              </div>
            )}

            {recentJobs.length > 0 && (
              <div className="card mt">
                <div className="card-title" style={{ marginBottom: "0.4rem" }}>
                  Background work
                </div>
                <div className="list">
                  {recentJobs.map((job) => (
                    <div className="list-item" key={job.id}>
                      <div className="grow">
                        <div className="small" style={{ fontWeight: 500 }}>
                          {titleCase(job.type)}
                        </div>
                        <div className="small faint">{ago(job.created)}</div>
                      </div>
                      <Badge tone={job.status}>{job.status}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
