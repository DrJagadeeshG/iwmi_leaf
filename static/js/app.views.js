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

    // Block→cluster drill-down: leaving the block view tears down the cluster
    // overlay and hides the filter-bar Cluster dropdown (cluster_view_spec).
    if (typeof clusterViewReset === 'function') clusterViewReset();

    // #9: CSV export is a detail-view action; hide it in the state overview
    // (no district selected). It is re-shown in detail views.
    updateExportButtonVisibility();

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

// The CSV export button has been removed from the UI (2026-06-05): the
// Summary report is the user-facing export now. Kept as a no-op so the
// detail-view render paths that call it stay unchanged.
function updateExportButtonVisibility() {}

