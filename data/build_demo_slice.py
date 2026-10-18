"""Cut a local CS demo slice out of ogbn-arxiv. Not the product."""

from __future__ import annotations

import collections
import csv
import gzip
import json
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIP = ROOT / "cache" / "arxiv.zip"
TITLEABS = ROOT / "cache" / "titleabs.tsv.gz"
OUT = ROOT / "demo"

# One field, so the citation graph is a literature a student can walk.
# The source graph is already CS-only. This slice is computation and language.
CATEGORIES = (
    "arxiv cs cl",
    "arxiv cs lg",
    "arxiv cs ai",
    "arxiv cs ir",
    "arxiv cs ne",
)
BASE_YEAR_MAX = 2018
LATER_YEAR_MIN = 2019
BASE_CAP = 650
LATER_CAP = 250
# ogbn's cs.CL label includes papers that are not about language.
# The title has to carry the field. This keeps the demo inside NLP.
KEEP_TERMS = (
    "language", "linguistic", "translation", "parsing", "parser", "sentiment",
    "embedding", "dialogue", "summar", "question answering", "named entity",
    "corpus", "text classif", "word representation", "speech", "grammar",
    "semantic role", "coreference", "entailment", "reading comprehension",
    "machine translation", "nlp", "bert", "glove", "word2vec", "transformer",
    "language model", "tokenization", "pos tag", "dependency pars",
)
DROP_TERMS = (
    "image", "video", "visual", "pixel", "coding theory", "packetization",
    "msr code", "storage system",
)


def member(name: str):
    archive = zipfile.ZipFile(ZIP)
    return gzip.open(archive.open(name), "rt", encoding="utf-8", newline="")


def load_labels() -> dict[int, str]:
    labels = {}
    with member("arxiv/mapping/labelidx2arxivcategeory.csv.gz") as handle:
        next(handle)
        for line in handle:
            idx, name = line.strip().split(",", 1)
            labels[int(idx)] = name.strip().strip('"')
    return labels


def load_column(name: str) -> list[int]:
    values = []
    with member(name) as handle:
        next(handle)
        for line in handle:
            values.append(int(line.strip()))
    return values


def load_paper_ids() -> list[str]:
    ids = []
    with member("arxiv/mapping/nodeidx2paperid.csv.gz") as handle:
        reader = csv.reader(handle)
        next(reader)
        for row in reader:
            ids.append(row[1])
    return ids


def load_edges() -> list[tuple[int, int]]:
    edges = []
    with member("arxiv/raw/edge.csv.gz") as handle:
        next(handle)
        for line in handle:
            left, right = line.strip().split(",")
            edges.append((int(left), int(right)))
    return edges


def load_texts(needed: set[str]) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    with tarfile.open(TITLEABS, "r:gz") as archive:
        handle = archive.extractfile("titleabs.tsv")
        assert handle is not None
        for raw in handle:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            paper_id, title, abstract = line.split("\t", 2)
            if paper_id in needed:
                found[paper_id] = (title.strip(), abstract.strip())
                if len(found) == len(needed):
                    break
    return found


