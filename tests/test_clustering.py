"""Cluster algorithm tests covering the 9 May 2026 changes.

Focus: the single-village exception (#18) and the orphan merge post-pass
(#19) introduced in clustering.cluster_block_commodity. The existing greedy
loop is exercised incidentally by the 'tight cluster' rows.
"""
import clustering


def test_single_village_with_huge_count_becomes_its_own_cluster(sample_villages_df):
    """A village whose member count already exceeds max_cluster_members
    should be emitted as a single-village cluster (Faiz #18, 2026-05-09).
    Without this pre-pass the greedy loop would reject it because adding
    any neighbour blows past max_cluster_members."""
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy",
    )
    singletons = [c for c in clusters if len(c.villages) == 1]
    assert singletons, "expected at least one single-village cluster"
    giant = next((c for c in singletons
                  if c.villages[0]["vill_name"] == "Village_Giant"), None)
    assert giant is not None, "Village_Giant should be a standalone cluster"
    assert giant.total_members == 200
    assert giant.max_span_km == 0.0


def test_orphan_village_merges_into_nearest_cluster(sample_villages_df):
    """The lone 3-member dairy village near the tight cluster should be
    absorbed by the orphan-merge post-pass (Faiz #19, 2026-05-09)."""
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy",
    )
    # The orphan must end up in *some* cluster - not floating free.
    found_in = [c for c in clusters
                if any(v["vill_name"] == "Village_Orphan" for v in c.villages)]
    assert found_in, "Village_Orphan should be merged into a cluster"
    host = found_in[0]
    # And specifically the tight cluster, not the Giant standalone.
    village_names = {v["vill_name"] for v in host.villages}
    assert "Village_A" in village_names, (
        "Orphan should join the nearby tight cluster, "
        f"not the Giant (got {village_names})"
    )


def test_orphan_merge_respects_soft_cap():
    """Orphans should not be merged when doing so would exceed
    3 * max_cluster_members - prevents runaway absorption."""
    import pandas as pd
    rows = [
        # Two normal villages forming a cluster at max_cluster_members
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V1", "lat": 26.5, "long": 92.0, "Dairy": 25},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V2", "lat": 26.501, "long": 92.001, "Dairy": 25},
        # A nearby orphan that would push past the soft cap (3 * 50 = 150)
        # if blindly absorbed.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "Big_Orphan", "lat": 26.510, "long": 92.010, "Dairy": 120},
    ]
    df = pd.DataFrame(rows)
    clusters = clustering.cluster_block_commodity(df, "B", "Dairy")
    # Big_Orphan is itself > max_cluster_members (50), so it becomes a
    # single-village cluster via #18 - and that's exactly what we want:
    # it doesn't get crammed into the existing tight cluster.
    for c in clusters:
        names = {v["vill_name"] for v in c.villages}
        if "V1" in names:
            assert "Big_Orphan" not in names, (
                "Big_Orphan should not be absorbed - it would blow the soft cap"
            )


def test_emit_cluster_centroid_and_span_are_recomputed(sample_villages_df):
    """_emit_cluster (now used by pre-pass, main loop, and orphan merge)
    must produce coherent centroid/max_span_km from the village list."""
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy",
    )
    for c in clusters:
        assert c.total_members == sum(v["members"] for v in c.villages)
        # Centroid lat/lon must be within the bounding box of member villages.
        lats = [v["lat"] for v in c.villages]
        lons = [v["long"] for v in c.villages]
        assert min(lats) <= c.centroid_lat <= max(lats)
        assert min(lons) <= c.centroid_lon <= max(lons)
        # Span >= 0; for single-village clusters it should be exactly 0.
        assert c.max_span_km >= 0.0
        if len(c.villages) == 1:
            assert c.max_span_km == 0.0
