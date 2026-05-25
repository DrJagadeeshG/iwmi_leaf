"""
Village Clustering Engine
Per-commodity spatial cluster generator for LEAF DSS.

Forms contiguous clusters of villages within a block, honouring:
  - per-village minimum interest in the commodity
  - cluster total member range (min/max)
  - cluster village count range (min/max)
  - maximum pairwise radius across the cluster
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
    "min_villages_per_cluster": 2,
    "max_villages_per_cluster": 4,
    "max_radius_km": 5.0,
    # When on, villages that never clear the min_cluster_members floor are
    # surfaced as PROVISIONAL clusters (relaxed floor) instead of being dropped
    # off the map. On by default since 2026-05-25 (UI flags them with a badge
    # and excludes them from fundable counts).
    "emit_provisional": True,
    "provisional_min_members": 1,
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
        while (
            len(idxs) < p["max_villages_per_cluster"]
            and total < p["max_cluster_members"]
        ):
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
        if (
            total < p["min_cluster_members"]
            or len(idxs) < p["min_villages_per_cluster"]
        ):
            for k in idxs:
                assigned[k] = False
            continue
        clusters.append(_emit_cluster(idxs))

    # Post-pass (Faiz 2026-05-09 #19, fixed 2026-05-25 #S2): orphan villages the
    # main loop left unassigned get merged into the nearest existing cluster -
    # but ONLY if the merge keeps the cluster fully valid. The earlier version
    # checked just a loose member soft-cap and so produced clusters that broke
    # the 4-village and 5km-span rules (e.g. CHARANPARA/DULIAPARA stapled onto
    # BARTANGLA -> 6 villages, 5.139 km). Now every cap is re-checked, so an
    # orphan is absorbed only when the result still satisfies max_villages,
    # max_radius span and max_cluster_members. Orphans that fit nowhere valid are
    # left for the provisional pass to surface (Pass D) rather than corrupting a
    # good cluster. Centroid distance is just a prefilter / tie-break.
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
            if len(c_idxs) + 1 > p["max_villages_per_cluster"]:
                continue
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
