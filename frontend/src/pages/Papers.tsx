import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, errorText, type SearchHit, type SearchResult } from "../api";
import { useAuth } from "../auth";
import { useToken } from "../hooks";
import { fieldName } from "../taxonomy";
import { Badge, Empty, ErrorNote, Icon, PageHead, SkeletonList } from "../ui";

const FACETS = ["task", "method", "dataset", "metric"] as const;
const EXAMPLES = ["graph neural networks", "contrastive learning", "transformers for long documents", "federated learning privacy", "graph coloring"];
const MATCH_LABEL: Record<string, string> = { vector: "semantic", title: "title", name: "concept", abstract: "abstract" };

type Form = { q: string; mode: string; yearFrom: string; yearTo: string; sort: string; unread: boolean };

function readForm(params: URLSearchParams): Form {
  return {
    q: params.get("q") || "",
    mode: params.get("mode") || "hybrid",
    yearFrom: params.get("year_from") || "",
    yearTo: params.get("year_to") || "",
    sort: params.get("sort") || "relevance",
    unread: params.get("unread_only") === "true",
  };
}

export function Papers() {
  const token = useToken();
  const { user } = useAuth();
  const student = user?.signup_role === "student";
  const [params, setParams] = useSearchParams();
  const key = params.toString();
  const [form, setForm] = useState<Form>(() => readForm(params));
  const [items, setItems] = useState<SearchHit[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setForm(readForm(params));
  }, [key]);

  function buildQuery(cursor: number) {
    const query = new URLSearchParams(params);
    if (!query.get("q") && query.get("mode") === "semantic") query.set("mode", "hybrid");
    query.set("limit", "10");
    if (cursor) query.set("cursor", String(cursor));
    return query.toString();
  }

  useEffect(() => {
    if (!token) return;
    let live = true;
    setLoading(true);
    setError("");
    api<SearchResult>(`/papers/search?${buildQuery(0)}`, token)
      .then((body) => {
        if (!live) return;
        setItems(body.items || []);
        setNext(body.next_cursor);
        setElapsed(body.elapsed_ms);
      })
      .catch((err) => live && setError(errorText(err, "Search failed.")))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [key, token]);

  async function loadMore() {
    if (next === null) return;
    setMore(true);
    try {
      const body = await api<SearchResult>(`/papers/search?${buildQuery(next)}`, token);
      setItems((prev) => [...prev, ...(body.items || [])]);
      setNext(body.next_cursor);
    } catch (err) {
      setError(errorText(err, "Could not load more."));
    } finally {
      setMore(false);
    }
  }

  function apply(next: Form, keepFacets = true) {
    const query = new URLSearchParams();
    if (next.q.trim()) query.set("q", next.q.trim());
    if (next.mode !== "hybrid") query.set("mode", next.mode);
    if (next.yearFrom) query.set("year_from", next.yearFrom);
    if (next.yearTo) query.set("year_to", next.yearTo);
    if (next.sort !== "relevance") query.set("sort", next.sort);
    if (next.unread) query.set("unread_only", "true");
    if (keepFacets) {
      for (const name of [...FACETS, "cites", "cited_by", "category"]) {
        const value = params.get(name);
        if (value) query.set(name, value);
      }
    }
    setParams(query);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    apply(form);
  }

  function change(patch: Partial<Form>) {
    const next = { ...form, ...patch };
    setForm(next);
    apply(next);
  }

  function removeParam(name: string) {
    const query = new URLSearchParams(params);
    query.delete(name);
    setParams(query);
  }

  const active = [...FACETS, "cites", "cited_by", "category"].filter((name) => params.get(name));
  const browsing = !params.get("q") && !active.length;

  return (
    <div className="page">
      <PageHead eyebrow="Corpus" title="Papers" sub="Search by meaning, by title and concept, or both. Every result shows why it matched." />

      <form onSubmit={submit}>
        <div className="row">
          <div className="input-wrap grow">
            <Icon name="search" className="big" />
            <input
              className="input big"
              value={form.q}
              onChange={(event) => setForm({ ...form, q: event.target.value })}
              placeholder="Try: contrastive learning for graphs"
              aria-label="Search papers"
              autoFocus
            />
          </div>
          <button className="btn" type="submit" style={{ padding: "0.85rem 1.4rem", borderRadius: "14px" }}>
            Search
          </button>
        </div>

        <div className="filters">
          <div className="field">
            <span className="label">Match by</span>
            <div className="segmented" role="tablist">
              {[
                ["hybrid", "Both"],
                ["semantic", "Meaning"],
                ["metadata", "Keywords"],
              ].map(([value, label]) => (
                <button key={value} type="button" className={form.mode === value ? "on" : ""} onClick={() => change({ mode: value })}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="field" style={{ minWidth: "5.5rem", width: "6rem" }}>
            <label htmlFor="yf">From year</label>
            <input id="yf" className="input sm" inputMode="numeric" maxLength={4} value={form.yearFrom} placeholder="2018" onChange={(event) => setForm({ ...form, yearFrom: event.target.value.replace(/\D/g, "") })} onBlur={() => apply(form)} />
          </div>
          <div className="field" style={{ minWidth: "5.5rem", width: "6rem" }}>
            <label htmlFor="yt">To year</label>
            <input id="yt" className="input sm" inputMode="numeric" maxLength={4} value={form.yearTo} placeholder="2024" onChange={(event) => setForm({ ...form, yearTo: event.target.value.replace(/\D/g, "") })} onBlur={() => apply(form)} />
          </div>
          <div className="field">
            <label htmlFor="sort">Sort</label>
            <select id="sort" className="select sm" value={form.sort} onChange={(event) => change({ sort: event.target.value })}>
              <option value="relevance">Relevance</option>
              <option value="year_desc">Newest first</option>
              <option value="year_asc">Oldest first</option>
              <option value="citations">Most cited here</option>
              <option value="title">Title A to Z</option>
            </select>
          </div>
          {student && (
            <label className="toggle" style={{ paddingBottom: "0.5rem" }}>
              <input type="checkbox" checked={form.unread} onChange={(event) => change({ unread: event.target.checked })} />
              Unread only
            </label>
          )}
        </div>
      </form>

      {active.length > 0 && (
        <div className="chips mt">
          {active.map((name) => (
            <span className={`chip ${name}`} key={name}>
              <span className="faint">{name.replace("_", " ")}</span>
              {name === "category" ? fieldName(params.get(name)) : params.get(name)}
              <button className="link-btn" type="button" aria-label={`Remove ${name} filter`} onClick={() => removeParam(name)} style={{ display: "inline-flex" }}>
                <Icon name="x" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="mt-lg">
        <ErrorNote text={error} />

        {!loading && !error && (
          <div className="row between small muted" style={{ marginBottom: "0.8rem" }}>
            <span>
              {browsing ? "Browsing the corpus" : `${items.length}${next !== null ? "+" : ""} ${items.length === 1 ? "result" : "results"}`}
            </span>
            <span className="faint">{elapsed} ms</span>
          </div>
        )}

        {loading ? (
          <SkeletonList rows={4} h="7.5rem" />
        ) : items.length ? (
          <div className="col">
            {items.map((hit) => (
              <ResultCard key={hit.arxiv_id} hit={hit} student={student} />
            ))}
            {next !== null && (
              <button className="btn ghost" type="button" onClick={loadMore} disabled={more} style={{ alignSelf: "center" }}>
                {more ? "Loading..." : "Load more"}
              </button>
            )}
          </div>
        ) : (
          !error && (
            <Empty
              icon="search"
              title="Nothing matched"
              text="Try fewer filters, switch to Meaning to match ideas rather than words, or start from one of these."
              action={
                <div className="chips" style={{ justifyContent: "center", marginTop: "1rem" }}>
                  {EXAMPLES.map((example) => (
                    <Link key={example} className="chip" to={`/papers?q=${encodeURIComponent(example)}`}>
                      {example}
                    </Link>
                  ))}
                </div>
              }
            />
          )
        )}
      </div>
    </div>
  );
}

function ResultCard({ hit, student }: { hit: SearchHit; student: boolean }) {
  return (
    <Link to={`/papers/${hit.arxiv_id}`} className="card interactive paper-card">
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <h3 className="paper-title">{hit.title}</h3>
        {student && hit.status !== "unread" && <Badge tone={hit.status}>{hit.status}</Badge>}
      </div>
      <div className="meta">
        <span className="mono">{hit.arxiv_id}</span>
        {hit.year ? (
          <>
            <i className="sep" />
            <span>{hit.year}</span>
          </>
        ) : null}
        {hit.category && (
          <>
            <i className="sep" />
            <span title={hit.category}>{fieldName(hit.category)}</span>
          </>
        )}
        {hit.citations > 0 && (
          <>
            <i className="sep" />
            <span>{hit.citations} cited in corpus</span>
          </>
        )}
        {hit.paper_kind && (
          <>
            <i className="sep" />
            <span>{hit.paper_kind}</span>
          </>
        )}
      </div>
      {hit.snippet && <p className="snippet clamp-3">{hit.snippet}</p>}
      {(hit.matched_by.length > 0 || hit.claim) && (
        <div className="row wrap small">
          {hit.matched_by.map((channel) => (
            <Badge key={channel} tone="brand">
              {MATCH_LABEL[channel] || channel}
            </Badge>
          ))}
          {hit.claim?.label && <span className="faint clamp-2">Claim: {hit.claim.label}</span>}
        </div>
      )}
    </Link>
  );
}
