import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorText, post, type Evidence, type Progress, type TraceStep } from "../api";
import { useFetch, useToast, useToken } from "../hooks";
import { PaperPicker } from "../picker";
import { Badge, Empty, ErrorNote, Icon, PageHead, SkeletonList } from "../ui";

type Result = { text?: string; evidence?: Evidence[]; trace?: TraceStep[] };

export function Field() {
  const token = useToken();
  const notify = useToast();
  const [params] = useSearchParams();
  const topic = params.get("topic") || "";
  const progress = useFetch<Progress>("/students/me/progress");
  const [note, setNote] = useState(topic);
  const [seed, setSeed] = useState(params.get("seed") || "");
  const [seedTitle, setSeedTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  const path = progress.data?.reading.path || [];

  async function run(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const body = await post<Result>("/agents/cartographer", token, { note: note.trim(), paper_id: seed.trim() });
      setResult(body);
      notify("Reading path updated");
      progress.reload();
    } catch (err) {
      setError(errorText(err, "The field could not be mapped."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="Cartographer"
        title="Map the field"
        sub="Pick a seed paper and the cartographer walks the citation graph outward, skips what you have already read, and orders what is left."
      />

      <div className="split">
        <section className="col gap-lg">
          <form className="card col" onSubmit={run}>
            <div className="field">
              <label htmlFor="seed">Seed paper</label>
              <PaperPicker
                id="seed"
                value={seed}
                onChange={(value) => {
                  setSeed(value);
                  setSeedTitle("");
                }}
                onPick={(hit) => {
                  setSeed(hit.arxiv_id);
                  setSeedTitle(hit.title);
                }}
              />
              {seedTitle && (
                <p className="small muted row">
                  <Icon name="check" />
                  {seedTitle}
                </p>
              )}
            </div>
            <div className="field">
              <label htmlFor="note">Topic or intent (optional)</label>
              <input id="note" className="input" value={note} onChange={(event) => setNote(event.target.value)} placeholder="What are you trying to understand?" />
            </div>
            {note.trim() && !seed.trim() && (
              <div className="alert warn">
                <Icon name="alert" />
                <span>
                  A topic on its own only uses the tasks you already know. For a sharper path, <Link to={`/papers?q=${encodeURIComponent(note.trim())}`}>find a seed paper for this topic</Link>.
                </span>
              </div>
            )}
            <ErrorNote text={error} />
            <div className="row">
              <button className="btn" type="submit" disabled={busy || (!seed.trim() && !note.trim())}>
                <Icon name="map" />
                {busy ? "Mapping..." : "Build reading path"}
              </button>
            </div>
          </form>

          {result && (
            <div className="card tint">
              <div className="card-head">
                <span className="card-title row">
                  <Icon name="spark" />
                  Cartographer says
                </span>
              </div>
              <p>{result.text}</p>
              {result.trace && result.trace.length > 0 && (
                <div className="chips mt">
                  {result.trace.map((step, index) => (
                    <span className="chip mono" key={index} title={step.result_summary}>
                      {step.tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        <section>
          <div className="section-head">
            <h2 className="section-title">
              <Icon name="book" />
              Current path
            </h2>
            {path.length > 0 && <Badge tone="brand">{path.length} papers</Badge>}
          </div>
          <div className="card">
            {progress.loading && !progress.data ? (
              <SkeletonList rows={4} h="2.6rem" />
            ) : path.length ? (
              <ol className="ladder">
                {path.map((item, index) => (
                  <li key={item.paper_id}>
                    <span className="ladder-num">{index + 1}</span>
                    <div className="grow">
                      <div className="ladder-title">
                        <Link to={`/papers/${item.paper_id}`}>{item.title || item.paper_id}</Link>
                      </div>
                      <div className="mono faint small">{item.paper_id}</div>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <Empty icon="map" title="No path yet" text="Choose a seed paper and build your first reading path." />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
