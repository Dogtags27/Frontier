"""Name multi-member clusters and link leftover claims with gpt-4.1-mini only.

One cluster per naming call. One paper per linking call. Replies are appended
as they arrive. Re-running skips work already saved. No other model is used.
"""

import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from falkordb import FalkorDB

from extract_client import ALLOWED_MODEL, CHAT_URL, CallError, salvage_json, ssl_context
from load_corpus import CLAIM_EDGE, EXTRACT, GRAPH, NODE_LABEL, TIMEOUT, q
from r2_config import ROOT, load_env

import urllib.error
import urllib.request

MODEL = "gpt-4.1-mini"
WORKERS = 8
SPEND_CAP = 3.0
IN_RATE = 0.40 / 1_000_000
CACHED_RATE = 0.10 / 1_000_000
OUT_RATE = 1.60 / 1_000_000
NAME_OUT = EXTRACT / "naming_results.jsonl"
LINK_OUT = EXTRACT / "link_llm.jsonl"
NAME_FAIL = EXTRACT / "naming_failures.jsonl"
LINK_FAIL = EXTRACT / "link_failures.jsonl"

NAME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"name": {"type": "string"}, "family": {"type": "string"}},
    "required": ["name", "family"],
}
LINK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"claim_id": {"type": "string"}, "target_id": {"type": "string"}},
                "required": ["claim_id", "target_id"],
            },
        }
    },
    "required": ["links"],
}
TARGET_LISTS = (
    ("techniques_used", "method"),
    ("baselines_compared", "method"),
    ("datasets_evaluated", "dataset"),
    ("scoring_measures", "metric"),
)
CLAIM_LISTS = (
    ("research_question", "question"),
    ("claimed_contributions", "contribution"),
    ("reported_results", "result"),
    ("quantitative_findings", "quantitative"),
    ("ablation_findings", "ablation"),
    ("failure_cases", "failure"),
    ("stated_limits", "limit"),
    ("future_work", "future_work"),
    ("assumptions_and_guarantees", "assumption"),
    ("experimental_setup", "setup"),
    ("reproducibility_details", "reproducibility"),
)

spend_lock = threading.Lock()
file_lock = threading.Lock()
spend = {"usd": 0.0, "prompt": 0, "cached": 0, "completion": 0}


def clean(text):
    return (text or "").replace("\x00", "")


def post(body, key, context, attempt=1):
    if body["model"] != ALLOWED_MODEL:
        raise RuntimeError(f"refusing model {body['model']}")
    req = urllib.request.Request(
        CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300, context=context) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        header = exc.headers.get("Retry-After") if exc.headers else None
        retry_after = int(header) if header and header.isdigit() else None
        raise CallError(exc.code, detail, exc.code == 429 or exc.code >= 500, retry_after) from None
    used = raw.get("model") or ""
    if not used.startswith(ALLOWED_MODEL):
        raise RuntimeError(f"response model {used}")
    return raw


def account(raw):
    usage = raw.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    fresh = max(0, prompt - cached)
    usd = fresh * IN_RATE + cached * CACHED_RATE + completion * OUT_RATE
    with spend_lock:
        spend["usd"] += usd
        spend["prompt"] += prompt
        spend["cached"] += cached
        spend["completion"] += completion
        total = spend["usd"]
    if total > SPEND_CAP:
        raise SystemExit(f"spend cap ${SPEND_CAP:.2f} reached at ${total:.2f}")
    return usage


def append(path, row):
    with file_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()


def done_ids(path, key):
    found = set()
    if not path.exists():
        return found
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                found.add(json.loads(line)[key])
    return found


def call_with_retry(body, key, context):
    for attempt in range(5):
        try:
            raw = post(body, key, context)
            account(raw)
            return raw
        except CallError as exc:
            if not exc.retryable or attempt == 4:
                raise
            time.sleep(exc.retry_after or min(2 ** attempt, 30))
    raise RuntimeError("retry loop ended")


def parsed_message(raw):
    message = raw["choices"][0]["message"]["content"] or ""
    parsed = salvage_json(message)
    return message, parsed, raw["choices"][0].get("finish_reason")


