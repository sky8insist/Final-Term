from app.graphs.mixed_graph import build_mixed_graph, fan_out_specialists
from app.graphs.root_graph import build_closure_graph


def test_mixed_graph_fans_out_and_waits_for_dependent_branches():
    graph = build_mixed_graph().get_graph()
    assert fan_out_specialists({}) == ["closure", "emotion"]
    assert {"closure", "planning", "emotion", "safety", "critic"} <= set(graph.nodes)


def test_root_graph_embeds_real_mixed_and_morning_subgraphs():
    graph = build_closure_graph().get_graph()
    assert graph.nodes["mixed"].data is not None
    assert graph.nodes["morning"].data is not None
