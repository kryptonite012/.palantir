"""Knowledge graph queries and graph algorithms (NetworkX over the relational store).

The relational database is the system of record; graphs are materialized on
demand with server-side filters and limits. This is adequate for project
graphs up to roughly 10^5 edges on a workstation; a dedicated graph database
is not justified below that scale (see docs/architecture.md).
"""

from __future__ import annotations

import hashlib
import io
import json
from collections import deque
from typing import Any

import networkx as nx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from project_atlas.core.errors import NotFound, ValidationFailed
from project_atlas.database.models import Entity, Relationship

ALGORITHM_VERSION = f"graph-1.0/networkx-{nx.__version__}"
ASSERTIONS = {"observed", "inferred", "model_suggested", "manual"}
ASSERTION_LABELS = {
    "observed": "Observed in source data",
    "inferred": "Deterministic inference",
    "model_suggested": "Model-suggested hypothesis (unverified)",
    "manual": "Manually asserted by analyst",
}


def _rel_query(project_id: str, rel_types: list[str] | None, assertions: list[str] | None, include_unverified: bool):
    q = select(Relationship).where(Relationship.project_id == project_id, Relationship.status != "rejected")
    if not include_unverified:
        q = q.where(Relationship.status == "active")
    if rel_types:
        q = q.where(Relationship.rel_type.in_(rel_types))
    if assertions:
        bad = set(assertions) - ASSERTIONS
        if bad:
            raise ValidationFailed(f"Unknown assertion kinds: {sorted(bad)}")
        q = q.where(Relationship.assertion.in_(assertions))
    return q


def node_view(e: Entity, degree: int | None = None) -> dict[str, Any]:
    return {"id": e.id, "label": e.display_name, "entity_type": e.entity_type, "degree": degree}


def edge_view(r: Relationship) -> dict[str, Any]:
    return {"id": r.id, "source": r.source_entity_id, "target": r.target_entity_id, "rel_type": r.rel_type,
            "assertion": r.assertion, "assertion_label": ASSERTION_LABELS.get(r.assertion, r.assertion),
            "status": r.status, "confidence": r.confidence,
            "evidence_count": (r.evidence or {}).get("record_count") or len((r.evidence or {}).get("records", []))
            or (1 if r.evidence else 0)}


def build_graph(db: Session, project_id: str, *, entity_types: list[str] | None = None, rel_types: list[str] | None = None,
                assertions: list[str] | None = None, include_unverified: bool = False) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    q = select(Entity).where(Entity.project_id == project_id, Entity.status == "active")
    if entity_types:
        q = q.where(Entity.entity_type.in_(entity_types))
    for e in db.execute(q).scalars():
        g.add_node(e.id, label=e.display_name, entity_type=e.entity_type)
    for r in db.execute(_rel_query(project_id, rel_types, assertions, include_unverified)).scalars():
        if r.source_entity_id in g and r.target_entity_id in g:
            g.add_edge(r.source_entity_id, r.target_entity_id, key=r.id, rel_type=r.rel_type, assertion=r.assertion)
    return g


def graph_state_hash(g: nx.MultiDiGraph) -> str:
    edges = sorted((u, v, k) for u, v, k in g.edges(keys=True))
    payload = json.dumps({"nodes": sorted(g.nodes), "edges": edges})
    return hashlib.sha256(payload.encode()).hexdigest()