def name_jobs():
    groups = defaultdict(list)
    meta = {}
    with (EXTRACT / "aliases.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            groups[row["canonical_id"]].append(row["label"])
            meta[row["canonical_id"]] = row["kind"]
    jobs = []
    for cid, labels in groups.items():
        if len(labels) < 2:
            continue
        jobs.append({"id": cid, "kind": meta[cid], "labels": labels})
    return jobs


def run_naming(key, context):
    finished = done_ids(NAME_OUT, "id")
    jobs = [job for job in name_jobs() if job["id"] not in finished]
    print(f"naming calls {len(jobs)}", flush=True)

    def one(job):
        listing = "\n".join(f"- {clean(label)}" for label in job["labels"])
        body = {
            "model": MODEL,
            "temperature": 0,
            "max_completion_tokens": 200,
            "response_format": {"type": "json_schema", "json_schema": {"name": "cluster_name", "strict": True, "schema": NAME_SCHEMA}},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You name one cluster of spellings that already refer to the same thing. "
                        "Reply with a canonical name under 8 words, using the most common spelling when it is already clear. "
                        "family is a short method-family name for a method cluster, and an empty string otherwise. "
                        "Do not introduce a different algorithm, dataset, or metric."
                    ),
                },
                {"role": "user", "content": f"Kind: {job['kind']}\nSpellings:\n{listing}"},
            ],
        }
        raw = call_with_retry(body, key, context)
        message, parsed, finish = parsed_message(raw)
        name = (parsed or {}).get("name", "").strip() if isinstance(parsed, dict) else ""
        family = (parsed or {}).get("family", "").strip() if isinstance(parsed, dict) else ""
        if not name:
            append(NAME_FAIL, {"id": job["id"], "raw_content": message, "finish_reason": finish})
            return
        if job["kind"] != "method":
            family = ""
        append(
            NAME_OUT,
            {
                "id": job["id"],
                "kind": job["kind"],
                "name": name,
                "family": family or name if job["kind"] == "method" else "",
                "finish_reason": finish,
                "usage": raw.get("usage", {}),
                "raw_content": message,
            },
        )

    run_pool(jobs, one)
    print(f"naming spend ${spend['usd']:.4f}", flush=True)


