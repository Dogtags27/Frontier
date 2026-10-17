import { Link } from "react-router-dom";
import { Icon } from "./ui";

export type StripGroup = {
  earlier: { arxiv_id: string; title: string; year: number } | null;
  later: { arxiv_id: string; title: string; year: number }[];
};

type Node = { arxiv_id: string; title: string; year: number };

function PaperNode({ paper, root }: { paper: Node; root?: boolean }) {
  return (
    <div className={`strip-node ${root ? "root" : ""}`}>
      <Link to={`/papers/${paper.arxiv_id}`} className="clamp-3">
        {paper.title || paper.arxiv_id}
      </Link>
      <div className="small faint">
        <span className="mono">{paper.arxiv_id}</span>
        {paper.year ? ` · ${paper.year}` : ""}
      </div>
    </div>
  );
}

export function ProvenanceStrip({ sentence, groups }: { sentence: string; groups: StripGroup[] }) {
  return (
    <div className="col">
      {sentence ? <p className="sentence">{sentence}</p> : <p className="muted small">No claim sentence is stored for this paper.</p>}
      {groups.length === 0 ? (
        <p className="muted small">No later papers in the corpus cite this one.</p>
      ) : (
        <div className="strip">
          {groups.map((group, index) => (
            <div className="strip-group" key={index}>
              {group.earlier && (
                <>
                  <PaperNode paper={group.earlier} root />
                  <Icon name="arrow" className="strip-arrow" />
                </>
              )}
              {group.later.map((paper) => (
                <PaperNode key={paper.arxiv_id} paper={paper} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