def main() -> None:
    labels = load_labels()
    label_of = {name: idx for idx, name in labels.items()}
    targets = {label_of[name] for name in CATEGORIES}
    node_label = load_column("arxiv/raw/node-label.csv.gz")
    node_year = load_column("arxiv/raw/node_year.csv.gz")
    paper_ids = load_paper_ids()
    edges = load_edges()

    # ogbn-arxiv points each edge from the cited paper to the citing paper.
    # Confirm before writing the slice.
    newer = older = 0
    for src, dst in edges[:200000]:
        if node_year[dst] > node_year[src]:
            newer += 1
        elif node_year[dst] < node_year[src]:
            older += 1
    citing_is_dst = newer >= older

    pool_ids = {
        paper_ids[i]
        for i, label in enumerate(node_label)
        if label in targets
    }
    cl_texts = load_texts(pool_ids)
    label_name = {idx: name for idx, name in labels.items()}

    def in_field(node: int) -> bool:
        title, abstract = cl_texts.get(paper_ids[node], ("", ""))
        title_l = title.lower()
        blob = title_l + " " + abstract.lower()
        if not any(term in blob for term in KEEP_TERMS):
            return False
        if any(term in title_l for term in DROP_TERMS):
            return False
        return True

    cl_nodes = [
        i for i, label in enumerate(node_label)
        if label in targets and in_field(i)
    ]
    cl_set = set(cl_nodes)
    cited_by: dict[int, list[int]] = collections.defaultdict(list)
    cites: dict[int, list[int]] = collections.defaultdict(list)
    for src, dst in edges:
        if src not in cl_set or dst not in cl_set:
            continue
        cited, citing = (src, dst) if citing_is_dst else (dst, src)
        cited_by[cited].append(citing)
        cites[citing].append(cited)

    # One connected neighborhood, not the most-cited list. The most-cited
    # list leaves hundreds of papers with no edge inside the slice.
    seen: set[int] = set()
    components: list[list[int]] = []
    for start in cl_nodes:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp = []
        while stack:
            node = stack.pop()
            comp.append(node)
            for other in cited_by[node]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
            for other in cites[node]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        components.append(comp)
    components.sort(key=len, reverse=True)
    core = components[0]
    hub = max(core, key=lambda i: len(cited_by[i]) + len(cites[i]))
    chosen = []
    queued = {hub}
    order = [hub]
    while order and len(chosen) < BASE_CAP + LATER_CAP:
        node = order.pop(0)
        chosen.append(node)
        neighbors = cited_by[node] + cites[node]
        neighbors.sort(key=lambda i: len(cited_by[i]) + len(cites[i]), reverse=True)
        for other in neighbors:
            if other not in queued:
                queued.add(other)
                order.append(other)
    chosen_set = set(chosen)
    base_set = {i for i in chosen if node_year[i] <= BASE_YEAR_MAX}
    print(
        f"language-titled cs.CL papers={len(cl_nodes)} "
        f"largest_component={len(core)} kept={len(chosen)}",
        flush=True,
    )

    texts = cl_texts
    OUT.mkdir(parents=True, exist_ok=True)

    papers_path = OUT / "papers.jsonl"
    missing_text = 0
    with papers_path.open("w", encoding="utf-8") as handle:
        for i in chosen:
            mag_id = paper_ids[i]
            title, abstract = texts.get(mag_id, ("", ""))
            if not title:
                missing_text += 1
            role = "base" if i in base_set else "later"
            row = {
                "mag_id": mag_id,
                "title": title,
                "abstract": abstract,
                "year": node_year[i],
                "category": label_name[node_label[i]].replace("arxiv ", "").replace(" ", "."),
                "role": role,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    edge_count = 0
    with (OUT / "cites.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["citing_mag_id", "cited_mag_id"])
        for citing, citeds in cites.items():
            if citing not in chosen_set:
                continue
            for cited in citeds:
                if cited not in chosen_set:
                    continue
                writer.writerow([paper_ids[citing], paper_ids[cited]])
                edge_count += 1

    year_hist = collections.Counter(node_year[i] for i in chosen)
    manifest = {
        "papers": len(chosen),
        "base_through_2018": len(base_set),
        "later_2019_2020": len(chosen_set - base_set),
        "citation_edges_inside_slice": edge_count,
        "missing_title_or_abstract": missing_text,
        "categories": ["cs.CL", "cs.LG", "cs.AI", "cs.IR", "cs.NE"],
        "selection": "Largest connected citation neighborhood among papers in those categories whose title or abstract contains a language term. Capped at 900 by a walk from the highest-degree paper.",
        "edge_direction": "citing_mag_id cites cited_mag_id",
        "edge_direction_check": {
            "dst_newer_than_src": newer,
            "dst_older_than_src": older,
            "citing_is_destination": citing_is_dst,
        },
        "year_histogram": {str(k): year_hist[k] for k in sorted(year_hist)},
        "sources": [
            {
                "name": "ogbn-arxiv",
                "url": "https://ogb.stanford.edu/docs/nodeprop/#ogbn-arxiv",
                "files": ["arxiv.zip raw edges, years, labels, MAG ids"],
                "license": "OGB dataset, CC BY 4.0",
            },
            {
                "name": "ogbn-arxiv title and abstract",
                "url": "https://snap.stanford.edu/ogb/data/misc/ogbn_arxiv/titleabs.tsv.gz",
            },
        ],
        "not_included": [
            "authors",
            "arxiv ids",
            "full text",
            "papers after 2020",
            "categories other than cs.CL",
            "the 2025-2026 Kaggle CSV (no local Kaggle credentials)",
        ],
        "do_not_commit": True,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