def link_jobs():
    facets = {}
    with (EXTRACT / "facets_clean.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            facets[rec["arxiv_id"]] = rec
    by_paper = defaultdict(list)
    with (EXTRACT / "claim_links.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            by_paper[row["arxiv_id"]].append(row)
    jobs = []
    for aid, rows in by_paper.items():
        rec = facets[aid]
        targets = []
        for key, role in TARGET_LISTS:
            for index, item in enumerate(rec["facets"].get(key) or []):
                targets.append(
                    {
                        "id": f"{key}:{index}",
                        "role": role,
                        "label": item["label"],
                        "sentence_number": item["sentence_number"],
                    }
                )
        if not targets:
            continue
        counts = defaultdict(int)
        claims = []
        for row in rows:
            index = counts[row["kind"]]
            counts[row["kind"]] += 1
            if row["links"]:
                continue
            claims.append(
                {
                    "id": f"c{len(claims)}",
                    "kind": row["kind"],
                    "index": index,
                    "label": row["label"],
                    "sentence_number": row["sentence_number"],
                }
            )
        if claims:
            jobs.append({"arxiv_id": aid, "claims": claims, "targets": targets})
    return jobs


def original_sentence(arxiv_id, number, cache):
    if arxiv_id not in cache:
        rows = {}
        path = EXTRACT / "sentences" / f"{arxiv_id}.jsonl"
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                rows[row["n"]] = clean(row.get("original"))
        cache[arxiv_id] = rows
    return cache[arxiv_id].get(number, "")


def run_linking(key, context):
    finished = done_ids(LINK_OUT, "arxiv_id")
    jobs = [job for job in link_jobs() if job["arxiv_id"] not in finished]
    print(f"linking calls {len(jobs)}", flush=True)
    sentences = {}
    sent_lock = threading.Lock()

    def one(job):
        with sent_lock:
            claim_lines = []
            for claim in job["claims"]:
                sentence = original_sentence(job["arxiv_id"], claim["sentence_number"], sentences)
                claim_lines.append(f"{claim['id']} {claim['kind']}: {clean(claim['label'])}\n{sentence}")
        target_lines = [
            f"{item['id']} {item['role']}: {clean(item['label'])}" for item in job["targets"]
        ]
        cap = min(2500, max(400, 30 * len(job["claims"])))
        body = {
            "model": MODEL,
            "temperature": 0,
            "max_completion_tokens": cap,
            "response_format": {"type": "json_schema", "json_schema": {"name": "claim_links", "strict": True, "schema": LINK_SCHEMA}},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Link claims from one paper to that paper's own methods, datasets, and metrics. "
                        "Use only the ids shown. A claim may link to several targets or to none. "
                        "Link a claim only when it is about that target, not when the words merely co-occur. "
                        "Reply with links: [{claim_id, target_id}]."
                    ),
                },
                {
                    "role": "user",
                    "content": "Targets:\n" + "\n".join(target_lines) + "\n\nClaims:\n" + "\n".join(claim_lines),
                },
            ],
        }
        raw = call_with_retry(body, key, context)
        message, parsed, finish = parsed_message(raw)
        claims = {item["id"]: item for item in job["claims"]}
        targets = {item["id"]: item for item in job["targets"]}
        kept = []
        seen = set()
        for item in (parsed or {}).get("links", []) if isinstance(parsed, dict) else []:
            claim = claims.get(item.get("claim_id"))
            target = targets.get(item.get("target_id"))
            if not claim or not target:
                continue
            identity = (claim["kind"], claim["index"], target["id"])
            if identity in seen:
                continue
            seen.add(identity)
            kept.append(
                {
                    "kind": claim["kind"],
                    "index": claim["index"],
                    "role": target["role"],
                    "label": target["label"],
                    "sentence_number": target["sentence_number"],
                    "source": "llm",
                }
            )
        append(
            LINK_OUT,
            {
                "arxiv_id": job["arxiv_id"],
                "links": kept,
                "finish_reason": finish,
                "usage": raw.get("usage", {}),
                "raw_content": message,
            },
        )

    run_pool(jobs, one)
    print(f"spend so far ${spend['usd']:.4f}", flush=True)


def run_pool(jobs, fn):
    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fn, job) for job in jobs]
        done = 0
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 50 == 0 or done == len(jobs):
                print(f"finished {done}/{len(jobs)} ${spend['usd']:.4f}", flush=True)


def apply_names():
    named = {}
    with NAME_OUT.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            named[row["id"]] = row
    canon_path = EXTRACT / "canonical.jsonl"
    updated = []
    for line in canon_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        found = named.get(row["id"])
        if found:
            row["name"] = found["name"]
            row["provisional"] = False
            if row["kind"] == "method":
                row["family"] = found["family"] or found["name"]
        updated.append(row)
    canon_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in updated), encoding="utf-8")
    alias_path = EXTRACT / "aliases.jsonl"
    aliases = []
    for line in alias_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        found = named.get(row["canonical_id"])
        if found:
            row["canonical_name"] = found["name"]
        aliases.append(row)
    alias_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in aliases), encoding="utf-8")
    graph = FalkorDB(host="localhost", port=6379).select_graph(GRAPH)
    rows = [
        {
            "slug": row["id"],
            "name": row["name"],
            "family": row.get("family") or row["name"],
            "label": NODE_LABEL[row["kind"]],
        }
        for row in named.values()
    ]
    for label in ("Task", "Method", "Dataset", "Metric"):
        chunk = [row for row in rows if row["label"] == label]
        if not chunk:
            continue
        family = ", n.family = row.family" if label == "Method" else ""
        q(
            graph,
            "UNWIND $rows AS row "
            f"MATCH (n:{label} {{slug: row.slug}}) "
            "SET n.name = row.name, n.provisional = false" + family,
            {"rows": chunk},
        )
    for ws_name in ("frontier_ws_maya", "frontier_ws_dev"):
        ws = FalkorDB(host="localhost", port=6379).select_graph(ws_name)
        q(
            ws,
            "UNWIND $rows AS row MATCH (g:Gap {method_family_id: row.slug}) SET g.method_family = row.family",
            {"rows": [row for row in rows if row["label"] == "Method"]},
        )
    print(f"applied names {len(named)}", flush=True)


