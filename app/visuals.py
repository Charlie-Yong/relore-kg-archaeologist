"""Render only facts already present in the public query response."""

from __future__ import annotations

import altair as alt

NODE_TYPES = {
    "Project": ("项目", "#32627A"),
    "Issue": ("Issue", "#8256B0"),
    "PullRequest": ("PR", "#007B70"),
    "Commit": ("提交", "#3266AB"),
    "File": ("文件", "#9C5F28"),
    "Function": ("函数", "#57753B"),
    "Release": ("版本", "#A54D67"),
    "Developer": ("开发者", "#376E87"),
    "Decision": ("决定", "#716633"),
    "SourceDocument": ("原文", "#536F78"),
}
RELATION_NAMES = {
    "HasRelease": "发布版本", "ClaimsToClose": "声明关闭", "Closes": "关闭",
    "MergedAs": "合并为", "Authored": "创建", "Merged": "合并", "Touches": "修改文件",
    "Defines": "定义", "ReachableIn": "可达于版本", "MentionsPR": "提到 PR",
    "ChangesTo": "演变为", "Imports": "导入", "ABOUT": "涉及", "EVIDENCED_BY": "由原文支持",
}


def label(entity, fallback):
    props = entity.get("properties", {})
    if entity.get("type") in {"Issue", "PullRequest"} and props.get("number") is not None:
        number = f"#{props['number']}"
        return f"{number} {props['title']}" if props.get("title") else number
    if entity.get("type") == "Commit" and (sha := props.get("sha")):
        return str(sha)[:12]
    return str(entity.get("display_name") or props.get("qualified_name") or props.get("title")
               or props.get("path") or props.get("tag") or props.get("login")
               or props.get("statement") or entity.get("key") or fallback)


def path_evidence(path):
    return set(path.get("evidence_ids", [])) | {
        eid for edge in path.get("relations", []) for eid in edge.get("evidence_ids", [])
    }


def ordered_paths(paths, claims, evidence=()):
    claim_refs = [set(claim.get("evidence_ids", [])) for claim in claims]
    cited = set().union(*claim_refs)
    by_id = {item["evidence_id"]: item["source_id"] for item in evidence}
    claim_sources = [{by_id[eid] for eid in refs if eid in by_id} for refs in claim_refs]

    def score(path):
        related = path_evidence(path)
        related_sources = {by_id[eid] for eid in related if eid in by_id}
        related_sources.update(e.get("properties", {}).get("source_id")
                               for e in path.get("entities", []))
        covered = sum(
            bool(related & refs or related_sources & sources)
            for refs, sources in zip(claim_refs, claim_sources, strict=True)
        )
        return (
            not bool(path.get("relations")), -covered,
            -len(related & cited), -len(path.get("relation_ids", [])),
        )

    return sorted(paths, key=score)


def chain_rows(path):
    """Place nodes in traversal order but derive arrows from the original edge endpoints."""
    entities = {ent["id"]: ent for ent in path.get("entities", [])}
    ids = path.get("entity_ids") or []
    positions = {identity: index * 2 for index, identity in enumerate(ids)}
    nodes = []
    for identity, row in positions.items():
        entity = entities.get(identity, {})
        name, color = NODE_TYPES.get(entity.get("type"), ("实体", "#64748B"))
        nodes.append({"row": row, "name": label(entity, identity), "type": name, "color": color})
    edges = []
    for rel in path.get("relations", []):
        start = positions.get(rel["from_id"])
        end = positions.get(rel["to_id"])
        if start is None or end is None or abs(end - start) != 2:
            continue
        edges.append({"start": start, "end": end, "middle": (start + end) / 2,
                      "arrow": end - (0.36 if end > start else -0.36),
                      "direction": "triangle-down" if end > start else "triangle-up",
                      "name": RELATION_NAMES.get(rel["type"], rel["type"]),
                      "type": rel["type"], "from": label(entities.get(rel["from_id"], {}),
                                                        rel["from_id"]),
                      "to": label(entities.get(rel["to_id"], {}), rel["to_id"])})
    return nodes, edges


def chain_chart(path):
    nodes, edges = chain_rows(path)
    if not nodes or not edges:
        return None
    domain = [nodes[-1]["row"] + 0.6, -0.6]

    def y(field):
        return alt.Y(field=field, type="quantitative", axis=None, scale=alt.Scale(domain=domain))

    ndata = alt.Data(values=nodes)
    edata = alt.Data(values=edges)
    rail = alt.Chart(edata).mark_rule(color="#8DA9B5", strokeWidth=2).encode(
        x=alt.value(22), y=y("start"), y2=alt.Y2("end:Q"),
        tooltip=[alt.Tooltip("type:N", title="关系"), alt.Tooltip("from:N", title="起点"),
                 alt.Tooltip("to:N", title="终点")],
    )
    arrows = alt.Chart(edata).mark_point(filled=True, size=92, color="#537F91").encode(
        x=alt.value(22), y=y("arrow"), shape=alt.Shape("direction:N", scale=None, legend=None),
    )
    dots = alt.Chart(ndata).mark_circle(size=225, opacity=1).encode(
        x=alt.value(22), y=y("row"), color=alt.Color("color:N", scale=None, legend=None),
        tooltip=[alt.Tooltip("type:N", title="类型"), alt.Tooltip("name:N", title="实体")],
    )
    names = alt.Chart(ndata).mark_text(
        align="left", dy=6, fontSize=13, fontWeight="bold", limit=285, color="#163B50",
    ).encode(x=alt.value(44), y=y("row"), text="name:N",
             tooltip=[alt.Tooltip("name:N", title="实体")])
    types = alt.Chart(ndata).mark_text(
        align="left", dy=-9, fontSize=10, fontWeight="bold",
    ).encode(x=alt.value(44), y=y("row"), text="type:N",
             color=alt.Color("color:N", scale=None, legend=None))
    edge_names = alt.Chart(edata).mark_text(
        align="left", color="#517283", fontSize=11, limit=245,
    ).encode(x=alt.value(44), y=y("middle"), text="name:N",
             tooltip=[alt.Tooltip("type:N", title="关系"), alt.Tooltip("from:N", title="起点"),
                      alt.Tooltip("to:N", title="终点")])
    return (
        (rail + arrows + dots + types + names + edge_names)
        .properties(height=max(140, 64 * len(nodes)), background="#F1F8FA")
        .configure_view(stroke=None)
    )
