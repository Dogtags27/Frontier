import { Link } from "react-router-dom";
import type { Progress } from "./api";
import { Badge, EVENT_LABEL, GAP_HINT, ago, titleCase } from "./ui";

export function Timeline({ items, limit = 8, links = true }: { items: Progress["timeline"]; limit?: number; links?: boolean }) {
  return (
    <ol className="timeline">
      {items.slice(0, limit).map((item, index) => {
        const target = item.title || item.ref;
        const isPaper = item.kind === "read" || /^\d{4}\.\d{4,5}|^[a-z-]+\/\d+/i.test(item.ref);
        return (
          <li className="tl-item" data-k={item.kind} key={`${item.at}-${index}`}>
            <div className="tl-kind">{EVENT_LABEL[item.kind] || titleCase(item.kind)}</div>
            <div className="small">
              {links && isPaper && item.ref ? <Link to={`/papers/${item.ref}`}>{target}</Link> : target || <span className="faint">Workspace update</span>}
            </div>
            <div className="small faint">{ago(item.at)}</div>
          </li>
        );
      })}
    </ol>
  );
}

type GapRowProps = { id: string; title: string; status: string; evidence?: number; score?: number | null; readonly?: boolean };

export function GapRow({ id, title, status, evidence, score, readonly }: GapRowProps) {
  const body = (
    <>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div className="gap-title clamp-2">{title || id}</div>
        <Badge tone={status} dot>
          {status}
        </Badge>
      </div>
      <div className="row wrap small faint" style={{ marginTop: "0.35rem" }}>
        {evidence !== undefined && <span>{evidence} evidence</span>}
        {score !== undefined && score !== null && <span className="score">score {Number(score).toFixed(2)}</span>}
        {evidence === undefined && score == null && <span>{GAP_HINT[status]}</span>}
      </div>
    </>
  );
  if (readonly) {
    return (
      <div className="gap-item" data-s={status}>
        {body}
      </div>
    );
  }
  return (
    <Link to={`/gaps/${id}`} className="gap-item" data-s={status}>
      {body}
    </Link>
  );
}

export function Decisions({ items }: { items: Progress["decisions"] }) {
  return (
    <div className="list">
      {items.map((item) => (
        <div className="list-item" key={item.id}>
          <Badge tone={item.invalidated ? "scooped" : "adopted"}>{item.invalidated ? "invalidated" : item.kind}</Badge>
          <div className="grow">
            <div style={item.invalidated ? { textDecoration: "line-through", color: "var(--text-3)" } : undefined}>{item.reason || titleCase(item.kind)}</div>
            <div className="small faint">{ago(item.at)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
