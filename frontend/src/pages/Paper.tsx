import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorText, post, type Facets, type Neighbor, type Neighbors, type Paper, type Progress } from "../api";
import { useAuth } from "../auth";
import { useChat } from "../chat";
import { PdfView, type Highlight } from "../pdf";
import { fieldName } from "../taxonomy";
import { ProvenanceStrip, type StripGroup } from "../strip";
import { useFetch, useToast, useToken } from "../hooks";
import { Badge, Empty, ErrorNote, Icon, Skeleton, SkeletonList, ago } from "../ui";

type Tab = "overview" | "pdf" | "lineage";
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
  const [tab, setTab] = useState<Tab>("overview");
  const [sentenceLimit, setSentenceLimit] = useState(8);
  const [depth, setDepth] = useState<string>("read");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const paper = useFetch<Paper>(`/papers/${id}`);
  const facets = useFetch<Facets>(`/papers/${id}/facets`);
  const sentences = useFetch<{ items: { n: number; original: string }[] }>(`/papers/${id}/sentences?limit=${sentenceLimit}`);
  const neighbors = useFetch<Neighbors>(tab === "lineage" ? `/papers/${id}/neighbors` : null);
  const provenance = useFetch<{ sentence: string; groups: StripGroup[] }>(tab === "lineage" ? `/papers/${id}/provenance` : null);
  const progress = useFetch<Progress>(student ? "/students/me/progress" : null);
  const claims = useFetch<{ items: { id: string; kind: string; label: string; sentence: string }[] }>(`/papers/${id}/claims`);

  useEffect(() => {
    setTab("overview");
    setSentenceLimit(8);
    setNote("");
  }, [id]);

  const mine = progress.data?.reading.recent.find((item) => item.paper_id === id);
  const inPath = progress.data?.reading.path.some((item) => item.paper_id === id);
  const lines = (sentences.data?.items || []).filter((item) => item.original);
  const info = paper.data;
  const claimItems = (claims.data?.items || []).filter((item) => item.sentence);
  const highlights = useMemo<Highlight[]>(
    () => [
      ...(claims.data?.items || []).filter((item) => item.sentence).map((item) => ({ text: item.sentence, label: item.label })),
      ...(sentences.data?.items || []).filter((item) => item.original).map((item) => ({ text: item.original })),
    ],
    [claims.data, sentences.data],
  );

  async function save() {
    setSaving(true);
    try {
      await post("/students/me/reads", token, { paper_id: id, depth, note: note.trim() });
      notify("Saved to your reading record");
      setNote("");
      progress.reload();
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
    <div className="page">
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
          <button className={tab === "pdf" ? "btn" : "btn ghost"} type="button" onClick={() => setTab("pdf")}>
            <Icon name="doc" />
            Read the PDF
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

      <div className="split mt-lg">
        <section>
          <div className="tabs" role="tablist">
            {(
              [
                ["overview", "Overview"],
                ["pdf", "PDF"],
                ["lineage", "Lineage"],
              ] as const
            ).map(([value, label]) => (
              <button key={value} className={`tab ${tab === value ? "on" : ""}`} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
                {label}
              </button>
            ))}
          </div>

          {tab === "overview" && (
            <div className="col gap-lg">
              <div>
                <h2 className="section-title" style={{ marginBottom: "0.6rem" }}>
                  Abstract
                </h2>
                {info ? <p className="abstract">{info.abstract || "No abstract is stored for this paper."}</p> : <SkeletonList rows={3} h="1.1rem" />}
              </div>
              {claimItems.length > 0 && (
                <div>
                  <h2 className="section-title" style={{ marginBottom: "0.6rem" }}>
                    Claims
                  </h2>
                  <div className="col gap-sm">
                    {claimItems.map((item) => (
                      <div className="sentence" key={item.id}>
                        <div className="row small" style={{ marginBottom: "0.3rem" }}>
                          <Badge tone="accent">{item.kind || "claim"}</Badge>
                          <strong>{item.label}</strong>
                        </div>
                        {item.sentence}
                      </div>
                    ))}
                    <button className="link-btn small" type="button" style={{ alignSelf: "flex-start" }} onClick={() => setTab("pdf")}>
                      See these highlighted in the PDF
                    </button>
                  </div>
                </div>
              )}
              <div>
                <h2 className="section-title" style={{ marginBottom: "0.6rem" }}>
                  Key sentences
                </h2>
                {sentences.loading && !lines.length ? (
                  <SkeletonList rows={3} h="3rem" />
                ) : lines.length ? (
                  <div className="col gap-sm">
                    {lines.map((line) => (
                      <p className="sentence" key={line.n}>
                        <span className="mono">#{line.n}</span>
                        {line.original}
                      </p>
                    ))}
                    {sentenceLimit < 30 && lines.length >= sentenceLimit && (
                      <button className="btn ghost sm" type="button" style={{ alignSelf: "flex-start" }} onClick={() => setSentenceLimit(30)}>
                        Show more
                      </button>
                    )}
                  </div>
                ) : (
                  <p className="muted">No sentences are stored for this paper.</p>
                )}
              </div>
            </div>
          )}

          {tab === "pdf" && <PdfView path={`/papers/${id}/pdf/file`} highlights={highlights} />}

          {tab === "lineage" && (
            <div className="col gap-lg">
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

        <aside className="col sticky">
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
              In this paper
            </div>
            {facets.loading && !facets.data ? (
              <SkeletonList rows={3} h="1.6rem" />
            ) : (
              <div className="col">
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
        </aside>
      </div>
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
