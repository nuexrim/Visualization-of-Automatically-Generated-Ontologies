from backend.db.graph_stats import GraphStats, compute_stats


def test_parallel_fks_count_once_and_self_reference_excluded():
    tables = ["a", "b", "c", "d"]
    fks = [("a", "b", 1), ("a", "b", 1), ("b", "a", 1), ("c", "c", 1)]
    assert compute_stats(tables, fks) == GraphStats(V=4, E=1, C=3, mu=0)


def test_composite_fk_excluded():
    assert compute_stats(["a", "b"], [("a", "b", 2)]) == GraphStats(V=2, E=0, C=2, mu=0)


def test_cycle():
    tables = ["a", "b", "c"]
    fks = [("a", "b", 1), ("b", "c", 1), ("c", "a", 1)]
    assert compute_stats(tables, fks) == GraphStats(V=3, E=3, C=1, mu=1)
