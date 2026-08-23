from collections import deque


ALLOWED_NODE_TYPES = {
    "root", "concept", "definition", "comparison", "process",
    "example", "exam_point", "warning",
}
ALLOWED_IMPORTANCE = {"high", "medium", "low"}


class MindMapValidationError(ValueError):
    pass


def _number(value, default: float) -> float:
    try:
        return min(max(float(value), 0), 1)
    except (TypeError, ValueError):
        return default


def normalize_map(result: dict, *, focus_question: str, mode: str, max_depth: int,
                  max_nodes: int, allowed_source_ids: set[str]) -> dict:
    raw_nodes = result.get("nodes") or []
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise MindMapValidationError("没有生成有效节点")

    nodes: list[dict] = []
    id_redirect: dict[str, str] = {}
    seen_ids: set[str] = set()
    seen_labels: dict[str, str] = {}
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id") or f"node-{index}").strip()
        if not node_id or node_id in seen_ids:
            node_id = f"node-{index}"
        label = str(raw.get("label") or raw.get("title") or "").strip()[:32]
        if not label:
            continue
        label_key = "".join(label.casefold().split())
        if label_key in seen_labels:
            id_redirect[node_id] = seen_labels[label_key]
            continue
        seen_ids.add(node_id)
        seen_labels[label_key] = node_id
        raw_sources = raw.get("sourceIds", raw.get("citationIds", [])) or []
        source_ids = list(dict.fromkeys(
            str(item) for item in raw_sources if str(item) in allowed_source_ids
        ))
        nodes.append({
            "id": node_id,
            "parentId": None if raw.get("parentId") is None else str(raw.get("parentId")),
            "label": label,
            "type": str(raw.get("type") or raw.get("nodeType") or "concept")
                    if str(raw.get("type") or raw.get("nodeType") or "concept") in ALLOWED_NODE_TYPES
                    else "concept",
            "level": 0,
            "importance": _number(raw.get("importance"), 0.6),
            "examImportance": str(raw.get("examImportance") or "medium")
                              if str(raw.get("examImportance") or "medium") in ALLOWED_IMPORTANCE
                              else "medium",
            "mastery": None,
            "description": str(raw.get("description") or "").strip()[:600],
            "sourceIds": source_ids,
            "order": int(raw.get("order") or index),
        })

    if not nodes:
        raise MindMapValidationError("没有生成有效节点")
    ids = {node["id"] for node in nodes}
    roots = [node for node in nodes if node["parentId"] is None]
    root = roots[0] if roots else nodes[0]
    root["parentId"] = None
    root["type"] = "root"
    for node in nodes:
        if node is root:
            continue
        parent = id_redirect.get(str(node["parentId"]), str(node["parentId"]))
        node["parentId"] = parent if parent in ids and parent != node["id"] else root["id"]
    for extra_root in roots[1:]:
        extra_root["parentId"] = root["id"]
        extra_root["type"] = "concept"

    children: dict[str, list[dict]] = {}
    for node in nodes:
        if node["parentId"] is not None:
            children.setdefault(node["parentId"], []).append(node)
    for values in children.values():
        values.sort(key=lambda item: (-item["importance"], item["order"]))

    kept: list[dict] = []
    queue = deque([(root, 0)])
    visited: set[str] = set()
    while queue and len(kept) < max_nodes:
        node, level = queue.popleft()
        if node["id"] in visited:
            continue
        visited.add(node["id"])
        node["level"] = level
        kept.append(node)
        if level < max_depth:
            limit = 5 if level == 0 else 6
            queue.extend((child, level + 1) for child in children.get(node["id"], [])[:limit])

    kept_ids = {node["id"] for node in kept}
    for node in kept:
        if node is not root and not node["sourceIds"]:
            raise MindMapValidationError(f"节点“{node['label']}”缺少有效资料来源")

    raw_edges = result.get("edges") or []
    relation_by_pair: dict[tuple[str, str], str] = {}
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        source = id_redirect.get(str(edge.get("source", edge.get("from", ""))), str(edge.get("source", edge.get("from", ""))))
        target = id_redirect.get(str(edge.get("target", edge.get("to", ""))), str(edge.get("target", edge.get("to", ""))))
        if source in kept_ids and target in kept_ids and source != target:
            relation_by_pair[(source, target)] = str(edge.get("relation") or "关联")[:20]
    edges = []
    for node in kept:
        parent = node["parentId"]
        if parent is not None and parent in kept_ids:
            edges.append({
                "source": parent,
                "target": node["id"],
                "relation": relation_by_pair.pop((parent, node["id"]), "包含"),
            })
    for (source, target), relation in relation_by_pair.items():
        edges.append({"source": source, "target": target, "relation": relation})

    return {
        "title": str(result.get("title") or root["label"]).strip()[:120],
        "focusQuestion": focus_question,
        "summary": str(result.get("summary") or "").strip()[:800],
        "mode": mode,
        "nodes": kept,
        "edges": edges,
        "evidenceInsufficient": bool(result.get("evidenceInsufficient", False)),
    }

