// =============================================================================
// District Detail (LEAF-52): aggregated card view for a whole district,
// reusing the block detail layout (50/50 map + cards).
// =============================================================================

// Classify a feasibility percentage into a label + colour, mirroring the
// backend thresholds in config.py.
function classifyFeasibilityFE(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return { cls: 'no_data', label: 'No Data', color: FEASIBILITY_COLORS.no_data };
    }
    let cls, label;
    if (value >= 100) { cls = 'very_high'; label = '100%'; }
    else if (value >= 75) { cls = 'high'; label = '75-100%'; }
    else if (value >= 50) { cls = 'moderate_high'; label = '50-75%'; }
    else if (value >= 25) { cls = 'moderate'; label = '25-50%'; }
    else if (value >= 1) { cls = 'low'; label = '1-25%'; }
    else { cls = 'very_low'; label = '0%'; }
    return { cls, label, color: FEASIBILITY_COLORS[cls] || FEASIBILITY_COLORS.no_data };
}

// Average all numeric block properties across a district into a single
// synthetic "district" props object the card renderer can consume.
function aggregateBlockProps(feats, districtName) {
    const sums = {}, counts = {};
    feats.forEach(f => {
        const p = f.properties || {};
        Object.keys(p).forEach(k => {
            const v = Number(p[k]);
            if (Number.isFinite(v)) { sums[k] = (sums[k] || 0) + v; counts[k] = (counts[k] || 0) + 1; }
        });
    });
    const props = { Dist_Name: districtName, Block_name: 'All blocks', is_district_aggregate: true };
    Object.keys(sums).forEach(k => { props[k] = sums[k] / counts[k]; });
    return props;
}

function showDistrictDetailView(districtName) {
    // Gather this district's block features from the current map layer.
    const feats = [];
    if (state.geojsonLayer) {
        state.geojsonLayer.eachLayer(l => {
            const p = (l.feature && l.feature.properties) || {};
            if ((p.Dist_Name || '') === districtName) feats.push(l.feature);
        });
    }
    if (!feats.length) { showOverviewView(); return; }

    document.getElementById('overviewView').style.display = 'none';
    document.getElementById('blockDetailView').style.display = 'block';
    document.getElementById('gpDetailView').style.display = 'none';
    state.currentBlock = null;

    const aggProps = aggregateBlockProps(feats, districtName);
    state.districtAggProps = aggProps;
    state.currentViewLevel = 'district';
    renderDistrictDetail(aggProps, feats);
    // #9: CSV export is available in detail views (a district is selected).
    updateExportButtonVisibility();
    updateURL();
}

function renderDistrictDetail(props, feats) {
    const feas = Number.isFinite(props.feasibility) ? props.feasibility : null;
    const { label, color } = classifyFeasibilityFE(feas);
    props.feasibility_label = label;
    props.feasibility_color = color;

    document.getElementById('feasibility-badges').innerHTML = `
        <span class="feasibility-badge" style="background: ${color}">
            <i class="bi bi-check-circle"></i> ${label} (${feas !== null ? feas.toFixed(1) : 'N/A'}%)
        </span>`;

    document.getElementById('location-card-title').innerHTML =
        `<strong>${props.Dist_Name}</strong> / All blocks (${feats.length})`;
    // #2: district summary as a clean full-width line in the (white) header,
    // not crammed into the dark map-card header.
    const ds = document.getElementById('district-summary');
    if (ds) {
        ds.innerHTML = `<strong>${props.Dist_Name}</strong> — Feasibility ` +
            `${feas !== null ? feas.toFixed(1) : 'N/A'}% across ${feats.length} blocks`;
        ds.style.display = '';
    }

    // No GP dropdown at district level.
    document.getElementById('block-gp-select').style.display = 'none';

    const totalOutside = renderActiveMetricsByGroup(props);
    const totalCountEl = document.getElementById('total-outside-count');
    totalCountEl.innerHTML = totalOutside > 0 ? `${totalOutside} outside range (avg)` : '';

    // District-level AI Insights (LEAF #1) + feasibility summary sentence (#21).
    // Reuse /api/ai-recommendation with aggregated district props: present the
    // district name as the "block" so the request + modal header are district-level.
    const aiProps = Object.assign({}, props, { Block_name: props.Dist_Name });
    renderRecommendations(aiProps, null, { outsideCount: totalOutside, scope: 'this district' });

    initDistrictMiniMap(feats);
}

// Draw all of a district's blocks on the left-hand map.
function initDistrictMiniMap(feats) {
    if (state.blockMiniMap) { state.blockMiniMap.remove(); state.blockMiniMap = null; }
    state.blockMiniMap = L.map('block-mini-map', { zoomControl: false, attributionControl: false });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 18 })
        .addTo(state.blockMiniMap);

    const layer = L.geoJSON({ type: 'FeatureCollection', features: feats }, {
        style: f => ({
            fillColor: (f.properties && f.properties.feasibility_color) || '#0297A6',
            color: '#28537D',
            weight: 1.2,
            fillOpacity: 0.4,
        }),
        onEachFeature: (feat, lyr) => {
            const p = feat.properties || {};
            const name = p.Block_name || 'Block';
            const feas = (p.feasibility !== null && p.feasibility !== undefined) ? p.feasibility.toFixed(1) + '%' : null;
            const tip = feas ? `<strong>${name}</strong><br>Feasibility: ${feas}` : `<strong>${name}</strong>`;
            lyr.bindTooltip(tip, { className: 'custom-tooltip' });
        },
    }).addTo(state.blockMiniMap);

    const refit = () => { try { state.blockMiniMap.fitBounds(layer.getBounds(), { padding: [20, 20] }); } catch (e) {} };
    refit();
    setTimeout(() => { if (state.blockMiniMap) { state.blockMiniMap.invalidateSize(); refit(); } }, 150);

    // Feasibility legend (LEAF #4)
    addMiniMapLegend(state.blockMiniMap);
}

