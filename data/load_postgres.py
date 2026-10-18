"""Load paper rows and sentence text into Render Postgres.

Reads DATABASE_URL from .env. No embeddings, no student rows, no PDF bytes.
Safe to re-run: a paper already present is skipped.
"""

import json

import psycopg

from r2_config import ROOT, load_env, r2_key

EXTRACT = ROOT / "data" / "extract"
BATCH = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id text PRIMARY KEY,
    title text NOT NULL,
    year integer NOT NULL,
    category text,
    categories text,
    layer text NOT NULL,
    r2_key text NOT NULL,
    abstract text
);
CREATE TABLE IF NOT EXISTS sentences (
    arxiv_id text NOT NULL REFERENCES papers (arxiv_id),
    n integer NOT NULL,
    compressed text,
    original text,
    PRIMARY KEY (arxiv_id, n)
);
"""


def connect():
    url = load_env().get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is missing from .env")
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return psycopg.connect(url, connect_timeout=30)


def clean(value):
    return (value or "").replace("\x00", "")


def papers():
    keys = {}
    index = EXTRACT / "r2_index.jsonl"
    if index.exists():
        with index.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                keys[row["arxiv_id"]] = row["r2_key"]
    with (EXTRACT / "corpus.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            aid = rec["arxiv_id"]
            yield {
                "arxiv_id": aid,
                "title": clean(rec["title"]),
                "year": int(rec["year"]),
                "category": rec.get("primary") or "",
                "categories": " ".join(rec.get("categories") or []),
                "layer": rec["layer"],
                "r2_key": keys.get(aid) or r2_key(aid),
                "abstract": clean(rec.get("abstract")),
            }


def sentence_rows(arxiv_id):
    path = EXTRACT / "sentences" / f"{arxiv_id}.jsonl"
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            yield (arxiv_id, row["n"], clean(row.get("compressed")), clean(row.get("original")))


def main():
    conn = connect()
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("SELECT arxiv_id FROM papers")
        done = {row[0] for row in cur.fetchall()}
    conn.commit()
    print(f"already loaded {len(done)}", flush=True)
    inserted = sentences = 0
    pending = []
    for paper in papers():
        if paper["arxiv_id"] in done:
            continue
        pending.append(paper)
        if len(pending) >= BATCH:
            sentences += write_batch(conn, pending)
            inserted += len(pending)
            pending.clear()
            print(f"papers {inserted}", flush=True)
    if pending:
        sentences += write_batch(conn, pending)
        inserted += len(pending)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM papers")
        paper_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sentences")
        sentence_count = cur.fetchone()[0]
        cur.execute(
            "SELECT n, left(original, 80) FROM sentences WHERE arxiv_id = '1409.1556' AND n = 1"
        )
        sample = cur.fetchone()
    print(
        json.dumps(
            {
                "inserted_papers": inserted,
                "inserted_sentences": sentences,
                "papers": paper_count,
                "sentences": sentence_count,
                "sample_1409_1556_n1": sample[1] if sample else None,
            },
            indent=2,
        )
    )
    conn.close()


def write_batch(conn, batch):
    count = 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO papers (arxiv_id, title, year, category, categories, layer, r2_key, abstract) "
            "VALUES (%(arxiv_id)s, %(title)s, %(year)s, %(category)s, %(categories)s, %(layer)s, %(r2_key)s, %(abstract)s)",
            batch,
        )
        with cur.copy(
            "COPY sentences (arxiv_id, n, compressed, original) FROM STDIN"
        ) as copy:
            for paper in batch:
                for row in sentence_rows(paper["arxiv_id"]):
                    copy.write_row(row)
                    count += 1
    conn.commit()
    return count


if __name__ == "__main__":
    main()
