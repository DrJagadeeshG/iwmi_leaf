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


def _rebalance_fixture():
    """A donor cluster pinned at the 4-village cap with an adjacent below-floor
    provisional pair next to it - the miniature ATTAREEKHATLINE case. The main
    pass fills the donor (D1..D4) first because those four are mutually closest,
    stranding P1+P2 (22 mem) as a provisional group. A single safe borrow can
    rescue them: donor 65->50 mem / 3 villages (still valid), provisional
    22+15=37 mem / 3 villages (fundable)."""
    import pandas as pd
    rows = [
        # Donor: four tight villages ~0.3 km apart -> fills the 4-village cap.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D1", "lat": 26.500, "long": 92.000, "Dairy": 20},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D2", "lat": 26.502, "long": 92.000, "Dairy": 15},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D3", "lat": 26.500, "long": 92.002, "Dairy": 15},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "D4", "lat": 26.502, "long": 92.002, "Dairy": 15},
        # Provisional pair ~2 km away (within the 5 km borrow span, but the donor
        # was already full so the main pass couldn't take them).
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
    assert len(pgroup.villages) <= p["max_villages_per_cluster"]
    assert pgroup.max_span_km <= p["max_radius_km"]

    # Every fundable cluster still respects all caps; the donor stays valid.
    for c in clusters:
        if c.provisional:
            continue
        assert len(c.villages) <= p["max_villages_per_cluster"]
        assert c.max_span_km <= p["max_radius_km"]
        assert c.total_members <= p["max_cluster_members"]
        # Multi-village fundable clusters must clear both floors.
        if len(c.villages) > 1:
            assert c.total_members >= p["min_cluster_members"]
            assert len(c.villages) >= p["min_villages_per_cluster"]


def test_rebalance_is_deterministic():
    """Two runs with rebalance on must yield identical cluster membership."""
    def sig():
        cs = clustering.cluster_block_commodity(
            _rebalance_fixture(), "B", "Dairy", params={"rebalance": True})
        return sorted((tuple(sorted(v["vill_name"] for v in c.villages)),
                       c.total_members, c.provisional) for c in cs)
    assert sig() == sig()


def test_min_members_per_village_excludes_below_threshold():
    """LEAF-42: villages with <=5 interested members must not enter the
    candidate pool, so they cannot appear in any cluster (fundable or
    provisional). At the default of 6, members=5 is excluded and members=6
    is kept."""
    import pandas as pd
    rows = [
        # Two anchor villages with healthy member counts.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "Anchor1", "lat": 26.500, "long": 92.000, "Dairy": 20},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "Anchor2", "lat": 26.501, "long": 92.001, "Dairy": 15},
        # Boundary cases: 5 must be excluded, 6 must be kept.
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "Tiny5", "lat": 26.502, "long": 92.002, "Dairy": 5},
        {"district_name": "D", "block_name": "B", "gp_name": "G",
         "vill_name": "Edge6", "lat": 26.503, "long": 92.003, "Dairy": 6},
    ]
    df = pd.DataFrame(rows)
    clusters = clustering.cluster_block_commodity(df, "B", "Dairy")
    seen = {v["vill_name"] for c in clusters for v in c.villages}
    assert "Tiny5" not in seen, "members=5 must be excluded by the LEAF-42 default"
    assert "Edge6" in seen, "members=6 must remain a candidate"


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
