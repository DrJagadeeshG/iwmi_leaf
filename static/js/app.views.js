// =============================================================================
// View Switching
// =============================================================================

function showOverviewView() {
    document.getElementById('overviewView').style.display = 'grid';
    document.getElementById('blockDetailView').style.display = 'none';
    document.getElementById('gpDetailView').style.display = 'none';
    state.currentBlock = null;
    state.currentGP = null;
    state.currentViewLevel = 'state';

    // #9: CSV export is a detail-view action; hide it in the state overview
    // (no district selected). It is re-shown in detail views.
    updateExportButtonVisibility();

    // #2: District-level summary line above the all-blocks overview.
    updateDistrictSummaryLine();

    // Destroy block mini map if exists
    if (state.blockMiniMap) {
        state.blockMiniMap.remove();
        state.blockMiniMap = null;
    }

    // Destroy GP mini map if exists
    if (state.gpMiniMap) {
        state.gpMiniMap.remove();
        state.gpMiniMap = null;
    }

    // Leaflet needs invalidateSize after container was hidden (display:none)
    if (state.map) {
        setTimeout(() => state.map.invalidateSize(), 50);
    }

    // Re-apply district filtering on the map & recalculate if filters exist
    if (state.currentFilters && state.currentFilters.length > 0) {
        calculateFeasibility();
    } else {
        filterMapByLocation();
    }

    // Keep URL in sync
    updateURL();
}

function showBlockDetailView(feature) {
    // Use GP view if in GP mode
    if (state.currentLevel === 'gp') {
        showGPDetailView(feature);
        return;
    }

    document.getElementById('overviewView').style.display = 'none';
    document.getElementById('blockDetailView').style.display = 'block';
    document.getElementById('gpDetailView').style.display = 'none';

    const props = feature.properties;
    state.currentBlock = props.Block_name || '';
    state.blockFeature = feature;
    state.currentViewLevel = 'block';

    renderBlockDetail(feature);
    initBlockMiniMap(feature);
    updateExportButtonVisibility();
}

function showGPDetailView(feature) {
    // Reuse the block detail view layout (same structure as block view)
    document.getElementById('overviewView').style.display = 'none';
    document.getElementById('blockDetailView').style.display = 'block';
    document.getElementById('gpDetailView').style.display = 'none';

    const props = feature.properties;
    state.currentGP = props.GP_NAME || '';
    state.blockFeature = feature;

    renderGPDetail(feature);
    initBlockMiniMap(feature);
    updateExportButtonVisibility();
}

// #9: CSV export only makes sense in a detail view (a district is selected).
// Show it whenever state.currentDistrict is set, hide it in the state overview.
function updateExportButtonVisibility() {
    const btn = document.getElementById('export-btn');
    if (!btn) return;
    const group = btn.closest('.filter-group') || btn;
    // Show CSV only in a detail view; hide on the state overview. Keyed off the
    // view level rather than state.currentDistrict, which can persist after
    // returning to the overview (so the button used to linger there).
    const inDetail = state.currentViewLevel && state.currentViewLevel !== 'state';
    group.style.display = inDetail ? '' : 'none';
}

// #2: Populate the district summary line in the overview. Aggregates the
// selected district's block feasibility (reuses aggregateBlockProps logic) and
// renders "‹District› — Feasibility ‹avg%› (‹N› blocks)". Hidden for "All Districts".
function updateDistrictSummaryLine() {
    const el = document.getElementById('district-summary-line');
    if (!el) return;

    if (!state.currentDistrict) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }

    // Gather this district's block features from the current map layer.
    const feats = [];
    if (state.geojsonLayer) {
        state.geojsonLayer.eachLayer(l => {
            const p = (l.feature && l.feature.properties) || {};
            if ((p.Dist_Name || '') === state.currentDistrict) feats.push(l.feature);
        });
    }

    if (!feats.length) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }

    const aggProps = aggregateBlockProps(feats, state.currentDistrict);
    const feas = Number.isFinite(aggProps.feasibility) ? aggProps.feasibility : null;
    const feasText = feas !== null ? `${feas.toFixed(1)}%` : 'N/A';
    el.innerHTML =
        `<strong>${state.currentDistrict}</strong> — Feasibility ${feasText} (${feats.length} blocks)`;
    el.style.display = '';
}

