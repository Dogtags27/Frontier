"""Procedure yield fields, checked on a throwaway graph and then deleted."""

import pytest
from falkordb.asyncio import FalkorDB

from app.constants import get_settings

PROBE = "b0_algo_probe"
CREATE = (
    "CREATE (:N {id:'a'})-[:E]->(:N {id:'b'})-[:E]->(:N {id:'c'}), "
    "(:N {id:'d'})-[:E]->(:N {id:'e'})"
)
PAGERANK = "CALL algo.pageRank('N', 'E') YIELD node, score RETURN node.id, score"
WCC = "CALL algo.WCC() YIELD node, componentId RETURN node.id, componentId"
BFS = "MATCH (a:N {id:'a'}) CALL algo.BFS(a, 3, 'E') YIELD nodes RETURN nodes"
COMMUNITY = "CALL algo.labelPropagation() YIELD node, communityId RETURN node.id, communityId"
SHORTEST = (
    "MATCH (a:N {id:'a'}), (c:N {id:'c'}) "
    "CALL algo.SPpaths({sourceNode: a, targetNode: c}) YIELD path RETURN path"
)


@pytest.mark.asyncio
async def test_algorithm_yield_fields():
    settings = get_settings()
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    graph = db.select_graph(PROBE)
    try:
        try:
            await graph.delete()
        except Exception:
            pass
        graph = db.select_graph(PROBE)
        await graph.query(CREATE)

        ranks = (await graph.query(PAGERANK)).result_set
        assert {row[0] for row in ranks} == {"a", "b", "c", "d", "e"}
        assert all(isinstance(row[1], float) for row in ranks)

        components = {row[0]: row[1] for row in (await graph.query(WCC)).result_set}
        assert components["a"] == components["b"] == components["c"]
        assert components["d"] == components["e"]
        assert components["a"] != components["d"]

        nodes = (await graph.query(BFS)).result_set[0][0]
        reached = {node.properties["id"] for node in nodes}
        assert "b" in reached and "d" not in reached

        communities = (await graph.query(COMMUNITY)).result_set
        assert {row[0] for row in communities} == {"a", "b", "c", "d", "e"}

        path = (await graph.query(SHORTEST)).result_set
        assert path
    finally:
        try:
            await db.select_graph(PROBE).delete()
        finally:
            await db.aclose()
