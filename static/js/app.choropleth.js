// =============================================================================
// Variable Choropleth Toggle
// =============================================================================

/**
 * Get min/max of a variable across all currently visible features.
 */
function getVariableRange(field) {
    let min = Infinity, max = -Infinity;
    if (!state.geojsonLayer) return { min: 0, max: 1 };

    state.geojsonLayer.eachLayer(layer => {
        const props = layer.feature.properties;
        // Skip hidden features
        if (state.currentDistrict) {
            const d = props.Dist_Name || props.district || '';
            if (String(d) !== String(state.currentDistrict)) return;
        }
        if (state.currentLevel === 'gp' && state.currentBlock) {
            const b = props.Block_Name || '';
            if (String(b) !== String(state.currentBlock)) return;
        }
        const val = parseFloat(props[field]);
        if (!isNaN(val)) {
            if (val < min) min = val;
            if (val > max) max = val;
        }
    });

    if (min === Infinity) { min = 0; max = 1; }
    if (min === max) { max = min + 1; }
    return { min, max };
}

/**
 * Get choropleth fill color for a feature based on state.activeVariable.
 */
function getChoroplethColor(feature) {
    const field = state.activeVariable;
    if (!field) return feature.properties.feasibility_color || FEASIBILITY_COLORS.no_data;
    const val = parseFloat(feature.properties[field]);
    if (isNaN(val)) return CHOROPLETH_NO_DATA;

    const range = getVariableRange(field);
    const binSize = (range.max - range.min) / CHOROPLETH_COLORS.length;
    const idx = Math.min(Math.floor((val - range.min) / binSize), CHOROPLETH_COLORS.length - 1);
    return CHOROPLETH_COLORS[idx].color;
}

/**
 * No-op stub - toggle icons are now inline in the filters table.
 */
function renderVariableToggles() {}

/**
 * Handle clicking a variable toggle (radio-style: one active at a time).
 */
function handleVariableToggle(field) {
    if (state.activeVariable === field) {
        state.activeVariable = null;
    } else {
        state.activeVariable = field;
    }

    // Update toggle icons and row highlights in the filters table
    document.querySelectorAll('.var-map-toggle').forEach(btn => {
        const isActive = btn.dataset.field === state.activeVariable;
        btn.classList.toggle('active', isActive);
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = isActive ? 'bi bi-map-fill' : 'bi bi-map';
        }
        // Highlight the parent row
        const row = btn.closest('tr');
        if (row) row.classList.toggle('var-row-active', isActive);
    });

    if (state.activeVariable) {
        applyChoroplethStyle();
        filterMapByLocation();
    } else {
        restoreDefaultLegend();
    }
}

/**
 * Apply choropleth coloring and update the map legend for the active variable.
 */
function applyChoroplethStyle() {
    const field = state.activeVariable;
    if (!field) return;

    const range = getVariableRange(field);
    const filterObj = state.currentFilters.find(f => f.column === field);
    const label = filterObj ? filterObj.label : field;

    updateChoroplethLegend(label, range.min, range.max);
}

/**
 * Update the map header legend to show a choropleth gradient for a variable.
 */
function updateChoroplethLegend(label, min, max) {
    const mapLegend = document.getElementById('map-legend');
    const mapTitle = document.querySelector('.map-header h3');

    if (mapTitle) {
        mapTitle.innerHTML = `<i class="bi bi-map"></i> ${label}`;
    }

    const binSize = (max - min) / CHOROPLETH_COLORS.length;
    const items = CHOROPLETH_COLORS.map((c, i) => {
        const lo = (min + binSize * i).toFixed(1);
        const hi = (min + binSize * (i + 1)).toFixed(1);
        return `
            <div class="legend-item">
                <span class="legend-color" style="background: ${c.color};"></span>
                <span>${lo}-${hi}</span>
            </div>
        `;
    }).join('');

    const noData = `
        <div class="legend-item">
            <span class="legend-color" style="background: ${CHOROPLETH_NO_DATA};"></span>
            <span>No Data</span>
        </div>
    `;

    mapLegend.innerHTML = items + noData;
}

/**
 * Restore the default feasibility legend and map colors.
 */
function restoreDefaultLegend() {
    const mapTitle = document.querySelector('.map-header h3');
    if (mapTitle) {
        mapTitle.innerHTML = '<i class="bi bi-map"></i> Feasibility Map';
    }

    if (state.currentFilters && state.currentFilters.length > 0) {
        // Recalculate will rebuild legend via updateChart and re-color map
        calculateFeasibility();
    } else {
        const mapLegend = document.getElementById('map-legend');
        mapLegend.innerHTML = '';
        filterMapByLocation();
    }
}

