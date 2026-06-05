// =============================================================================
// GP (Gram Panchayat) Details
// =============================================================================

function renderGPDetail(feature) {
    const props = feature.properties;

    // Reuse block detail view elements (same layout as block view)
    const badgesContainer = document.getElementById('feasibility-badges');
    const feasibility = props.feasibility !== null && props.feasibility !== undefined
        ? props.feasibility.toFixed(1)
        : 'N/A';
    const label = props.feasibility_label || 'No Data';
    const color = props.feasibility_color || FEASIBILITY_COLORS.no_data;
    const badgeClass = label.toLowerCase().replace(' ', '-');

    badgesContainer.innerHTML = `
        <span class="feasibility-badge ${badgeClass}" style="background: ${color}">
            <i class="bi bi-check-circle"></i> ${label} (${feasibility}%)
        </span>
    `;

    // Update location path: District / Block / GP
    const gpName = props.GP_NAME || 'Unknown GP';
    const blockName = props.Block_Name || '';
    const districtName = props.Dist_Name || 'Tinsukia';

    const locationPath = blockName
        ? `${districtName} / ${blockName} / <strong>${gpName}</strong>`
        : `${districtName} / <strong>${gpName}</strong>`;
    document.getElementById('location-card-title').innerHTML = locationPath;

    // Update recommendations
    const vilCount = props.VIL_COUNT || props['NUMBER OF VILLAGE'] || '';
    const vilInfo = vilCount ? ` | Villages: ${vilCount}` : '';
    document.getElementById('block-recommendations').innerHTML = `
        <i class="bi bi-lightbulb-fill"></i> <strong>${gpName}, ${districtName}</strong>${vilInfo}
        ${feasibility !== 'N/A' ? ` | Feasibility: ${feasibility}%` : ''}
    `;

    // Render GP metrics into block detail cards
    renderGPMetricsInBlockView(props);
}

async function renderGPMetricsInBlockView(props) {
    // Ensure GP variable metadata is loaded
    if (!state.gpVariables || state.gpVariables.length === 0) {
        try {
            const resp = await fetch('/api/gp/variables');
            const vars = await resp.json();
            if (Array.isArray(vars)) state.gpVariables = vars;
        } catch (e) { console.error('Failed to load GP variables:', e); }
    }
    // Map GP data categories to the block detail card container IDs
    const groupContainers = {
        'Land & Agri': 'land-agri-metrics',
        'Water': 'water-metrics',
        'Infrastructure': 'infrastructure-metrics',
        'Livestock': 'livestock-metrics',
        'People': 'people-metrics',
        'MMUA Scheme': 'mmua-metrics'
    };

    const groupCounts = {
        'Land & Agri': 'count-land-agri',
        'Water': 'count-water',
        'Infrastructure': 'count-infrastructure',
        'Livestock': 'count-livestock',
        'People': 'count-people',
        'MMUA Scheme': 'count-mmua'
    };

    // Clear all containers first
    Object.keys(groupContainers).forEach(group => {
        const container = document.getElementById(groupContainers[group]);
        const countEl = document.getElementById(groupCounts[group]);
        if (container) {
            container.innerHTML = '';
            container.closest('.detail-card').style.display = 'none';
        }
        if (countEl) countEl.innerHTML = '';
    });

    // Build a lookup from GP variables metadata (field code -> {label, group})
    const varLookup = {};
    if (state.gpVariables) {
        state.gpVariables.forEach(v => {
            varLookup[v.field] = { label: v.label, group: v.group };
        });
    }

    // Map DSS groups to the 5 display groups (matching block view cards)
    const groupMapping = {
        'Land & Agri': 'Land & Agri',
        'Water': 'Water',
        'Infrastructure': 'Infrastructure',
        'Livestock': 'Livestock',
        'People': 'People',
        'MMUA Scheme': 'MMUA Scheme',
        'Soil': 'Land & Agri',
        'Climate': 'Water',
    };

    // Categorize GP properties using DSS metadata groups
    const grouped = {
        'Land & Agri': [],
        'Water': [],
        'Infrastructure': [],
        'Livestock': [],
        'People': [],
        'MMUA Scheme': []
    };

    const skipKeys = new Set(['geometry', 'GP_CODE', 'GP_ID', 'GP_NAME', 'VIL_COUNT', 'Dist_Name',
        'Block_Name', 'feasibility', 'feasibility_class', 'feasibility_label', 'feasibility_color',
        'NUMBER OF VILLAGE', 'TEHSIL_NAM', 'BLOCK_NAME', 'STATE_NAME', 'DIST_NAME',
        'SHAPE_Leng', 'SHAPE_Area', 'BW', 'BX']);

    Object.entries(props).forEach(([key, value]) => {
        if (value === null || value === undefined) return;
        if (skipKeys.has(key)) return;

        const meta = varLookup[key];
        if (!meta) return; // skip unknown fields

        const displayGroup = groupMapping[meta.group] || 'Infrastructure';
        if (!grouped[displayGroup]) return;

        const displayValue = typeof value === 'number' ? value.toFixed(2) : value;
        grouped[displayGroup].push({ field: key, label: meta.label, value: displayValue });
    });

    // Render each group into block detail cards
    Object.entries(grouped).forEach(([group, metrics]) => {
        const containerId = groupContainers[group];
        if (!containerId) return;

        const container = document.getElementById(containerId);
        if (!container) return;

        if (metrics.length === 0) return;

        // Show the card
        container.closest('.detail-card').style.display = 'block';

        const metricsHtml = metrics.map(m => {
            const tip = escAttr(buildInfotip({ field: m.field, label: m.label }));
            return `
                <div class="metric-row">
                    <span class="metric-label" data-infotip="${tip}">${m.label}</span>
                    <span class="metric-value">${m.value}</span>
                </div>
            `;
        }).join('');

        container.innerHTML = wrapInScrollStructure(metricsHtml);
        setTimeout(() => initScrollSync(container), 0);
    });
}

function initGPMiniMap(feature) {
    // Destroy existing mini map
    if (state.gpMiniMap) {
        state.gpMiniMap.remove();
    }

    // Create new mini map
    state.gpMiniMap = L.map('gp-mini-map', {
        zoomControl: false,
        attributionControl: false,
    });

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
    }).addTo(state.gpMiniMap);

    // Add GP boundary with feasibility color if available
    const gpLayer = L.geoJSON(feature, {
        style: {
            fillColor: gpFillColor(feature),
            color: '#1b5e20',
            weight: 2,
            fillOpacity: 0.5,
        }
    }).addTo(state.gpMiniMap);

    // Fit bounds
    state.gpMiniMap.fitBounds(gpLayer.getBounds(), { padding: [20, 20] });
}
