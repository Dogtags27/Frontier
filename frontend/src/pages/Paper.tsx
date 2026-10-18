import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorText, post, type Facets, type Neighbor, type Neighbors, type Paper, type Progress } from "../api";
import { useAuth } from "../auth";
import { useChat } from "../chat";
import { LineageMap, MixBar, PaperReader, termsFrom, type Claim, type OutlineItem } from "../reader";
import { fieldName } from "../taxonomy";
import { ProvenanceStrip, type StripGroup } from "../strip";
import { dataChanged, useFetch, useToast, useToken } from "../hooks";
import { Badge, Empty, ErrorNote, Icon, Skeleton, SkeletonList, ago } from "../ui";

type Tab = "read" | "lineage";
const DEPTHS = [
  ["skimmed", "Skimmed"],
  ["read", "Read"],
  ["understood", "Understood"],
] as const;

export function PaperPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const student = user?.signup_role === "student";
  const token = useToken();
  const notify = useToast();
  const chat = useChat();
  const [tab, setTab] = useState<Tab>("read");
  const [focus, setFocus] = useState(false);
  const [depth, setDepth] = useState<string>("read");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [outline, setOutline] = useState<OutlineItem[]>([]);

  const paper = useFetch<Paper>(`/papers/${id}`);
  const facets = useFetch<Facets>(`/papers/${id}/facets`);
  const sentences = useFetch<{ items: { n: number; original: string }[] }>(`/papers/${id}/sentences?limit=80`);
  const neighbors = useFetch<Neighbors>(`/papers/${id}/neighbors`);
  const provenance = useFetch<{ sentence: string; groups: StripGroup[] }>(tab === "lineage" ? `/papers/${id}/provenance` : null);
  const progress = useFetch<Progress>(student ? "/students/me/progress" : null);
  const claims = useFetch<{ items: Claim[] }>(`/papers/${id}/claims`);

  useEffect(() => {
    setTab("read");
    setFocus(false);
    setNote("");
  }, [id]);

  useEffect(() => {
    if (!focus) return;
    if (chat.open) chat.setOpen(false);
  }, [focus]);

  const mine = progress.data?.reading.recent.find((item) => item.paper_id === id);
  const inPath = progress.data?.reading.path.some((item) => item.paper_id === id);
  const info = paper.data;
  const claimItems = useMemo(() => (claims.data?.items || []).filter((item) => item.sentence || item.label), [claims.data]);
  const terms = useMemo(() => termsFrom(facets.data, claimItems), [facets.data, claimItems]);
  const original = `https://arxiv.org/pdf/${id}`;

  async function save() {
    setSaving(true);
    try {
      await post("/students/me/reads", token, { paper_id: id, depth, note: note.trim() });
      notify("Saved to your reading record");
      setNote("");
      dataChanged();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setSaving(false);
    }
  }

  if (paper.error && !info) {
    return (
      <div className="page narrow">
        <Link className="btn ghost sm" to="/papers">
          <Icon name="back" />
          Papers
        </Link>
        <div className="mt-lg">
          <Empty icon="doc" title="Paper not found" text={`There is no paper with id ${id} in this corpus.`} action={<Link className="btn sm" to="/papers">Search the corpus</Link>} />
        </div>
      </div>
    );
  }

  return (
    <div className={`page reader-page ${focus ? "is-focus" : ""}`}>
      <Link className="small row" to="/papers" style={{ marginBottom: "1rem", width: "fit-content" }}>
        <Icon name="back" />
        Papers
      </Link>

      <header className="paper-head col">
        {info ? (
          <>
            <h1>{info.title}</h1>
            <div className="meta">
              <span className="mono">{info.arxiv_id}</span>
              {info.year ? <i className="sep" /> : null}
              {info.year ? <span>{info.year}</span> : null}
              {info.category && <i className="sep" />}
              {info.category && <span title={info.category}>{fieldName(info.category)}</span>}
              {info.paper_kind && <Badge tone="brand">{info.paper_kind}</Badge>}
              {mine && <Badge tone={mine.depth}>{mine.depth}</Badge>}
              {inPath && !mine && <Badge tone="accent">On your path</Badge>}
            </div>
          </>
        ) : (
          <>
            <Skeleton h="2.2rem" w="80%" />
            <Skeleton h="1rem" w="30%" />
          </>
        )}
        <div className="row wrap">
          <a className="btn" href={original} target="_blank" rel="noreferrer">
            <Icon name="external" />
            Open original PDF
          </a>
          <button className={`btn ghost ${focus ? "on" : ""}`} type="button" onClick={() => setFocus((value) => !value)}>
            {focus ? "Show notes" : "Focus reading"}
          </button>
          {student && (
            <>
              <button className="btn ghost" type="button" onClick={() => chat.ask(`What is ${id} about?`)}>
                <Icon name="spark" />
                Ask the assistant
              </button>
              <button className="btn ghost" type="button" onClick={() => chat.ask(`Find gaps around ${id}`)}>
                <Icon name="flag" />
                Find gaps from here
              </button>
              <Link className="btn ghost" to={`/field?seed=${encodeURIComponent(id)}`}>
                <Icon name="map" />
                Map from here
              </Link>
            </>
          )}
        </div>
      </header>

      <div className="reader-layout mt-lg">
        <section className="reader-stage">
          <div className="tabs" role="tablist">
            {(
              [
                ["read", "Read"],
                ["lineage", "Lineage"],
              ] as const
            ).map(([value, label]) => (
              <button key={value} className={`tab ${tab === value ? "on" : ""}`} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
                {label}
              </button>
            ))}
          </div>

          {tab === "read" && (
            <PaperReader
              id={id}
              abstract={info?.abstract}
              terms={terms}
              claims={claimItems}
              sentences={sentences.data?.items || []}
              onOutline={(items) => setOutline((prev) => (prev.length === items.length && prev.every((item, index) => item.id === items[index].id) ? prev : items))}
            />
          )}

          {tab === "lineage" && (
            <div className="col gap-lg">
              <div>
                <h2 className="section-title" style={{ marginBottom: "0.6rem" }}>
                  Citation neighborhood
                </h2>
                <LineageMap current={id} title={info?.title} neighbors={neighbors.data} />
              </div>
              <div>
                <h2 className="section-title" style={{ marginBottom: "0.6rem" }}>
                  Provenance
                </h2>
                {provenance.loading && !provenance.data ? <SkeletonList rows={2} h="4rem" /> : <ProvenanceStrip sentence={provenance.data?.sentence || ""} groups={provenance.data?.groups || []} />}
              </div>
              <div className="grid-2">
                <NeighborList title="Builds on" icon="back" items={neighbors.data?.cites} loading={neighbors.loading} empty="No cited papers inside this corpus." />
                <NeighborList title="Built on by" icon="arrow" items={neighbors.data?.cited_by} loading={neighbors.loading} empty="No later papers in the corpus cite this one." />
              </div>
              <ErrorNote text={neighbors.error || provenance.error} />
            </div>
          )}
        </section>

        {!focus && (
          <aside className="col sticky reader-rail">
            {tab === "read" && outline.length > 0 && (
              <div className="card">
                <div className="card-title row" style={{ marginBottom: "0.6rem" }}>
                  <Icon name="doc" />
                  Contents
                </div>
                <nav className="outline" aria-label="Sections">
                  {outline.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`outline-item l${item.level}`}
                      onClick={() => document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                    >
                      {item.text}
                    </button>
                  ))}
                </nav>
              </div>
            )}
            {student && (
              <div className="card">
                <div className="card-head">
                  <span className="card-title row">
                    <Icon name="book" />
                    Your reading
                  </span>
                  {mine && <span className="small faint">{ago(mine.at)}</span>}
                </div>
                {mine?.note && <p className="small muted" style={{ marginBottom: "0.8rem" }}>"{mine.note}"</p>}
                <div className="segmented" style={{ display: "flex" }}>
                  {DEPTHS.map(([value, label]) => (
                    <button key={value} type="button" className={depth === value ? "on" : ""} style={{ flex: 1 }} onClick={() => setDepth(value)}>
                      {label}
                    </button>
                  ))}
                </div>
                <textarea className="textarea mt" rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="What stood out? What is the main limit?" aria-label="Reading note" />
                <button className="btn block mt" type="button" disabled={saving} onClick={save}>
                  <Icon name="check" />
                  {saving ? "Saving..." : mine ? "Update record" : "Mark as read"}
                </button>
              </div>
            )}

            <div className="card">
              <div className="card-title" style={{ marginBottom: "0.8rem" }}>
                In the graph
              </div>
              <MixBar facets={facets.data} />
              {facets.loading && !facets.data ? (
                <SkeletonList rows={3} h="1.6rem" />
              ) : (
                <div className="col mt">
                  {(
                    [
                      ["tasks", "task", "Tasks"],
                      ["methods", "method", "Methods"],
                      ["datasets", "dataset", "Datasets"],
                      ["metrics", "metric", "Metrics"],
                    ] as const
                  ).map(([key, kind, label]) => {
                    const list = facets.data?.[key] || [];
                    if (!list.length) return null;
                    return (
                      <div key={key}>
                        <div className="label" style={{ marginBottom: "0.35rem" }}>
                          {label}
                        </div>
                        <div className="chips">
                          {list.map((item) => (
                            <Link key={item.slug} className={`chip ${kind}`} to={`/papers?${kind}=${encodeURIComponent(item.slug)}`} title={`Find papers with ${item.name}`}>
                              {item.name}
                            </Link>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  {facets.data && !Object.values(facets.data).some((list) => Array.isArray(list) && list.length) && <p className="muted small">No extracted concepts for this paper.</p>}
                </div>
              )}
            </div>

            <div className="card">
              <div className="card-head">
                <span className="card-title row">
                  <Icon name="layers" />
                  Neighborhood
                </span>
                <button className="link-btn small" type="button" onClick={() => setTab("lineage")}>
                  Open map
                </button>
              </div>
              <NeighborPeek items={neighbors.data?.cites} label="Builds on" />
              <NeighborPeek items={neighbors.data?.cited_by} label="Built on by" />
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

function NeighborPeek({ items, label }: { items?: Neighbor[]; label: string }) {
  const list = (items || []).slice(0, 3);
  return (
    <div className="peek">
      <div className="label">{label}</div>
      {list.length ? (
        <div className="col gap-sm">
          {list.map((item) => (
            <Link key={item.arxiv_id} className="peek-link" to={`/papers/${item.arxiv_id}`}>
              {item.title || item.arxiv_id}
            </Link>
          ))}
        </div>
      ) : (
        <p className="muted small">None in this corpus yet.</p>
      )}
    </div>
  );
}

function NeighborList({ title, icon, items, loading, empty }: { title: string; icon: string; items?: Neighbor[]; loading: boolean; empty: string }) {
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title row">
          <Icon name={icon} />
          {title}
        </span>
        {items && <Badge>{items.length}</Badge>}
      </div>
      {loading && !items ? (
        <SkeletonList rows={3} h="2rem" />
      ) : items?.length ? (
        <div className="list">
          {items.map((item) => (
            <div className="list-item" key={item.arxiv_id}>
              <div className="grow">
                <Link to={`/papers/${item.arxiv_id}`} className="clamp-2" style={{ fontWeight: 500, color: "var(--text)" }}>
                  {item.title || item.arxiv_id}
                </Link>
                <div className="small faint">
                  <span className="mono">{item.arxiv_id}</span>
                  {item.year ? ` · ${item.year}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small">{empty}</p>
      )}
    </div>
  );
}
