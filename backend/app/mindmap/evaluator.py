def evaluate_map(content: dict) -> dict:
    nodes = content["nodes"]
    non_root = [node for node in nodes if node["level"] > 0]
    grounded = [node for node in non_root if node.get("sourceIds")]
    labels = ["".join(str(node["label"]).casefold().split()) for node in nodes]
    redundancy = 1 - (len(set(labels)) / max(len(labels), 1))
    levels = [int(node["level"]) for node in nodes]
    hierarchy = 1.0 if levels and levels[0] == 0 and max(levels) <= 4 else 0.7
    coverage = min(1.0, len(non_root) / 8) if non_root else 0.0
    relevance = 0.93 if content.get("focusQuestion") and non_root else 0.6
    grounding = len(grounded) / max(len(non_root), 1)
    return {
        "relevance": round(relevance, 3),
        "coverage": round(coverage, 3),
        "hierarchy": round(hierarchy, 3),
        "grounding": round(grounding, 3),
        "redundancy": round(redundancy, 3),
    }


def retry_reason(evaluation: dict) -> str | None:
    problems = []
    if evaluation["relevance"] < 0.85:
        problems.append("节点没有充分回答 Focus Question")
    if evaluation["hierarchy"] < 0.85:
        problems.append("知识层级不合理")
    if evaluation["grounding"] < 0.9:
        problems.append("存在没有资料依据的节点")
    if evaluation["redundancy"] > 0.15:
        problems.append("存在重复概念")
    return "；".join(problems) or None

