import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import type { Progress, Student } from "../api";
import { useAuth } from "../auth";
import { StudentGraph, type GraphNode } from "../graph";
import { useFetch } from "../hooks";
import { Decisions, GapRow, Timeline } from "../parts";
import { Badge, Empty, ErrorNote, GapBar, Icon, SkeletonList, Stat, ago, initials } from "../ui";

export function Ledger() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const progress = useFetch<Progress>(`/students/${id}/progress`);
  const roster = useFetch<Student[]>(user?.org_id ? `/orgs/${user.org_id}/students` : null);

  const data = progress.data;
  const name = roster.data?.find((student) => student.id === id)?.display_name || "Student";

  const nodes = useMemo<GraphNode[]>(() => {
    const list: GraphNode[] = [];
    for (const item of data?.reading.path || []) list.push({ id: item.paper_id, label: item.title || item.paper_id, kind: "path" });
    for (const item of data?.reading.recent || []) list.push({ id: item.paper_id, label: item.title || item.paper_id, kind: "read" });
    for (const item of data?.open_gaps || []) list.push({ id: item.id, label: item.title || item.id, kind: "gap" });
    return list;
  }, [data]);

  if (progress.error && !data) {
    return (
      <div className="page narrow">
        <Link className="small row" to="/roster" style={{ marginBottom: "1rem", width: "fit-content" }}>
          <Icon name="back" />
          Class
        </Link>
        <Empty icon="lock" title="Student not available" text="This student is not enrolled in your class, or has been removed." />
      </div>
    );
  }

  const open = (data?.gaps.candidate || 0) + (data?.gaps.challenged || 0) + (data?.gaps.alive || 0);

  return (
    <div className="page">
      <Link className="small row" to="/roster" style={{ marginBottom: "1rem", width: "fit-content" }}>
        <Icon name="back" />
        Class
      </Link>

      <div className="row between wrap" style={{ marginBottom: "1.5rem" }}>
        <div className="row" style={{ gap: "1rem" }}>
          <span className="avatar lg">{initials(name)}</span>
          <div>
            <p className="eyebrow" style={{ marginBottom: "0.2rem" }}>
              Progress summary
            </p>
            <h1 className="page-title" style={{ fontSize: "1.9rem" }}>
              {name}
            </h1>
          </div>
        </div>
        <Badge tone="brand">
          <Icon name="eye" />
          Read only
        </Badge>
      </div>

      <ErrorNote text={progress.error} />

      <div className="stats">
        <Stat icon="book" label="Papers read" value={data?.graph.reads ?? "-"} tone="var(--brand-soft)" />
        <Stat icon="flag" label="Open questions" value={data ? open : "-"} note={data ? `${data.graph.gaps} ever opened` : undefined} tone="var(--accent-soft)" />
        <Stat icon="check" label="Decisions" value={data?.graph.decisions ?? "-"} tone="var(--adopted-soft)" />
        <Stat icon="layers" label="Concepts known" value={data?.graph.concepts ?? "-"} tone="var(--candidate-soft)" />
      </div>

      <div className="section-head">
        <h2 className="section-title">
          <Icon name="compass" />
          Research graph
        </h2>
      </div>
      {progress.loading && !data ? <div className="skeleton" style={{ height: "26rem", borderRadius: "14px" }} /> : <StudentGraph nodes={nodes} name={name} />}

      <div className="split mt-lg" style={{ alignItems: "start" }}>
        <section className="col gap-lg">
          <div>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2 className="section-title">
                <Icon name="flag" />
                Gaps
              </h2>
            </div>
            {data && data.graph.gaps > 0 && (
              <div className="card" style={{ marginBottom: "0.8rem" }}>
                <GapBar counts={data.gaps} />
              </div>
            )}
            {progress.loading && !data ? (
              <SkeletonList rows={2} h="4rem" />
            ) : data?.open_gaps.length ? (
              <div className="col gap-sm">
                {data.open_gaps.map((gap) => (
                  <GapRow key={gap.id} id={gap.id} title={gap.title} status={gap.status} evidence={gap.evidence} score={gap.score} readonly />
                ))}
              </div>
            ) : (
              <p className="muted small">No open gaps.</p>
            )}
          </div>

          <div>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2 className="section-title">
                <Icon name="book" />
                Reading
              </h2>
              <span className="small muted">{data?.graph.reads ?? 0} total</span>
            </div>
            <div className="card">
              {data?.reading.recent.length ? (
                <div className="list">
                  {data.reading.recent.map((item) => (
                    <div className="list-item" key={item.id}>
                      <div className="grow">
                        <Link to={`/papers/${item.paper_id}`} style={{ fontWeight: 500, color: "var(--text)" }}>
                          {item.title || item.paper_id}
                        </Link>
                        {item.note && <p className="small muted clamp-2">"{item.note}"</p>}
                        <p className="small faint">{ago(item.at)}</p>
                      </div>
                      <Badge tone={item.depth}>{item.depth}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted small">No reading recorded yet.</p>
              )}
            </div>
            {data && data.reading.path.length > 0 && (
              <div className="card tint mt">
                <div className="card-title" style={{ marginBottom: "0.4rem" }}>
                  Queued on their path
                </div>
                <ol className="ladder">
                  {data.reading.path.map((item, index) => (
                    <li key={item.paper_id} style={{ padding: "0.45rem 0" }}>
                      <span className="ladder-num">{index + 1}</span>
                      <div className="ladder-title small">{item.title || item.paper_id}</div>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>

          {data && data.reading.plans.length > 0 && (
            <div>
              <div className="section-head" style={{ marginTop: 0 }}>
                <h2 className="section-title">
                  <Icon name="flask" />
                  Experiment plans
                </h2>
              </div>
              <div className="col gap-sm">
                {data.reading.plans.map((plan) => (
                  <div className="card" key={plan.gap_id}>
                    <p className="muted">{plan.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="col gap-lg">
          <div>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2 className="section-title">
                <Icon name="check" />
                Decisions
              </h2>
            </div>
            <div className="card">{data?.decisions.length ? <Decisions items={data.decisions} /> : <p className="muted small">No decisions recorded.</p>}</div>
          </div>
          <div>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2 className="section-title">
                <Icon name="pulse" />
                Timeline
              </h2>
            </div>
            <div className="card">{data?.timeline.length ? <Timeline items={data.timeline} limit={12} /> : <p className="muted small">Nothing on the timeline yet.</p>}</div>
          </div>
        </section>
      </div>
    </div>
  );
}