def neighborhood(db: Session, project_id: str, *, center: str | None, depth: int, limit: int,
                 entity_types: list[str] | None, rel_types: list[str] | None, assertions: list[str] | None,
                 include_unverified: bool) -> dict[str, Any]:
    depth = max(0, min(depth, 4))
    if center is None:
        # Overview: highest-degree nodes first (degree computed in SQL), progressively loadable via ``limit``.
        from sqlalchemy import func, literal_column, union_all

        rq = _rel_query(project_id, rel_types, assertions, include_unverified).subquery()
        ends = union_all(select(rq.c.source_entity_id.label("eid")), select(rq.c.target_entity_id.label("eid"))).subquery()
        deg = select(ends.c.eid, func.count().label("d")).group_by(ends.c.eid).subquery()
        eq = (select(Entity, func.coalesce(deg.c.d, 0).label("degree")).outerjoin(deg, deg.c.eid == Entity.id)
              .where(Entity.project_id == project_id, Entity.status == "active"))
        if entity_types:
            eq = eq.where(Entity.entity_type.in_(entity_types))
        total_nodes = db.execute(select(func.count()).select_from(eq.subquery())).scalar_one()
        rows = db.execute(eq.order_by(literal_column("degree").desc(), Entity.display_name).limit(limit)).all()
        keep = {e.id for e, _ in rows}
        nodes = [node_view(e, int(d)) for e, d in rows]
        rels = db.execute(select(Relationship).where(Relationship.id.in_(select(rq.c.id)),
                                                     Relationship.source_entity_id.in_(keep),
                                                     Relationship.target_entity_id.in_(keep))).scalars().all() if keep else []
        total_edges = db.execute(select(func.count()).select_from(rq)).scalar_one()
        return {"nodes": nodes, "edges": [edge_view(r) for r in rels], "truncated": total_nodes > limit,
                "total_nodes": total_nodes, "total_edges": total_edges}
    start = db.get(Entity, center)
    if start is None or start.project_id != project_id:
        raise NotFound("Entity not found")
    while start.status == "merged" and start.merged_into_id:
        start = db.get(Entity, start.merged_into_id)
    seen = {start.id: 0}
    frontier = deque([start.id])
    edges: dict[str, Relationship] = {}
    truncated = False
    base = _rel_query(project_id, rel_types, assertions, include_unverified)
    while frontier:
        nid = frontier.popleft()
        if seen[nid] >= depth:
            continue
        for r in db.execute(base.where(or_(Relationship.source_entity_id == nid, Relationship.target_entity_id == nid))).scalars():
            other = r.target_entity_id if r.source_entity_id == nid else r.source_entity_id
            if other not in seen:
                if len(seen) >= limit:
                    truncated = True
                    continue
                seen[other] = seen[nid] + 1
                frontier.append(other)
            edges[r.id] = r
    ents = {e.id: e for e in db.execute(select(Entity).where(Entity.id.in_(list(seen)))).scalars()}
    if entity_types:
        ents = {k: v for k, v in ents.items() if v.entity_type in entity_types or k == start.id}
    nodes = [{**node_view(e), "hops": seen[e.id]} for e in ents.values() if e.status == "active"]
    keep = {n["id"] for n in nodes}
    return {"nodes": nodes, "edges": [edge_view(r) for r in edges.values()
                                      if r.source_entity_id in keep and r.target_entity_id in keep],
            "truncated": truncated, "center": start.id}


