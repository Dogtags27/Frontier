"""Corpus search. Vector distance, title and name lookup, and abstract text, fused by rank."""

import re
import time

from app.core import BadRequest
from app.models.queries import Q, SQL
from app.models.schemas import SearchQuery
from app.services.workspace import graph_name_for

RRF_K = 60
VECTOR_CAP = 160
# Direct lookups outweigh a semantic-only hit, without dropping the vector channel.
CHANNEL_WEIGHT = {"vector": 1.0, "title": 1.6, "name": 1.6, "abstract": 1.3}
TITLE_WORD_BONUS = 0.025
CLAIM_WORD_BONUS = 0.015
STOP_WORDS = frozenset(
    "a an the of for and or on in to with from by is are was were be as at into over under "
    "between about than then this that these those using use used via per not no it its their "
    "we our how what which who when where".split()
)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _num(value, default=0):
    if value is None:
        return default
    return value


def fulltext_query(text: str) -> str:
    """Drop characters the full-text parser treats as operators."""
    return " ".join(re.sub(r"[^0-9A-Za-z ]+", " ", text).split())


def content_words(text: str) -> list[str]:
    """Query words that can prefer a literal title or claim, with stop words removed."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if len(word) > 2 and word not in STOP_WORDS]


def word_overlap(text: str, words: list[str]) -> float:
    if not words or not text:
        return 0.0
    haystack = text.lower()
    return sum(1 for word in words if word in haystack) / len(words)


def _paper(row) -> dict:
    return {
        "arxiv_id": _text(row[0]),
        "title": _text(row[1]),
        "year": int(_num(row[2])),
        "category": _text(row[3]),
        "layer": _text(row[4]),
        "paper_kind": _text(row[5]),
    }


class SearchService:
    def __init__(self, graph, pg, llm, settings):
        self.graph = graph
        self.pg = pg
        self.llm = llm
        self.settings = settings

    async def search(self, principal, request: SearchQuery) -> dict:
        request = request.clamped()
        if request.mode == "semantic" and not request.q:
            raise BadRequest("semantic search needs text")
        started = time.perf_counter()
        channels: dict[str, list[str]] = {}
        props: dict[str, dict] = {}
        claims: dict[str, dict] = {}
        distances: dict[str, float] = {}
        if request.q and request.mode in ("semantic", "hybrid"):
            vector = await self.llm.embed(principal, request.q)
            await self._vector(vector, request, channels, props, claims, distances)
        if request.mode != "semantic":
            await self._metadata(request, channels, props)
        await self._hydrate(channels, props)
        allowed = await self._relation_ids(request)
        marks = await self._marks(principal)
        hits = self._combine(channels, props, claims, distances, marks, request, allowed)
        await self._attach_citations(hits)
        hits = self._sort(hits, request.sort)
        page = hits[request.cursor : request.cursor + request.limit]
        await self._snippets(page)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        next_cursor = request.cursor + request.limit if request.cursor + request.limit < len(hits) else None
        return {"items": page, "next_cursor": next_cursor, "elapsed_ms": elapsed_ms}

    async def suggest(self, kind: str, q: str, limit: int = 8) -> dict:
        text = q.strip()
        limit = min(max(limit, 1), 20)
        if len(text) < 2:
            return {"items": []}
        if kind == "task":
            rows = await self._names(Q.FULLTEXT_TASKS, text, limit)
        elif kind == "method":
            rows = await self._names(Q.FULLTEXT_METHODS, text, limit)
        elif kind == "dataset":
            rows = await self._rows(Q.DATASETS_CONTAIN, {"q": text, "limit": limit})
        elif kind == "metric":
            rows = await self._rows(Q.METRICS_CONTAIN, {"q": text, "limit": limit})
        elif kind == "paper":
            cleaned = fulltext_query(text)
            if not cleaned:
                return {"items": []}
            rows = await self._rows(Q.FULLTEXT_PAPERS, {"q": cleaned, "limit": limit})
            return {
                "items": [
                    {"arxiv_id": _text(row[0]), "title": _text(row[1]), "year": int(_num(row[2]))} for row in rows
                ]
            }
        else:
            raise BadRequest("kind must be task, method, dataset, metric, or paper")
        return {"items": [{"slug": _text(row[0]), "name": _text(row[1])} for row in rows]}

    async def _vector(self, vector, request, channels, props, claims, distances) -> None:
        k = min(max(request.limit * 5, 25), 80)
        while True:
            for row in await self._rows(Q.VECTOR_PAPERS, {"k": k, "vector": vector}):
                paper = _paper(row)
                props[paper["arxiv_id"]] = paper
                distances[paper["arxiv_id"]] = float(row[6])
            for row in await self._rows(Q.VECTOR_CLAIMS, {"k": k, "vector": vector}):
                arxiv_id = _text(row[0])
                distance = float(row[5])
                current = claims.get(arxiv_id)
                if current is None or distance < current["distance"]:
                    claims[arxiv_id] = {
                        "id": _text(row[1]),
                        "kind": _text(row[2]),
                        "label": _text(row[3]),
                        "span": int(_num(row[4])),
                        "distance": distance,
                    }
                distances[arxiv_id] = min(distances.get(arxiv_id, distance), distance)
            channels["vector"] = sorted(distances, key=lambda arxiv_id: (distances[arxiv_id], arxiv_id))
            kept = sum(1 for arxiv_id in channels["vector"] if arxiv_id in props and self._props_ok(props[arxiv_id], request))
            if kept >= request.limit or k >= VECTOR_CAP or not request.has_filters():
                break
            k = min(k * 2, VECTOR_CAP)

    async def _metadata(self, request, channels, props) -> None:
        if not request.q:
            for row in await self._rows(Q.ALL_PAPERS, {}):
                paper = _paper(row)
                props[paper["arxiv_id"]] = paper
            channels["filter"] = list(props)
            return
        text = fulltext_query(request.q)
        if text:
            for row in await self._rows(Q.FULLTEXT_PAPERS, {"q": text, "limit": 40}):
                paper = _paper(row)
                props[paper["arxiv_id"]] = paper
                channels.setdefault("title", [])
                if paper["arxiv_id"] not in channels["title"]:
                    channels["title"].append(paper["arxiv_id"])
            await self._named(Q.FULLTEXT_TASKS, Q.PAPERS_FOR_TASKS, text, channels, props)
            await self._named(Q.FULLTEXT_METHODS, Q.PAPERS_FOR_METHODS, text, channels, props)
        if len(request.q) >= 3:
            await self._named(Q.DATASETS_CONTAIN, Q.PAPERS_FOR_DATASETS, request.q, channels, props)
            await self._named(Q.METRICS_CONTAIN, Q.PAPERS_FOR_METRICS, request.q, channels, props)
            found = await self.pg.fetch(SQL.ABSTRACT_SEARCH, (request.q, request.q, 40))
            channels["abstract"] = [_text(row[0]) for row in found]

    async def _named(self, name_query, paper_query, text, channels, props) -> None:
        names = await self._names(name_query, text, 5)
        slugs = [_text(row[0]) for row in names if row[0]]
        if not slugs:
            return
        ordered = channels.setdefault("name", [])
        for row in await self._rows(paper_query, {"slugs": slugs, "limit": 40}):
            paper = _paper(row)
            props[paper["arxiv_id"]] = paper
            if paper["arxiv_id"] not in ordered:
                ordered.append(paper["arxiv_id"])

    async def _names(self, query, text, limit):
        if query in (Q.FULLTEXT_TASKS, Q.FULLTEXT_METHODS):
            cleaned = fulltext_query(text)
            if not cleaned:
                return []
            return await self._rows(query, {"q": cleaned, "limit": limit})
        return await self._rows(query, {"q": text, "limit": limit})

    async def _hydrate(self, channels, props) -> None:
        missing = []
        for ids in channels.values():
            for arxiv_id in ids:
                if arxiv_id not in props and arxiv_id not in missing:
                    missing.append(arxiv_id)
        if not missing:
            return
        for row in await self._rows(Q.PAPERS_BY_IDS, {"ids": missing}):
            paper = _paper(row)
            props[paper["arxiv_id"]] = paper

    async def _relation_ids(self, request: SearchQuery) -> set[str] | None:
        sets = []
        if request.task:
            sets.append(await self._id_set(Q.TASK_IDS, {"name": request.task}))
        if request.method:
            sets.append(await self._id_set(Q.METHOD_IDS, {"name": request.method}))
        if request.dataset:
            sets.append(await self._id_set(Q.DATASET_IDS, {"name": request.dataset}))
        if request.metric:
            sets.append(await self._id_set(Q.METRIC_IDS, {"name": request.metric}))
        if request.cites:
            sets.append(await self._id_set(Q.CITING, {"id": request.cites}))
        if request.cited_by:
            sets.append(await self._id_set(Q.CITED_BY, {"id": request.cited_by}))
        if not sets:
            return None
        allowed = sets[0]
        for other in sets[1:]:
            allowed &= other
        return allowed

    async def _id_set(self, query, params) -> set[str]:
        return {_text(row[0]) for row in await self._rows(query, params)}

    async def _marks(self, principal) -> dict[str, str]:
        try:
            rows = await self.graph.run(graph_name_for(principal.user_id), Q.PAPER_MARKS, {}, ro=True)
        except Exception:
            return {}
        return {_text(row[0]): _text(row[1]) or "read" for row in rows}

    def _combine(self, channels, props, claims, distances, marks, request, allowed) -> list[dict]:
        if channels.get("filter") and not request.q:
            order = channels["filter"]
            scores = {arxiv_id: 0.0 for arxiv_id in order}
            sources = {arxiv_id: ["filter"] for arxiv_id in order}
        else:
            scores, sources = {}, {}
            for name, ids in channels.items():
                if name == "filter":
                    continue
                weight = CHANNEL_WEIGHT.get(name, 1.0)
                for rank, arxiv_id in enumerate(ids):
                    scores[arxiv_id] = scores.get(arxiv_id, 0.0) + weight / (RRF_K + rank + 1)
                    sources.setdefault(arxiv_id, []).append(name)
            words = content_words(request.q)
            for arxiv_id in scores:
                paper = props.get(arxiv_id)
                if paper is not None:
                    scores[arxiv_id] += TITLE_WORD_BONUS * word_overlap(paper.get("title", ""), words)
                claim = claims.get(arxiv_id)
                if claim is not None:
                    scores[arxiv_id] += CLAIM_WORD_BONUS * word_overlap(claim.get("label", ""), words)
            order = sorted(scores, key=lambda arxiv_id: (-scores[arxiv_id], arxiv_id))
        hits = []
        for arxiv_id in order:
            paper = props.get(arxiv_id)
            if paper is None or not self._props_ok(paper, request):
                continue
            if allowed is not None and arxiv_id not in allowed:
                continue
            state = marks.get(arxiv_id, "unread")
            if request.unread_only and state != "unread":
                continue
            claim = claims.get(arxiv_id)
            hits.append(
                {
                    **paper,
                    "score": round(scores.get(arxiv_id, 0.0), 6),
                    "distance": distances.get(arxiv_id),
                    "matched_by": sources.get(arxiv_id, []),
                    "claim": None if claim is None else {key: claim[key] for key in ("id", "kind", "label", "span")},
                    "snippet": "",
                    "status": state,
                    "citations": 0,
                }
            )
        return hits

    def _props_ok(self, paper: dict, request: SearchQuery) -> bool:
        if request.year_from is not None and paper["year"] < request.year_from:
            return False
        if request.year_to is not None and paper["year"] > request.year_to:
            return False
        if request.category and paper["category"] != request.category:
            return False
        if request.layer and paper["layer"] != request.layer:
            return False
        if request.paper_kind and paper["paper_kind"] != request.paper_kind:
            return False
        return True

    def _sort(self, hits: list[dict], sort: str) -> list[dict]:
        if sort == "relevance" and hits and all(hit["score"] == 0 for hit in hits):
            sort = "year_desc"
        if sort == "year_desc":
            return sorted(hits, key=lambda hit: (-hit["year"], hit["title"], hit["arxiv_id"]))
        if sort == "year_asc":
            return sorted(hits, key=lambda hit: (hit["year"], hit["title"], hit["arxiv_id"]))
        if sort == "title":
            return sorted(hits, key=lambda hit: (hit["title"].lower(), hit["arxiv_id"]))
        if sort == "citations":
            return sorted(hits, key=lambda hit: (-hit["citations"], hit["title"], hit["arxiv_id"]))
        return hits

    async def _attach_citations(self, hits: list[dict]) -> None:
        """Citations are papers inside this corpus that cite the hit, not an outside index."""
        if not hits:
            return
        rows = await self._rows(Q.CITATION_COUNTS, {"ids": [hit["arxiv_id"] for hit in hits]})
        counts = {_text(row[0]): int(row[1]) for row in rows}
        for hit in hits:
            hit["citations"] = counts.get(hit["arxiv_id"], 0)

    async def _snippets(self, page: list[dict]) -> None:
        if not page:
            return
        ids = [hit["arxiv_id"] for hit in page]
        abstracts = {_text(row[0]): _text(row[1]) for row in await self.pg.fetch(SQL.PAPERS_BY_IDS, (ids,))}
        wanted = [hit for hit in page if hit["claim"]]
        sentences = {}
        if wanted:
            rows = await self.pg.fetch(
                SQL.SENTENCES_FOR,
                ([hit["arxiv_id"] for hit in wanted], [hit["claim"]["span"] for hit in wanted]),
            )
            sentences = {(_text(row[0]), int(row[1])): _text(row[2]) for row in rows}
        for hit in page:
            claim = hit["claim"]
            if claim:
                hit["snippet"] = sentences.get((hit["arxiv_id"], claim["span"]), "")
            if not hit["snippet"]:
                hit["snippet"] = abstracts.get(hit["arxiv_id"], "")

    async def _rows(self, query, params):
        return await self.graph.run(self.settings.corpus_graph, query, params, ro=True)
