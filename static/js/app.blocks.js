// =============================================================================
// Block Details
// =============================================================================

function showBlockDetails(props, feature) {
    if (feature) {
        showBlockDetailView(feature);
    }
}

function renderBlockDetail(feature) {
    const props = feature.properties;

    // Update feasibility badge
    const badgesContainer = document.getElementById('feasibility-badges');
    const feasibility = props.feasibility !== null ? props.feasibility.toFixed(1) : 'N/A';
    const label = props.feasibility_label || 'No Data';
    const color = props.feasibility_color || FEASIBILITY_COLORS.no_data;
    const badgeClass = label.toLowerCase().replace(' ', '-');

    badgesContainer.innerHTML = `
        <span class="feasibility-badge ${badgeClass}" style="background: ${color}">
            <i class="bi bi-check-circle"></i> ${label} (${feasibility}%)
        </span>
    `;

    // Update location card title with District / Block path
    const blockName = props.Block_name || 'Unknown';
    const districtName = props.Dist_Name || 'Unknown';
    document.getElementById('location-card-title').innerHTML = `${districtName} / <strong>${blockName}</strong>`;

    // Show/populate GP dropdown for GP-enabled districts
    const blockGPSelect = document.getElementById('block-gp-select');
    const hasGPData = state.gpAvailable && state.gpDistricts.includes(districtName);
    if (hasGPData && blockName) {
        blockGPSelect.style.display = '';
        populateBlockGPDropdown(blockName);
    } else {
        blockGPSelect.style.display = 'none';
    }

    // Render metrics by category (dynamic based on active filters)
    const totalOutside = renderActiveMetricsByGroup(props);

    // Update total outside count
    const totalCountEl = document.getElementById('total-outside-count');
    if (totalOutside > 0) {
        totalCountEl.innerHTML = `${totalOutside} outside range`;
    } else {
        totalCountEl.innerHTML = '';
    }

    // Reset to block view (hide any cluster cards) and refresh the cluster
    // dropdown for this block + active commodity (LEAF-53).
    setClusterMode(false);
    updateBlockClusterDropdown(blockName);

    // Render recommendations (pass feature for map + feasibility summary sentence #21)
    renderRecommendations(props, feature, { outsideCount: totalOutside, scope: 'this block' });
}

// =============================================================================
// Cluster level inside the dashboard (LEAF-53)
// =============================================================================

// Toggle between the block's category cards and the cluster cards.
function setClusterMode(on) {
    document.querySelectorAll('.detail-right > .detail-card').forEach(c => {
        c.style.display = on ? 'none' : '';
    });
    const cc = document.getElementById('cluster-cards');
    if (cc) cc.style.display = on ? '' : 'none';
}

// Populate the cluster dropdown for a block, scoped to the active livestock
// sub-category (the clustering commodity). Hidden when no commodity is active
// or the block+commodity has no clusters.
async function updateBlockClusterDropdown(blockName) {
    const sel = document.getElementById('block-cluster-select');
    const commodity = state.currentSubcategory;  // e.g. Goatery / Piggery / Dairy
    state.blockClusters = [];
    if (!commodity || !blockName) {
        sel.style.display = 'none';
        sel.innerHTML = '<option value="">All clusters</option>';
        return;
    }
    try {
        const r = await fetch(`/api/clusters?block=${encodeURIComponent(blockName)}&commodity=${encodeURIComponent(commodity)}`);
        const clusters = await r.json();
        state.blockClusters = Array.isArray(clusters) ? clusters : [];
    } catch (e) {
        state.blockClusters = [];
    }
    if (!state.blockClusters.length) {
        sel.style.display = 'none';
        sel.innerHTML = '<option value="">All clusters</option>';
        return;
    }
    sel.innerHTML = '';
    const all = document.createElement('option');
    all.value = ''; all.textContent = `All clusters (${state.blockClusters.length})`;
    sel.appendChild(all);
    state.blockClusters.forEach(c => {
        const o = document.createElement('option');
        o.value = c.cluster_id;
        o.textContent = `Cluster ${c.cluster_label != null ? c.cluster_label : (c.cluster_num != null ? c.cluster_num : c.cluster_id)} · ${c.total_members} members`;
        sel.appendChild(o);
    });
    sel.style.display = '';
}

function handleBlockClusterSelect() {
    const id = document.getElementById('block-cluster-select').value;
    if (!id) {
        // Back to the block's category cards + block boundary map.
        setClusterMode(false);
        state.currentCluster = null;
        state.currentViewLevel = 'block';
        if (state.blockFeature) {
            renderActiveMetricsByGroup(state.blockFeature.properties);
            initBlockMiniMap(state.blockFeature);
        }
        return;
    }
    const c = (state.blockClusters || []).find(x => String(x.cluster_id) === String(id));
    if (c) showClusterDetailView(c);
}