// #11: State-view summary text. Kept as a single constant + render helper so
// the wording can be swapped in one place once finalised.
// TODO(LEAF): final summary wording pending from Faiz.
const STATE_VIEW_SUMMARY_TEXT = 'Select an intervention to see filters';  // placeholder

function renderStateViewSummary() {
    return `<p class="no-filters">${STATE_VIEW_SUMMARY_TEXT}</p>`;
}

function updateActiveFilters(filters, variableStats) {
    const container = document.getElementById('active-filters');

    if (!filters || filters.length === 0) {
        container.innerHTML = renderStateViewSummary();
        return;
    }

    // variableStats: per-variable { min, max, mean } scoped to current district (from backend)
    const varStats = variableStats || {};

    // Get fallback values from intervention config
    const configVars = state.interventionConfig?.variables || [];

    // #10: brand palette cycled per group (teal, green, orange, blue, yellow, sky, purple).
    const GROUP_COLORS = ['#0297A6', '#22AD7A', '#E86933', '#5088C6', '#DD9103', '#46BBD4', '#a259ff'];

    // #10: order variables by group, then build a coloured header row per group
    // with the group rows getting a matching 3px left border.
    const groupOrder = [];
    const byGroup = {};
    filters.forEach(f => {
        const g = f.group || 'Other';
        if (!byGroup[g]) { byGroup[g] = []; groupOrder.push(g); }
        byGroup[g].push(f);
    });

    const renderRow = (f, groupColor) => {
        const configVar = configVars.find(v => v.field === f.column);
        const vs = varStats[f.column];

        // Show the configured filter range (range_min / range_max) and data average
        const filterMin = f.min_val ?? configVar?.range_min ?? '-';
        const filterMax = f.max_val ?? configVar?.range_max ?? '-';
        const avg = vs?.mean ?? configVar?.data_mean ?? f.data_mean ?? '-';
        const minDisplay = typeof filterMin === 'number' ? filterMin.toFixed(1) : filterMin;
        const maxDisplay = typeof filterMax === 'number' ? filterMax.toFixed(1) : filterMax;
        const avgDisplay = typeof avg === 'number' ? avg.toFixed(1) : avg;

        const tip = escAttr(buildInfotip({
            field: f.column,
            label: f.label,
            description: configVar?.description || f.description || '',
            group: f.group,
            data_min: vs?.min ?? configVar?.data_min,
            data_max: vs?.max ?? configVar?.data_max,
            data_mean: vs?.mean ?? configVar?.data_mean,
            range_min: f.min_val,
            range_max: f.max_val,
        }));

        const isActive = state.activeVariable === f.column;
        const toggleCls = isActive ? 'var-map-toggle active' : 'var-map-toggle';
        const toggleIcon = isActive ? 'bi-map-fill' : 'bi-map';
        const rowCls = isActive ? 'var-row-active' : '';

        return `
            <tr class="${rowCls} var-group-row" style="border-left: 3px solid ${groupColor};">
                <td class="var-toggle-cell">
                    <button class="${toggleCls}" data-field="${escAttr(f.column)}" title="Show on map">
                        <i class="bi ${toggleIcon}"></i>
                    </button>
                </td>
                <td data-infotip="${tip}" data-infotip-pos="right">${f.label}</td>
                <td class="text-right">${minDisplay}</td>
                <td class="text-right">${avgDisplay}</td>
                <td class="text-right">${maxDisplay}</td>
            </tr>
        `;
    };

    const rows = groupOrder.map((g, gi) => {
        const groupColor = GROUP_COLORS[gi % GROUP_COLORS.length];
        const headerRow = `
            <tr class="var-group-header" style="background: ${groupColor};">
                <td colspan="5">${g}</td>
            </tr>
        `;
        return headerRow + byGroup[g].map(f => renderRow(f, groupColor)).join('');
    }).join('');

    container.innerHTML = `
        <table class="filters-table">
            <thead>
                <tr class="filters-title-row">
                    <th colspan="5"><i class="bi bi-funnel"></i> Active Filters</th>
                </tr>
                <tr>
                    <th><i class="bi bi-map"></i></th>
                    <th><i class="bi bi-tag"></i> Variable</th>
                    <th class="text-right"><i class="bi bi-arrow-down"></i> Min</th>
                    <th class="text-right"><i class="bi bi-bar-chart"></i> Avg</th>
                    <th class="text-right"><i class="bi bi-arrow-up"></i> Max</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Attach toggle listeners
    container.querySelectorAll('.var-map-toggle').forEach(btn => {
        btn.addEventListener('click', () => handleVariableToggle(btn.dataset.field));
    });
}

