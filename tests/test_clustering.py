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


def test_orphan_merge_respects_village_and_span_caps(sample_villages_df):
    """Orphan-merge must never break the village-count or span caps (#S2,
    2026-05-25). The fixture's tight cluster is already at the 4-village cap, so
    Village_Orphan cannot be stapled on - that was the BARTANGLA bug where the
    orphan-merge produced a 6-village / 5.139 km cluster."""
    p = clustering.DEFAULT_PARAMS
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy",
    )
    for c in clusters:
        if c.provisional:
            continue
        assert len(c.villages) <= p["max_villages_per_cluster"], (
            f"{c.cluster_id} has {len(c.villages)} villages (cap {p['max_villages_per_cluster']})"
        )
        assert c.max_span_km <= p["max_radius_km"], (
            f"{c.cluster_id} span {c.max_span_km} exceeds {p['max_radius_km']} km"
        )
    # The orphan is NOT crammed into the full tight cluster.
    for c in clusters:
        names = {v["vill_name"] for v in c.villages}
        if "Village_A" in names:
            assert "Village_Orphan" not in names, (
                "Orphan should not be force-merged into the full 4-village cluster"
            )


def test_orphan_surfaced_as_provisional_when_enabled(sample_villages_df):
    """With emit_provisional on, an orphan that fits no valid cluster is surfaced
    as a flagged provisional cluster (Pass D) rather than silently dropped."""
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy", params={"emit_provisional": True},
    )
    found = [c for c in clusters
             if any(v["vill_name"] == "Village_Orphan" for v in c.villages)]
    assert found, "Village_Orphan should be surfaced, not dropped"
    assert found[0].provisional is True, "the surfaced orphan cluster must be flagged provisional"


def test_oversized_orphan_not_absorbed():
    """A village that is itself >= max_cluster_members must not be crammed into
    an existing cluster. It becomes its own single-village cluster via Pass A,
    and the cap-respecting orphan-merge would refuse it anyway (it would blow the
    member cap). Uses max=50 so a 120-member village trips the threshold."""
    import pandas as pd
    rows = [
        # Two normal villages forming a cluster at max_cluster_members=50
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
    clusters = clustering.cluster_block_commodity(
        df, "B", "Dairy", params={"max_cluster_members": 50})
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
