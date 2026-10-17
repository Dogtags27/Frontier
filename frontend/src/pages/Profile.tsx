import { useState } from "react";
import { api, errorText, type MemoryItem, type Profile as ProfileData } from "../api";
import { useAuth } from "../auth";
import { useFetch, useToast, useToken } from "../hooks";
import { Badge, Empty, ErrorNote, GapBar, Icon, SkeletonList, Stat, ago, initials } from "../ui";

const DAYS = 140;

function level(count: number) {
  if (!count) return 0;
  if (count === 1) return 1;
  if (count === 2) return 2;
  if (count <= 4) return 3;
  return 4;
}

export function Profile() {
  const { user } = useAuth();
  const token = useToken();
  const notify = useToast();
  const profile = useFetch<ProfileData>("/me/profile");
  const memory = useFetch<{ memories: MemoryItem[] }>("/students/me/memory?limit=20");
  const [removing, setRemoving] = useState("");

  const data = profile.data;
  const days = new Map((data?.reads_by_day || []).map((item) => [item.day, item.count]));
  const cells = Array.from({ length: DAYS }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (DAYS - 1 - index));
    const key = date.toISOString().slice(0, 10);
    return { key, count: days.get(key) || 0 };
  });
  const active = cells.filter((cell) => cell.count > 0).length;
  const name = user?.display_name || user?.email || "";

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
      <div className="row" style={{ marginBottom: "1.75rem", gap: "1rem" }}>
        <span className="avatar lg">{initials(name)}</span>
        <div>
          <h1 className="page-title" style={{ fontSize: "1.8rem" }}>
            {user?.display_name || "Your profile"}
          </h1>
          <p className="muted small">{user?.email}</p>
        </div>
      </div>

      <ErrorNote text={profile.error} />

      <div className="stats">
        <Stat icon="book" label="Papers read" value={data?.graph.reads ?? "-"} tone="var(--brand-soft)" />
        <Stat icon="flag" label="Gaps opened" value={data?.graph.gaps ?? "-"} tone="var(--accent-soft)" />
        <Stat icon="check" label="Decisions" value={data?.graph.decisions ?? "-"} tone="var(--adopted-soft)" />
        <Stat icon="layers" label="Concepts known" value={data?.graph.concepts ?? "-"} tone="var(--candidate-soft)" />
      </div>

      <div className="section-head">
        <h2 className="section-title">
          <Icon name="pulse" />
          Reading rhythm
        </h2>
        <span className="small muted">
          {active} active {active === 1 ? "day" : "days"} in the last 20 weeks
        </span>
      </div>
      <div className="card">
        {profile.loading && !data ? (
          <SkeletonList rows={1} h="6rem" />
        ) : (
          <div className="heat" role="img" aria-label="Reading activity heatmap">
            {cells.map((cell) => (
              <span key={cell.key} data-l={level(cell.count)} title={`${cell.key}: ${cell.count} ${cell.count === 1 ? "read" : "reads"}`} />
            ))}
          </div>
        )}
      </div>

      <div className="grid-2 mt-lg" style={{ alignItems: "start" }}>
        <div>
          <div className="section-head" style={{ marginTop: 0 }}>
            <h2 className="section-title">
              <Icon name="compass" />
              What you know
            </h2>
          </div>
          <div className="card">
            {data?.tasks.length ? (
              <div className="chips">
                {data.tasks.map((task) => (
                  <span className="chip task" key={task}>
                    {task}
                  </span>
                ))}
              </div>
            ) : (
              <p className="muted small">Tasks appear here as you record reads and notes.</p>
            )}
            {data?.interest && (
              <p className="muted small" style={{ marginTop: "0.9rem", paddingTop: "0.9rem", borderTop: "1px solid var(--line)" }}>
                {data.interest}
              </p>
            )}
          </div>

          <div className="section-head">
            <h2 className="section-title">
              <Icon name="flag" />
              Gaps
            </h2>
          </div>
          <div className="card">{data && data.graph.gaps > 0 ? <GapBar counts={data.gaps} /> : <p className="muted small">No gaps yet.</p>}</div>
        </div>

        <div>
          <div className="section-head" style={{ marginTop: 0 }}>
            <h2 className="section-title">
              <Icon name="layers" />
              What I remember
            </h2>
          </div>
          <div className="card">
            {memory.loading && !memory.data ? (
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
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
