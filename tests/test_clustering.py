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


def test_orphan_merge_respects_member_and_span_caps(sample_villages_df):
    """Orphan-merge must never break the member ceiling or span cap (#S2,
    2026-05-25; village-count cap removed by LEAF-43). The member ceiling
    does NOT apply to Pass-A singletons - they are the explicit single-village
    exception for villages >=max_cluster_members that the greedy loop can't grow."""
    p = clustering.DEFAULT_PARAMS
    clusters = clustering.cluster_block_commodity(
        sample_villages_df, "TESTBLK", "Dairy",
    )
    for c in clusters:
        if c.provisional:
            continue
        # Pass-A singletons may legitimately exceed max_cluster_members; the
        # ceiling applies only to grown / merged clusters.
        if len(c.villages) > 1:
            assert c.total_members <= p["max_cluster_members"], (
                f"{c.cluster_id} has {c.total_members} members (cap {p['max_cluster_members']})"
            )
        assert c.max_span_km <= p["max_radius_km"], (
            f"{c.cluster_id} span {c.max_span_km} exceeds {p['max_radius_km']} km"
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


def _rebalance_fixture():
    """A donor cluster pinned at the 150-member ceiling next to a below-floor
    provisional pair - the post-LEAF-43 ATTAREEKHATLINE case. The main pass
    fills the donor (D1..D4 totalling 150 = the ceiling), so Pass C can't
    absorb P1/P2 (12+10=22) because adding either blows the member ceiling.
    P1+P2 stay provisional unless Pass E rescues. A safe borrow exists:
    P borrows D2 (15 mem), donor falls to 135 mem (still valid), P jumps to
    37 mem (fundable)."""
    import pandas as pd
    rows = [
        # Donor at the member ceiling so Pass C can't absorb P1/P2.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D1", "lat": 26.500, "long": 92.000, "Dairy": 70},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D2", "lat": 26.502, "long": 92.000, "Dairy": 15},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D3", "lat": 26.500, "long": 92.002, "Dairy": 35},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D4", "lat": 26.502, "long": 92.002, "Dairy": 30},
        # Provisional pair ~2 km away. Within the 5 km borrow span, but the
        # donor is already at 150 mem so Pass C can't absorb them.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "P1", "lat": 26.520, "long": 92.000, "Dairy": 12},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "P2", "lat": 26.522, "long": 92.000, "Dairy": 10},
    ]
    return pd.DataFrame(rows)


def test_rebalance_off_by_default_leaves_provisional():
    """Default params: rebalance is OFF, so the below-floor pair stays a
    provisional group (the conservative, prod-safe baseline)."""
    clusters = clustering.cluster_block_commodity(_rebalance_fixture(), "B", "Dairy")
    pgroup = next((c for c in clusters
                   if {"P1", "P2"} <= {v["vill_name"] for v in c.villages}), None)
    assert pgroup is not None, "P1/P2 should be surfaced as a group"
    assert pgroup.provisional is True
    assert pgroup.total_members == 22  # below the 30 floor, not rescued


def test_rebalance_rescues_provisional_with_safe_borrow():
    """rebalance=True: the provisional pair borrows ONE village from the full
    donor and becomes fundable, while the donor stays valid and no cap breaks."""
    p = clustering.DEFAULT_PARAMS
    clusters = clustering.cluster_block_commodity(
        _rebalance_fixture(), "B", "Dairy", params={"rebalance": True})

    pgroup = next((c for c in clusters
                   if {"P1", "P2"} <= {v["vill_name"] for v in c.villages}), None)
    assert pgroup is not None
    assert pgroup.provisional is False, "the pair should be rescued to fundable"
    assert pgroup.total_members >= p["min_cluster_members"]
    assert pgroup.max_span_km <= p["max_radius_km"]

    # Every fundable cluster still respects the surviving caps; the donor stays
    # valid. Village-count caps removed by LEAF-43.
    for c in clusters:
        if c.provisional:
            continue
        assert c.max_span_km <= p["max_radius_km"]
        assert c.total_members <= p["max_cluster_members"]
        assert c.total_members >= p["min_cluster_members"]


def test_rebalance_is_deterministic():
    """Two runs with rebalance on must yield identical cluster membership."""
    def sig():
        cs = clustering.cluster_block_commodity(
            _rebalance_fixture(), "B", "Dairy", params={"rebalance": True})
        return sorted((tuple(sorted(v["vill_name"] for v in c.villages)),
                       c.total_members, c.provisional) for c in cs)
    assert sig() == sig()


def test_five_villages_within_5km_form_one_cluster():
    """LEAF-43: with the village-count cap removed, five villages that all
    sit within max_radius_km of each other and whose members sum to a
    valid funding band MUST land in one cluster (was two clusters of 2+3
    under the old 2-4 village rule, or a chopped first-4 + 1 orphan)."""
    import pandas as pd
    # Five tight villages ~0.3 km apart, member counts sum to 65 (in band).
    rows = [
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V1", "lat": 26.500, "long": 92.000, "Dairy": 15},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V2", "lat": 26.502, "long": 92.000, "Dairy": 13},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V3", "lat": 26.500, "long": 92.002, "Dairy": 13},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V4", "lat": 26.502, "long": 92.002, "Dairy": 12},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "V5", "lat": 26.501, "long": 92.001, "Dairy": 12},
    ]
    clusters = clustering.cluster_block_commodity(pd.DataFrame(rows), "B", "Dairy")
    fundables = [c for c in clusters if not c.provisional]
    assert len(fundables) == 1, f"expected one fundable cluster, got {len(fundables)}"
    c = fundables[0]
    assert len(c.villages) == 5, f"expected five villages in the cluster, got {len(c.villages)}"
    assert c.total_members == 65
    assert c.max_span_km <= 5.0


def test_single_village_30_member_cluster_is_fundable():
    """LEAF-43: a single village with members in the funding band is itself a
    valid fundable cluster (was rejected by the old 2-village floor; Pass A
    only handled >=150-member singletons)."""
    import pandas as pd
    rows = [
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "LoneBig", "lat": 26.500, "long": 92.000, "Dairy": 80},
    ]
    clusters = clustering.cluster_block_commodity(pd.DataFrame(rows), "B", "Dairy")
    fundables = [c for c in clusters if not c.provisional]
    assert len(fundables) == 1
    assert fundables[0].villages[0]["vill_name"] == "LoneBig"
    assert fundables[0].total_members == 80


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
