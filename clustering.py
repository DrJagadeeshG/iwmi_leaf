"""
Village Clustering Engine
Per-commodity spatial cluster generator for LEAF DSS.

Forms contiguous clusters of villages within a block, honouring:
  - per-village minimum interest in the commodity
  - cluster total member range (min/max)
  - maximum pairwise radius across the cluster
A cluster's village count is no longer capped (LEAF-43): if N villages
fall within max_radius_km of each other and the member band still holds,
that is a valid cluster.
Algorithm: greedy seed-and-grow. Largest unassigned village seeds a cluster;
nearest unassigned candidates are added while constraints hold. Discards
under-size clusters at the end.
"""

import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

import pandas as pd

# Bump whenever the clustering LOGIC changes (a change params/data don't
# capture). The smart-refresh fingerprint includes this, so bumping it forces
# every unlocked scope to regenerate on its next read.
ALGO_VERSION = 4

COMMODITIES = [
    "Dairy",
    "Goatery",
    "Piggery",
    "Backyard_Poultry",
    "Duckery",
    "Fishery_Activity",
]

DEFAULT_PARAMS = {
    "min_members_per_village": 1,
    "min_cluster_members": 30,
    "max_cluster_members": 150,
    # LEAF-43 (Faiz 2026-05-21): the village-count band (was 2-4) is dropped.
    # A cluster is valid by member range + 5 km span alone; "if six villages
    # fall within 5 km and satisfy member limits, that is a valid cluster."
    # min_villages_per_cluster / max_villages_per_cluster removed.
    "max_radius_km": 5.0,
    # When on, villages that never clear the min_cluster_members floor are
    # surfaced as PROVISIONAL clusters (relaxed floor) instead of being dropped
    # off the map. On by default since 2026-05-25 (UI flags them with a badge
    # and excludes them from fundable counts).
    "emit_provisional": True,
    "provisional_min_members": 1,
    # Pass E (post-pass rebalance). When on, a below-floor provisional group can
    # become fundable by borrowing village(s) from an adjacent fundable cluster,
    # but ONLY when every cap still holds and the donor stays valid. DEFAULT OFF:
    # it changes output across ~18% of provisional groups, so it must be reviewed
    # before enabling on prod (bump ALGO_VERSION when you do). See cluster
    # follow-up notes / OPEN ITEM A.
    "rebalance": False,
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Cluster:
    cluster_id: str
    commodity: str
    block_name: str
    district_name: str
    village_indices: List[int] = field(default_factory=list)
    villages: List[Dict] = field(default_factory=list)
    total_members: int = 0
    max_span_km: float = 0.0
    centroid_lat: float = 0.0
    centroid_lon: float = 0.0
    pashu_sakhi: Optional[str] = None
    block_coordinator: Optional[str] = None
    # True when the cluster falls below the fundable member floor and is only
    # surfaced for review (Pass D). Eligible clusters keep this False.
    provisional: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)


def _params(overrides: Optional[Dict]) -> Dict:
    p = dict(DEFAULT_PARAMS)
    if overrides:
        for k, v in overrides.items():
            if k in p and v is not None:
                p[k] = v
    return p


def _max_pairwise_km(coords: List[tuple]) -> float:
    n = len(coords)
    if n < 2:
        return 0.0
    m = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            if d > m:
                m = d
    return m


