import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText, post, type MemoryItem, type Org, type Profile as ProfileData } from "../api";
import { useAuth } from "../auth";
import { useFetch, useToast, useToken } from "../hooks";
import { Badge, Empty, ErrorNote, GAP_COLOR, GAP_ORDER, Icon, SkeletonList, ago, initials } from "../ui";

const R = 52;
const C = 2 * Math.PI * R;

function Donut({ counts }: { counts: Record<string, number> }) {
  const total = GAP_ORDER.reduce((sum, key) => sum + (counts[key] || 0), 0);
  let offset = 0;
  return (
    <svg className="donut" viewBox="0 0 128 128" role="img" aria-label={`${total} questions in total`}>
      <circle cx="64" cy="64" r={R} fill="none" stroke="var(--line)" strokeWidth="10" />
      {total > 0 &&
        GAP_ORDER.map((key) => {
          const value = counts[key] || 0;
          if (!value) return null;
          const length = (value / total) * C;
          const gap = Math.min(3, length * 0.2);
          const node = (
            <circle
              key={key}
              cx="64"
              cy="64"
              r={R}
              fill="none"
              stroke={GAP_COLOR[key]}
              strokeWidth="10"
              strokeDasharray={`${Math.max(length - gap, 0.1)} ${C}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 64 64)"
            />
          );
          offset += length;
          return node;
        })}
      <text x="64" y="62" textAnchor="middle" className="donut-n">
        {total}
      </text>
      <text x="64" y="80" textAnchor="middle" className="donut-l">
        {total === 1 ? "question" : "questions"}
      </text>
    </svg>
  );
}

function streaks(days: Set<string>) {
  const key = (date: Date) => date.toISOString().slice(0, 10);
  let current = 0;
  const cursor = new Date();
  if (!days.has(key(cursor))) cursor.setDate(cursor.getDate() - 1);
  while (days.has(key(cursor))) {
    current += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  const sorted = [...days].sort();
  let best = 0;
  let run = 0;
  let prev = 0;
  for (const day of sorted) {
    const time = Date.parse(day);
    run = prev && time - prev === 86400000 ? run + 1 : 1;
    best = Math.max(best, run);
    prev = time;
  }
  return { current, best };
}

const TONES = ["#0f766e", "#4651bd", "#c27a17", "#a42f5f", "#2b8656", "#62759c"];

function toneOf(text: string) {
  let sum = 0;
  for (const ch of text) sum = (sum * 31 + ch.charCodeAt(0)) >>> 0;
  return TONES[sum % TONES.length];
}

function codeFrom(value: string) {
  const text = value.trim();
  const found = text.match(/\/join\/([^/?#\s]+)/);
  return found ? found[1] : text;
}

function Teams() {
  const token = useToken();
  const notify = useToast();
  const { refresh } = useAuth();
  const orgs = useFetch<{ items: Org[] }>("/me/orgs");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState("");
  const items = orgs.data?.items || [];

  async function join(event: React.FormEvent) {
    event.preventDefault();
    const value = codeFrom(code);
    if (!value) return;
    setBusy("join");
    try {
      const joined = await post<{ name?: string }>("/orgs/join", token, { code: value });
      notify(joined.name ? `You joined ${joined.name}` : "You joined the team");
      setCode("");
      orgs.reload();
      void refresh();
    } catch (err) {
      const text = errorText(err);
      notify(text === "not found" ? "That code is invalid, expired, or already replaced." : text, "error");
    } finally {
      setBusy("");
    }
  }

  async function leave(org: Org) {
    if (!window.confirm(`Leave ${org.name}? ${org.supervisor || "The instructor"} will stop seeing your progress summary. You can rejoin with a code.`)) return;
    setBusy(org.id);
    try {
      await api(`/me/orgs/${org.id}`, token, { method: "DELETE" });
      notify(`You left ${org.name}`);
      orgs.reload();
      void refresh();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="card pf-teams">
      <div className="pf-reads-head">
        <h2>Teams</h2>
        {items.length > 0 && <span className="small muted">{items.length === 1 ? "1 team" : `${items.length} teams`}</span>}
      </div>
      <p className="small muted pf-teams-sub">Instructors can see a read-only summary of your progress for each team you join. You can be on several teams at once.</p>

      {orgs.loading && !orgs.data ? (
        <SkeletonList rows={2} h="4rem" />
      ) : items.length ? (
        <ul className="team-list">
          {items.map((org) => (
            <li className="team" key={org.id}>
              <span className="team-mark" style={{ background: toneOf(org.id) }}>
                {initials(org.name)}
              </span>
              <div className="team-body">
                <strong title={org.name}>{org.name}</strong>
                <span className="small muted">
                  Led by {org.supervisor || "your instructor"} · {org.members} {org.members === 1 ? "member" : "members"} · joined {ago(org.joined_at)}
                </span>
              </div>
              <button className="btn ghost sm" type="button" disabled={busy === org.id} onClick={() => leave(org)}>
                Leave
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small team-empty">You are not on a team yet. Ask your instructor for a code and add it below.</p>
      )}

      <form className="team-join" onSubmit={join}>
        <div className="input-wrap grow">
          <Icon name="link" />
          <input className="input" value={code} onChange={(event) => setCode(event.target.value)} placeholder="Enter a class code or paste an invite link" aria-label="Class code" />
        </div>
        <button className="btn" type="submit" disabled={!code.trim() || busy === "join"}>
          {busy === "join" ? "Joining..." : "Join team"}
        </button>
      </form>
    </section>
  );
}

export function Profile() {
  const { user } = useAuth();
  const token = useToken();
  const notify = useToast();
  const profile = useFetch<ProfileData>("/me/profile");
  const memory = useFetch<{ memories: MemoryItem[] }>("/students/me/memory?limit=20");
  const [removing, setRemoving] = useState("");
  const [tab, setTab] = useState<"skills" | "memory">("skills");

  const data = profile.data;
  const dayCounts = new Map((data?.reads_by_day || []).map((item) => [item.day, item.count]));
  const { current, best } = streaks(new Set([...dayCounts.keys()].filter((day) => (dayCounts.get(day) || 0) > 0)));
  const month = new Date();
  month.setDate(month.getDate() - 30);
  const recent = (data?.reads_by_day || []).filter((item) => new Date(item.day) >= month).reduce((sum, item) => sum + item.count, 0);
  const name = user?.display_name || user?.email || "";
  const gaps = data?.gaps || {};
  const total = GAP_ORDER.reduce((sum, key) => sum + (gaps[key] || 0), 0);
  const shown = GAP_ORDER.filter((key) => gaps[key]);

  async function forget(id: string) {
    setRemoving(id);
    try {
      await api(`/students/me/memory/${id}`, token, { method: "DELETE" });
      notify("Forgotten");
      memory.reload();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setRemoving("");
    }
  }

  return (
    <div className="page">
      <ErrorNote text={profile.error} />
      <div className="pf">
        <aside className="card pf-side">
          <span className="avatar xl">{initials(name)}</span>
          <h1 className="pf-name">{user?.display_name || "Your profile"}</h1>
          <p className="muted small pf-mail">{user?.email}</p>
          <div className="pf-rows">
            <div>
              <span>Papers read</span>
              <b>{data?.graph.reads ?? "-"}</b>
            </div>
            <div>
              <span>Decisions made</span>
              <b>{data?.graph.decisions ?? "-"}</b>
            </div>
            <div>
              <span>Concepts known</span>
              <b>{data?.graph.concepts ?? "-"}</b>
            </div>
          </div>
          <div className="pf-rows pf-rhythm">
            <h3>Reading rhythm</h3>
            <div>
              <span>Last 30 days</span>
              <b>{recent}</b>
            </div>
            <div>
              <span>Current streak</span>
              <b>
                {current} {current === 1 ? "day" : "days"}
              </b>
            </div>
            <div>
              <span>Best streak</span>
              <b>
                {best} {best === 1 ? "day" : "days"}
              </b>
            </div>
          </div>
        </aside>

        <div className="pf-main">
          <section className="card pf-solved">
            <Donut counts={gaps} />
            <div className="pf-legend">
              <h2>Open questions</h2>
              {total === 0 ? (
                <p className="muted small">Questions you track show up here, grouped by how far along they are.</p>
              ) : (
                <ul>
                  {shown.map((key) => (
                    <li key={key}>
                      <i style={{ background: GAP_COLOR[key] }} />
                      <span>{key}</span>
                      <b>{gaps[key]}</b>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="card pf-reads">
            <div className="pf-reads-head">
              <h2>Recently read</h2>
              {data && data.graph.reads > 0 && <span className="small muted">{data.graph.reads} in total</span>}
            </div>
            {profile.loading && !data ? (
              <SkeletonList rows={3} h="2.4rem" />
            ) : data?.reading.recent.length ? (
              <ul className="pf-read-list">
                {data.reading.recent.slice(0, 8).map((item) => (
                  <li key={item.id}>
                    <Link to={`/papers/${item.paper_id}`}>{item.title || item.paper_id}</Link>
                    <span className="pf-read-meta">
                      {item.depth && <Badge tone={item.depth}>{item.depth}</Badge>}
                      <span className="small faint">{ago(item.at)}</span>
                    </span>
                    {item.note && <p className="small muted clamp-2">{item.note}</p>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Papers you record as read show up here.</p>
            )}
          </section>

          <section className="card pf-tabs">
            <div className="segmented" role="tablist">
              <button className={tab === "skills" ? "on" : ""} type="button" role="tab" onClick={() => setTab("skills")}>
                Skills
              </button>
              <button className={tab === "memory" ? "on" : ""} type="button" role="tab" onClick={() => setTab("memory")}>
                What I remember
              </button>
            </div>

            {tab === "skills" &&
              (profile.loading && !data ? (
                <SkeletonList rows={2} h="2.4rem" />
              ) : (
                <div className="pf-skills">
                  <h3>
                    <Icon name="compass" />
                    Topics you know
                  </h3>
                  {data?.tasks.length ? (
                    <div className="chips">
                      {data.tasks.map((task) => (
                        <span className="chip task" key={task}>
                          {task}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="muted small">Topics appear here as you read papers and take notes.</p>
                  )}
                  {data?.interest && (
                    <>
                      <h3>
                        <Icon name="spark" />
                        Current focus
                      </h3>
                      <p className="small muted">{data.interest}</p>
                    </>
                  )}
                </div>
              ))}

            {tab === "memory" &&
              (memory.loading && !memory.data ? (
                <SkeletonList rows={3} h="2.6rem" />
              ) : memory.data?.memories.length ? (
                <div className="list">
                  {memory.data.memories.map((item) => (
                    <div className="list-item" key={item.id}>
                      <div className="grow">
                        <div className="row wrap">
                          <Badge tone="brand">{item.kind}</Badge>
                          {item.entity && <span className="small faint">{item.entity}</span>}
                        </div>
                        <p className="small" style={{ marginTop: "0.3rem" }}>
                          {item.text}
                        </p>
                        <p className="small faint">{ago(item.valid_from)}</p>
                      </div>
                      <button className="btn ghost sm icon-only" type="button" title="Forget this" disabled={removing === item.id} onClick={() => forget(item.id)}>
                        <Icon name="trash" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty icon="layers" title="Nothing remembered yet" text="Durable facts from your notes and chats show up here. You can remove any of them." />
              ))}
          </section>

          <Teams />
        </div>
      </div>
    </div>
  );
}