def apply_links():
    incoming = defaultdict(list)
    llm_rows = 0
    with LINK_OUT.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            llm_rows += 1
            for link in row["links"]:
                incoming[(row["arxiv_id"], link["kind"], link["index"])].append(link)
    alias = {}
    with (EXTRACT / "aliases.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            alias[(row["kind"], row["label"].casefold())] = row["canonical_id"]
    path = EXTRACT / "claim_links.jsonl"
    counts = defaultdict(int)
    rewritten = []
    added = 0
    graph_rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index = counts[(row["arxiv_id"], row["kind"])]
        counts[(row["arxiv_id"], row["kind"])] += 1
        existing = {(link["role"], link["label"].casefold()) for link in row["links"]}
        for link in incoming.get((row["arxiv_id"], row["kind"], index), []):
            identity = (link["role"], link["label"].casefold())
            if identity in existing:
                continue
            row["links"].append(
                {
                    "role": link["role"],
                    "label": link["label"],
                    "sentence_number": link["sentence_number"],
                    "source": "llm",
                }
            )
            existing.add(identity)
            added += 1
            slug = alias.get((link["role"], link["label"].casefold()))
            if slug:
                graph_rows.append(
                    {
                        "claim_id": f"{row['arxiv_id']}:{row['kind']}:{index}",
                        "slug": slug,
                        "rel": CLAIM_EDGE[link["role"]],
                        "node": NODE_LABEL[link["role"]],
                        "span": link["sentence_number"],
                    }
                )
        rewritten.append(row)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rewritten), encoding="utf-8")
    graph = FalkorDB(host="localhost", port=6379).select_graph(GRAPH)
    for rel in ("ABOUT_METHOD", "ON_DATASET", "MEASURED_BY"):
        chunk = [row for row in graph_rows if row["rel"] == rel]
        if not chunk:
            continue
        node = chunk[0]["node"]
        for start in range(0, len(chunk), 200):
            q(
                graph,
                "UNWIND $rows AS row MATCH (c:Claim {id: row.claim_id}) "
                f"MATCH (n:{node} {{slug: row.slug}}) "
                f"MERGE (c)-[e:{rel} {{link_source: 'llm', span: row.span}}]->(n)",
                {"rows": chunk[start : start + 200]},
            )
    print(f"link files {llm_rows} new links {added}", flush=True)
    return added


def update_manifest(new_links):
    path = EXTRACT / "manifest.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    sources = {"sentence": 0, "lexical": 0, "llm": 0}
    with_link = 0
    with (EXTRACT / "claim_links.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["links"]:
                with_link += 1
            for link in row["links"]:
                sources[link["source"]] = sources.get(link["source"], 0) + 1
    report["claims_with_a_link"] = with_link
    report["links_by_source"] = sources
    report["model_linking_pass"] = (
        f"gpt-4.1-mini on unlinked claims, {new_links} new links, one paper per call"
    )
    report["canonical_names"] = "multi-member clusters named by gpt-4.1-mini; singletons keep their spelling"
    report["model_job_tokens"] = {
        "prompt": spend["prompt"],
        "cached": spend["cached"],
        "completion": spend["completion"],
        "usd": round(spend["usd"], 4),
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    if MODEL != ALLOWED_MODEL:
        raise SystemExit("refusing model")
    key = load_env().get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is missing from .env")
    context = ssl_context()
    run_naming(key, context)
    apply_names()
    run_linking(key, context)
    added = apply_links()
    update_manifest(added)
    print(
        json.dumps(
            {"usd": round(spend["usd"], 4), "prompt": spend["prompt"], "completion": spend["completion"], "new_links": added},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