def cluster_block_commodity(
    df: pd.DataFrame,
    block_name: str,
    commodity: str,
    params: Optional[Dict] = None,
) -> List[Cluster]:
    """Generate clusters for one (block, commodity) pair.

    `df` must contain rows for a single block; columns: district_name, block_name,
    gp_name, vill_name, lat, long, and the commodity column.
    """
    if commodity not in COMMODITIES:
        raise ValueError(f"Unknown commodity '{commodity}'. Expected one of {COMMODITIES}.")

    p = _params(params)

    # Case-insensitive block match: callers (frontend, API) may pass the block
    # in MMUA display case (e.g. "Bhergaon") while the village master is upper
    # ("BHERGAON"). Canonicalise block_name to the master casing so stored
    # block_name and cluster_id are consistent regardless of input case.
    block_df = df[df["block_name"].astype(str).str.upper() == str(block_name).upper()].copy()
    if block_df.empty or commodity not in block_df.columns:
        return []
    block_name = str(block_df["block_name"].iloc[0])

    candidates = (
        block_df[block_df[commodity] >= p["min_members_per_village"]]
        .reset_index(drop=True)
    )
    if candidates.empty:
        return []

    district_name = str(candidates["district_name"].iloc[0])
    coords = list(zip(candidates["lat"].astype(float), candidates["long"].astype(float)))
    members = candidates[commodity].astype(int).tolist()
    seed_order = sorted(range(len(candidates)), key=lambda i: members[i], reverse=True)

    assigned = [False] * len(candidates)
    clusters: List[Cluster] = []

    def _emit_cluster(idxs: List[int], provisional: bool = False) -> Cluster:
        """Build a Cluster from a list of candidate indices. Used by the main
        loop and by the single-village / orphan-merge / provisional passes."""
        cluster_coords = [coords[k] for k in idxs]
        c_lat = sum(c[0] for c in cluster_coords) / len(cluster_coords)
        c_lon = sum(c[1] for c in cluster_coords) / len(cluster_coords)
        villages = []
        for k in idxs:
            row = candidates.iloc[k]
            villages.append({
                "vill_name": str(row["vill_name"]),
                "gp_name": str(row["gp_name"]),
                "lat": float(row["lat"]),
                "long": float(row["long"]),
                "members": int(row[commodity]),
            })
        return Cluster(
            cluster_id=f"{block_name}-{commodity}-{uuid.uuid4().hex[:8]}",
            commodity=commodity,
            block_name=block_name,
            district_name=district_name,
            village_indices=[int(candidates.index[k]) for k in idxs],
            villages=villages,
            total_members=int(sum(members[k] for k in idxs)),
            max_span_km=round(_max_pairwise_km(cluster_coords), 3),
            centroid_lat=round(c_lat, 6),
            centroid_lon=round(c_lon, 6),
            provisional=provisional,
        )

    # Pre-pass (Faiz 2026-05-09, #18): a single village can already meet or
    # exceed the funding band on its own (e.g. 274 members of dairy interest
    # against a 30-50 default band). Without this exception the greedy loop
    # rejects them because adding any neighbour blows max_cluster_members.
    # Treat them as standalone clusters before the main pass runs.
    for i in seed_order:
        if assigned[i]:
            continue
        if members[i] >= p["max_cluster_members"]:
            clusters.append(_emit_cluster([i]))
            assigned[i] = True

    def _grow(seed: int):
        """Greedy seed-and-grow from one seed. Marks chosen villages assigned
        and returns (indices, total_members). Distance is measured to the seed
        (Pass B's growth metric); size and radius guards still gate every add."""
        idxs = [seed]
        total = members[seed]
        assigned[seed] = True
        # LEAF-43: no upper village-count gate. Growth stops when no remaining
        # village fits the member ceiling AND the 5 km pairwise span.
        while total < p["max_cluster_members"]:
            seed_lat, seed_lon = coords[idxs[0]]
            best_i, best_d = None, float("inf")
            for j in range(len(candidates)):
                if assigned[j] or j in idxs:
                    continue
                d_seed = haversine_km(seed_lat, seed_lon, coords[j][0], coords[j][1])
                if d_seed > p["max_radius_km"]:
                    continue
                trial_coords = [coords[k] for k in idxs] + [coords[j]]
                if _max_pairwise_km(trial_coords) > p["max_radius_km"]:
                    continue
                if total + members[j] > p["max_cluster_members"]:
                    continue
                if d_seed < best_d:
                    best_d = d_seed
                    best_i = j
            if best_i is None:
                break
            idxs.append(best_i)
            total += members[best_i]
            assigned[best_i] = True
        return idxs, total

    for seed in seed_order:
        if assigned[seed]:
            continue
        idxs, total = _grow(seed)
        # LEAF-43: village-count floor dropped. Discard only if the cluster
        # fails the 30-member floor; a single-village cluster with 30+ members
        # is a valid cluster.
        if total < p["min_cluster_members"]:
            for k in idxs:
                assigned[k] = False
            continue
        clusters.append(_emit_cluster(idxs))

    # Post-pass (Faiz 2026-05-09 #19, fixed 2026-05-25 #S2, simplified
    # 2026-05-29 LEAF-43): orphan villages the main loop left unassigned get
    # merged into the nearest existing cluster - but ONLY if the merge keeps
    # every remaining cap intact. The pre-LEAF-43 caps were max_villages,
    # max_cluster_members, max_radius span; LEAF-43 drops the village-count
    # cap, so today the merge re-checks just max_cluster_members and the
    # 5 km pairwise span. Orphans that don't fit are left for Pass D.
    merge_radius_km = 2 * p["max_radius_km"]
    for i in range(len(candidates)):
        if assigned[i]:
            continue
        v_lat, v_lon = coords[i]
        best_c, best_d = None, float("inf")
        for c in clusters:
            d = haversine_km(v_lat, v_lon, c.centroid_lat, c.centroid_lon)
            if d > merge_radius_km:
                continue
            c_idxs = [candidates.index.get_loc(idx) for idx in c.village_indices]
            if c.total_members + members[i] > p["max_cluster_members"]:
                continue
            if _max_pairwise_km([coords[k] for k in c_idxs] + [coords[i]]) > p["max_radius_km"]:
                continue
            if d < best_d:
                best_d = d
                best_c = c
        if best_c is None:
            continue
        # Re-emit the cluster with the orphan appended; cheaper than mutating
        # the dataclass in place and keeps centroid/span derivations in one
        # spot. Original index list survives via village_indices.
        orig_idxs = [candidates.index.get_loc(idx) for idx in best_c.village_indices]
        new_idxs = orig_idxs + [i]
        merged = _emit_cluster(new_idxs)
        # Preserve the original cluster_id so downstream consumers don't see
        # the orphan absorption as a "different" cluster.
        merged.cluster_id = best_c.cluster_id
        merged.pashu_sakhi = best_c.pashu_sakhi
        merged.block_coordinator = best_c.block_coordinator
        for j, existing in enumerate(clusters):
            if existing is best_c:
                clusters[j] = merged
                break
        assigned[i] = True

    # Pass D (Faiz 2026-05-19): low-density blocks/pockets (BHERGAON's Tangla
    # corner, all of KHOWANG/Dairy) leave villages that never clear the
    # min_cluster_members floor, so they vanish from the map. When
    # emit_provisional is on, surface every still-unassigned village as a
    # PROVISIONAL cluster - same growth, radius and size caps, but the member
    # floor is relaxed to provisional_min_members and the 2-village floor is
    # dropped so isolated villages still show. Flagged so the UI can mark them
    # "below funding floor - review" rather than presenting them as fundable.
    if p["emit_provisional"]:
        for seed in seed_order:
            if assigned[seed]:
                continue
            idxs, total = _grow(seed)
            if total >= p["provisional_min_members"]:
                clusters.append(_emit_cluster(idxs, provisional=True))
            else:
                for k in idxs:
                    assigned[k] = False

    # Pass E (rebalance, OFF by default - OPEN ITEM A). Rescue below-floor
    # provisional groups by borrowing village(s) from an adjacent fundable
    # cluster. Conservative and deterministic by design:
    #   - process provisional groups largest-first;
    #   - a borrow commits only if P stays within all caps (<=4 villages,
    #     <=5km span, <=150 members) AND the donor stays valid (>=min members,
    #     >=min villages) AFTER losing the village;
    #   - if P can't reach the floor within its remaining village budget, ALL
    #     its tentative borrows are reverted (no churn);
    #   - only the ORIGINAL fundable clusters may donate, and each village moves
    #     at most once -> one rescue level, no cascade.
    if p["rebalance"]:
        def _local(c: Cluster) -> List[int]:
            return [candidates.index.get_loc(idx) for idx in c.village_indices]

        donors = [c for c in clusters if not c.provisional]
        provis = sorted((c for c in clusters if c.provisional),
                        key=lambda c: c.total_members, reverse=True)
        donor_local = {c.cluster_id: _local(c) for c in donors}
        donor_obj = {c.cluster_id: c for c in donors}
        moved = set()  # candidate-local indices already borrowed

        def _replace(old: Cluster, new: Cluster) -> None:
            for j, x in enumerate(clusters):
                if x is old:
                    clusters[j] = new
                    return

        for pc in provis:
            if pc.total_members >= p["min_cluster_members"]:
                continue
            cur_local = list(_local(pc))
            plan: List[tuple] = []  # (donor_cluster_id, candidate-local idx)
            # LEAF-43: no village-count gate on the borrower; only the
            # member ceiling and 5 km span bound the borrow. The donor still
            # has to stay at >=min_cluster_members after losing the village.
            while sum(members[k] for k in cur_local) < p["min_cluster_members"]:
                best = None  # (sort_key, donor_id, local_idx); lowest key wins
                for did, d_idx in donor_local.items():
                    planned_here = [k for (d, k) in plan if d == did]
                    remaining_base = [k for k in d_idx if k not in planned_here]
                    for k in remaining_base:
                        if k in moved:
                            continue
                        trial = cur_local + [k]
                        new_total = sum(members[j] for j in trial)
                        if new_total > p["max_cluster_members"]:
                            continue
                        span = _max_pairwise_km([coords[j] for j in trial])
                        if span > p["max_radius_km"]:
                            continue
                        remaining = [x for x in remaining_base if x != k]
                        if sum(members[j] for j in remaining) < p["min_cluster_members"]:
                            continue
                        # Conservative borrow: take the SMALLEST move that clears
                        # the floor (minimal overshoot keeps the donor as intact as
                        # possible); only if no single borrow clears it do we take
                        # the biggest member gain to make progress. Tighter span,
                        # then lowest index, break ties -> fully deterministic.
                        reaches = new_total >= p["min_cluster_members"]
                        key = (0 if reaches else 1,
                               new_total if reaches else -members[k],
                               round(span, 6), k)
                        if best is None or key < best[0]:
                            best = (key, did, k)
                if best is None:
                    break
                _, did, k = best
                cur_local.append(k)
                plan.append((did, k))

            if plan and sum(members[k] for k in cur_local) >= p["min_cluster_members"]:
                rescued = _emit_cluster(cur_local, provisional=False)
                rescued.cluster_id = pc.cluster_id
                rescued.pashu_sakhi = pc.pashu_sakhi
                rescued.block_coordinator = pc.block_coordinator
                _replace(pc, rescued)
                for did, k in plan:
                    donor_local[did] = [x for x in donor_local[did] if x != k]
                    moved.add(k)
                for did in {d for d, _ in plan}:
                    old = donor_obj[did]
                    rebuilt = _emit_cluster(donor_local[did])
                    rebuilt.cluster_id = old.cluster_id
                    rebuilt.pashu_sakhi = old.pashu_sakhi
                    rebuilt.block_coordinator = old.block_coordinator
                    _replace(old, rebuilt)
                    donor_obj[did] = rebuilt

    return clusters


def cluster_block_all(
    df: pd.DataFrame,
    block_name: str,
    params: Optional[Dict] = None,
    commodities: Optional[List[str]] = None,
) -> Dict[str, List[Cluster]]:
    """Generate clusters for all commodities in one block. Returns {commodity: [Cluster, ...]}."""
    cs = commodities or COMMODITIES
    return {c: cluster_block_commodity(df, block_name, c, params) for c in cs}