function showClusterDetailView(c) {
    state.currentCluster = c;
    state.currentViewLevel = 'cluster';
    const villages = (c.villages || []);
    const status = c.finalized
        ? '<span style="color:#22AD7A;font-weight:600"><i class="bi bi-check-circle-fill"></i> Finalised</span>'
        : '<span style="color:#888">Proposed</span>';
    const memberRows = villages.map(v =>
        `<div class="metric-row"><span class="metric-label">${escapeText(v.vill_name || 'Village')}</span>` +
        `<span class="metric-value">${Number(v.members || 0).toLocaleString()}</span></div>`).join('');
    const coord = (c.pashu_sakhi || c.block_coordinator)
        ? `<div class="detail-card">
              <div class="detail-card-header"><span><i class="bi bi-person-badge"></i> Assignment</span></div>
              <div class="detail-card-body"><div class="metrics-scroll-wrapper">
                ${c.pashu_sakhi ? `<div class="metric-row"><span class="metric-label">Pashu Sakhi</span><span class="metric-value">${escapeText(c.pashu_sakhi)}</span></div>` : ''}
                ${c.block_coordinator ? `<div class="metric-row"><span class="metric-label">Block coordinator</span><span class="metric-value">${escapeText(c.block_coordinator)}</span></div>` : ''}
              </div></div>
           </div>`
        : '';

    document.getElementById('cluster-cards').innerHTML = `
        <div class="detail-card">
            <div class="detail-card-header"><span><i class="bi bi-diagram-3"></i> Cluster ${c.cluster_label != null ? c.cluster_label : (c.cluster_num != null ? c.cluster_num : c.cluster_id)}</span></div>
            <div class="detail-card-body"><div class="metrics-scroll-wrapper">
                <div class="metric-row"><span class="metric-label">Commodity</span><span class="metric-value">${escapeText(c.commodity || '')}</span></div>
                <div class="metric-row"><span class="metric-label">Total members</span><span class="metric-value">${Number(c.total_members || 0).toLocaleString()}</span></div>
                <div class="metric-row"><span class="metric-label">Villages</span><span class="metric-value">${villages.length}</span></div>
                <div class="metric-row"><span class="metric-label">Max span</span><span class="metric-value">${c.max_span_km != null ? c.max_span_km + ' km' : '—'}</span></div>
                <div class="metric-row"><span class="metric-label">Status</span><span class="metric-value">${status}</span></div>
            </div></div>
        </div>
        <div class="detail-card">
            <div class="detail-card-header"><span><i class="bi bi-pin-map"></i> Member villages (${villages.length})</span></div>
            <div class="detail-card-body"><div class="metrics-scroll-wrapper">${memberRows || '<p class="no-filters">No villages.</p>'}</div></div>
        </div>
        ${coord}`;

    document.getElementById('location-card-title').innerHTML =
        `${escapeText(c.block_name || state.currentBlock || '')} / <strong>Cluster ${c.cluster_label != null ? c.cluster_label : (c.cluster_num != null ? c.cluster_num : c.cluster_id)}</strong>`;

    setClusterMode(true);
    initClusterMiniMap(c);
}

// Plot a cluster's member villages on the left-hand map.
function initClusterMiniMap(c) {
    if (state.blockMiniMap) { state.blockMiniMap.remove(); state.blockMiniMap = null; }
    state.blockMiniMap = L.map('block-mini-map', { zoomControl: false, attributionControl: false });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 18 })
        .addTo(state.blockMiniMap);

    const pts = [];
    (c.villages || []).forEach(v => {
        const lat = Number(v.lat), lng = Number(v.long);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        pts.push([lat, lng]);
        L.circleMarker([lat, lng], {
            radius: Math.max(5, Math.min(14, 4 + Math.sqrt(Number(v.members) || 0) * 1.2)),
            color: '#243240', weight: 1, fillColor: '#0297A6', fillOpacity: 0.85,
        }).addTo(state.blockMiniMap).bindTooltip(
            `${escapeText(v.vill_name || 'Village')} · ${Number(v.members || 0)} members`,
            { direction: 'top' });
    });

    const fit = () => {
        try {
            if (pts.length > 1) state.blockMiniMap.fitBounds(L.latLngBounds(pts), { padding: [30, 30] });
            else if (pts.length === 1) state.blockMiniMap.setView(pts[0], 13);
        } catch (e) {}
    };
    fit();
    setTimeout(() => { if (state.blockMiniMap) { state.blockMiniMap.invalidateSize(); fit(); } }, 150);
}

// Minimal HTML-escape for text inserted via innerHTML.