def run_algorithm(db: Session, project_id: str, algorithm: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (result, inputs) where inputs fingerprint the graph state."""
    g = build_graph(db, project_id, entity_types=params.get("entity_types"), rel_types=params.get("rel_types"),
                    assertions=params.get("assertions"), include_unverified=bool(params.get("include_unverified")))
    inputs = {"graph_state_sha256": graph_state_hash(g), "nodes": g.number_of_nodes(), "edges": g.number_of_edges()}
    ug = nx.Graph(g)
    top = int(params.get("top", 25))
    labels = nx.get_node_attributes(g, "label")

    def ranked(scores: dict[str, float]) -> list[dict[str, Any]]:
        items = sorted(scores.items(), key=lambda kv: (-kv[1], labels.get(kv[0], "")))[:top]
        return [{"entity_id": k, "label": labels.get(k), "score": round(v, 6)} for k, v in items]

    if g.number_of_nodes() == 0:
        return {"algorithm": algorithm, "empty": True, "note": "Graph has no nodes for the selected filters"}, inputs
    if algorithm == "degree_centrality":
        res = {"ranking": ranked(nx.degree_centrality(ug))}
    elif algorithm == "betweenness_centrality":
        k = None if ug.number_of_nodes() <= 2000 else 500
        res = {"ranking": ranked(nx.betweenness_centrality(ug, k=k, seed=42)),
               "approximate": k is not None, "sample_size": k}
    elif algorithm == "pagerank":
        alpha = float(params.get("alpha", 0.85))
        if not 0 < alpha < 1:
            raise ValidationFailed("alpha must be between 0 and 1")
        scores, iterations = pagerank(nx.DiGraph(g), alpha)
        res = {"ranking": ranked(scores), "alpha": alpha, "iterations": iterations,
               "method": "power iteration, uniform teleport, dangling mass redistributed uniformly, tol=1e-10"}
    elif algorithm == "connected_components":
        comps = sorted((sorted(c) for c in nx.connected_components(ug)), key=lambda c: (-len(c), c[0]))
        res = {"count": len(comps), "sizes": [len(c) for c in comps],
               "components": [{"size": len(c), "members": [{"entity_id": n, "label": labels.get(n)} for n in c[:50]]}
                              for c in comps[:top]]}
    elif algorithm == "communities":
        comms = nx.community.louvain_communities(ug, seed=int(params.get("seed", 42)),
                                                 resolution=float(params.get("resolution", 1.0)))
        comms = sorted((sorted(c) for c in comms), key=lambda c: (-len(c), c[0]))
        res = {"count": len(comms), "modularity": round(nx.community.modularity(ug, comms), 6) if ug.number_of_edges() else None,
               "communities": [{"size": len(c), "members": [{"entity_id": n, "label": labels.get(n)} for n in c[:50]]}
                               for c in comms[:top]],
               "note": "Louvain community detection is heuristic; results depend on the seed and resolution."}
    elif algorithm == "shortest_path":
        src, dst = params.get("source"), params.get("target")
        if src not in g or dst not in g:
            raise ValidationFailed("source and target must be active entities in the filtered graph")
        try:
            paths = list(nx.all_shortest_paths(ug, src, dst))[: int(params.get("max_paths", 5))]
        except nx.NetworkXNoPath:
            paths = []
        res = {"paths": [[{"entity_id": n, "label": labels.get(n)} for n in p] for p in paths],
               "length": (len(paths[0]) - 1) if paths else None, "found": bool(paths)}
    else:
        raise ValidationFailed(f"Unknown graph algorithm {algorithm!r}")
    res["algorithm"] = algorithm
    res["sample_size"] = {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()}
    res["limitations"] = "Computed on relationships as recorded; missing or unobserved relationships are not represented."
    return res, inputs


def pagerank(g: nx.DiGraph, alpha: float = 0.85, tol: float = 1e-10, max_iter: int = 200) -> tuple[dict[str, float], int]:
    """Dependency-free PageRank (NetworkX's default implementation requires SciPy)."""
    n = g.number_of_nodes()
    if n == 0:
        return {}, 0
    rank = dict.fromkeys(g, 1.0 / n)
    out_deg = {u: g.out_degree(u) for u in g}
    for it in range(1, max_iter + 1):
        dangling = alpha * sum(rank[u] for u in g if out_deg[u] == 0) / n
        nxt = dict.fromkeys(g, (1.0 - alpha) / n + dangling)
        for u in g:
            if out_deg[u]:
                share = alpha * rank[u] / out_deg[u]
                for v in g.successors(u):
                    nxt[v] += share
        err = sum(abs(nxt[u] - rank[u]) for u in g)
        rank = nxt
        if err < n * tol:
            return rank, it
    return rank, max_iter


def export_subgraph(db: Session, project_id: str, node_ids: list[str], fmt: str) -> tuple[bytes, str]:
    ents = db.execute(select(Entity).where(Entity.project_id == project_id, Entity.id.in_(node_ids))).scalars().all()
    keep = {e.id for e in ents}
    rels = db.execute(select(Relationship).where(Relationship.project_id == project_id,
                                                 Relationship.source_entity_id.in_(keep),
                                                 Relationship.target_entity_id.in_(keep),
                                                 Relationship.status != "rejected")).scalars().all()
    g = nx.MultiDiGraph()
    for e in ents:
        g.add_node(e.id, label=e.display_name, entity_type=e.entity_type)
    for r in rels:
        g.add_edge(r.source_entity_id, r.target_entity_id, key=r.id, rel_type=r.rel_type, assertion=r.assertion,
                   status=r.status)
    if fmt == "graphml":
        buf = io.BytesIO()
        nx.write_graphml(g, buf)
        return buf.getvalue(), "application/graphml+xml"
    if fmt == "gexf":
        buf = io.BytesIO()
        nx.write_gexf(g, buf)
        return buf.getvalue(), "application/gexf+xml"
    if fmt == "json":
        data = nx.node_link_data(g, edges="edges")
        return json.dumps(data, indent=2, default=str).encode(), "application/json"
    raise ValidationFailed("Format must be graphml, gexf or json")
