/**
 * LEAF DSS - Frontend Application
 * Map, filters, and interactivity
 */

// =============================================================================
// Global State
// =============================================================================

const state = {
    map: null,
    geojsonLayer: null,
    currentIntervention: null,
    currentFilters: [],
    logic: 'AND',
    interventionConfig: null,
    chart: null,
};

// Feasibility colors
const FEASIBILITY_COLORS = {
    'very_high': '#1b5e20',
    'high': '#81c784',
    'moderate_high': '#c5e1a5',
    'moderate': '#ffd700',
    'low': '#ff8c00',
    'very_low': '#ff0000',
    'no_data': '#E0E0E0',
};

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    initEventListeners();

    // Auto-select first intervention
    const interventionSelect = document.getElementById('intervention-select');
    if (interventionSelect.options.length > 1) {
        interventionSelect.selectedIndex = 1;
        handleInterventionChange();
    }
});

// =============================================================================
// Map Functions
// =============================================================================

function initMap() {
    // Initialize Leaflet map
    state.map = L.map('map').setView([22.5, 82.5], 7);

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        maxZoom: 18,
    }).addTo(state.map);
}

function updateMap(geojsonData) {
    // Remove existing layer
    if (state.geojsonLayer) {
        state.map.removeLayer(state.geojsonLayer);
    }

    // Add new GeoJSON layer
    state.geojsonLayer = L.geoJSON(geojsonData, {
        style: featureStyle,
        onEachFeature: onEachFeature,
    }).addTo(state.map);

    // Fit bounds with more zoom
    if (state.geojsonLayer.getBounds().isValid()) {
        state.map.fitBounds(state.geojsonLayer.getBounds(), { padding: [100, 100], maxZoom: 12 });
    }
}

function featureStyle(feature) {
    const color = feature.properties.feasibility_color || FEASIBILITY_COLORS.no_data;
    return {
        fillColor: color,
        weight: 1,
        opacity: 1,
        color: '#333',
        fillOpacity: 0.7,
    };
}

function onEachFeature(feature, layer) {
    const props = feature.properties;
    const blockName = props.Block_name || 'Unknown';
    const feasibility = props.feasibility !== null ? props.feasibility.toFixed(1) + '%' : 'No Data';
    const label = props.feasibility_label || 'No Data';

    // Tooltip
    layer.bindTooltip(`
        <strong>${blockName}</strong><br>
        Feasibility: ${feasibility}<br>
        Category: ${label}
    `);

    // Click handler
    layer.on('click', () => showBlockDetails(props));

    // Hover effects
    layer.on('mouseover', () => {
        layer.setStyle({ weight: 3, color: '#000' });
    });
    layer.on('mouseout', () => {
        layer.setStyle({ weight: 1, color: '#333' });
    });
}

// =============================================================================
// Event Listeners
// =============================================================================

function initEventListeners() {
    // Intervention change
    document.getElementById('intervention-select').addEventListener('change', handleInterventionChange);

    // Variable group change
    document.getElementById('group-select').addEventListener('change', handleGroupChange);

    // Logic toggle
    document.getElementById('logic-and').addEventListener('click', () => setLogic('AND'));
    document.getElementById('logic-or').addEventListener('click', () => setLogic('OR'));

    // Configure button
    document.getElementById('configure-btn').addEventListener('click', openConfigModal);

    // Modal buttons
    document.getElementById('modal-close').addEventListener('click', closeConfigModal);
    document.getElementById('cancel-config').addEventListener('click', closeConfigModal);
    document.getElementById('apply-config').addEventListener('click', applyConfig);

    // Close modal on backdrop click
    document.getElementById('config-modal').addEventListener('click', (e) => {
        if (e.target.id === 'config-modal') closeConfigModal();
    });

    // Export button
    document.getElementById('export-btn').addEventListener('click', exportCSV);

    // Close block details
    document.getElementById('close-details').addEventListener('click', hideBlockDetails);
}

// =============================================================================
// Intervention Handling
// =============================================================================

async function handleInterventionChange() {
    const select = document.getElementById('intervention-select');
    const intervention = select.value;

    if (!intervention) {
        state.currentIntervention = null;
        state.interventionConfig = null;
        updateActiveFilters([]);
        return;
    }

    state.currentIntervention = intervention;

    // Fetch intervention config
    try {
        const response = await fetch(`/api/intervention/${encodeURIComponent(intervention)}/config`);
        const data = await response.json();
        state.interventionConfig = data;

        // Build default filters from config
        state.currentFilters = data.variables.map(v => ({
            column: v.field,
            min_val: v.range_min,
            max_val: v.range_max,
            weight: v.weight,
            label: v.label,
        }));

        // Calculate feasibility
        await calculateFeasibility();

    } catch (error) {
        console.error('Error loading intervention config:', error);
    }
}

function handleGroupChange() {
    // Reset intervention when group is selected
    document.getElementById('intervention-select').value = '';
    state.currentIntervention = null;
    // TODO: Implement group-based filtering
}

function setLogic(logic) {
    state.logic = logic;

    // Update UI
    document.getElementById('logic-and').classList.toggle('active', logic === 'AND');
    document.getElementById('logic-or').classList.toggle('active', logic === 'OR');

    // Recalculate if we have filters
    if (state.currentFilters.length > 0) {
        calculateFeasibility();
    }
}

// =============================================================================
// Feasibility Calculation
// =============================================================================

async function calculateFeasibility() {
    try {
        const response = await fetch('/api/calculate-feasibility', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                intervention: state.currentIntervention,
                filters: state.currentFilters,
                logic: state.logic,
            }),
        });

        const data = await response.json();

        // Update map
        updateMap(data.geojson);

        // Update statistics
        updateStatistics(data.statistics);

        // Update active filters display
        updateActiveFilters(state.currentFilters);

    } catch (error) {
        console.error('Error calculating feasibility:', error);
    }
}

// =============================================================================
// Configuration Modal
// =============================================================================

function openConfigModal() {
    if (!state.interventionConfig) {
        alert('Please select an intervention first');
        return;
    }

    const modal = document.getElementById('config-modal');
    const title = document.getElementById('modal-title');
    const form = document.getElementById('config-form');

    title.textContent = `Configure ${state.interventionConfig.name}`;

    // Build table HTML
    let rows = '';
    state.interventionConfig.variables.forEach((v, index) => {
        const currentFilter = state.currentFilters.find(f => f.column === v.field) || {};
        const minVal = currentFilter.min_val !== undefined ? currentFilter.min_val : v.range_min;
        const maxVal = currentFilter.max_val !== undefined ? currentFilter.max_val : v.range_max;
        const weight = currentFilter.weight !== undefined ? currentFilter.weight : v.weight;

        rows += `
            <tr class="config-row" data-field="${v.field}">
                <td class="config-sno-cell">${index + 1}</td>
                <td class="config-label-cell">
                    <div class="config-label">${v.label}</div>
                    <div class="config-description">${v.description || ''}</div>
                </td>
                <td class="config-min-cell">
                    <span class="min-display">${minVal.toFixed(1)}</span>
                    <input type="range" class="range-min"
                        min="${v.data_min}" max="${v.data_max}"
                        value="${minVal}" step="0.1"
                        data-field="${v.field}">
                </td>
                <td class="config-max-cell">
                    <span class="max-display">${maxVal.toFixed(1)}</span>
                    <input type="range" class="range-max"
                        min="${v.data_min}" max="${v.data_max}"
                        value="${maxVal}" step="0.1"
                        data-field="${v.field}">
                </td>
                <td class="config-weight-cell">
                    <input type="number" class="weight-input"
                        min="0" max="10" step="0.1"
                        value="${weight}"
                        data-field="${v.field}">
                </td>
            </tr>
        `;
    });

    form.innerHTML = `
        <table class="config-table">
            <thead>
                <tr>
                    <th><i class="bi bi-hash"></i> S.No</th>
                    <th><i class="bi bi-tag"></i> Variable</th>
                    <th><i class="bi bi-arrow-down"></i> Min Value</th>
                    <th><i class="bi bi-arrow-up"></i> Max Value</th>
                    <th><i class="bi bi-speedometer2"></i> Weight</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Add event listeners for sliders
    form.querySelectorAll('.range-min, .range-max').forEach(input => {
        input.addEventListener('input', updateRangeDisplay);
    });

    modal.classList.add('show');
}

function updateRangeDisplay(e) {
    const row = e.target.closest('.config-row');
    const minInput = row.querySelector('.range-min');
    const maxInput = row.querySelector('.range-max');
    const minDisplay = row.querySelector('.min-display');
    const maxDisplay = row.querySelector('.max-display');

    minDisplay.textContent = parseFloat(minInput.value).toFixed(1);
    maxDisplay.textContent = parseFloat(maxInput.value).toFixed(1);
}

function closeConfigModal() {
    document.getElementById('config-modal').classList.remove('show');
}

function applyConfig() {
    const form = document.getElementById('config-form');
    const rows = form.querySelectorAll('.config-row');

    state.currentFilters = [];

    rows.forEach(row => {
        const field = row.dataset.field;
        const minInput = row.querySelector('.range-min');
        const maxInput = row.querySelector('.range-max');
        const weightInput = row.querySelector('.weight-input');

        const configVar = state.interventionConfig.variables.find(v => v.field === field);

        state.currentFilters.push({
            column: field,
            min_val: parseFloat(minInput.value),
            max_val: parseFloat(maxInput.value),
            weight: parseFloat(weightInput.value),
            label: configVar ? configVar.label : field,
        });
    });

    closeConfigModal();
    calculateFeasibility();
}

// =============================================================================
// Statistics & Charts
// =============================================================================

function updateStatistics(stats) {
    // Update chart
    updateChart(stats.distribution);
}

function updateChart(distribution) {
    const ctx = document.getElementById('distribution-chart').getContext('2d');

    const categories = [
        { label: '100%', name: 'Very High', color: FEASIBILITY_COLORS.very_high },
        { label: '75-100%', name: 'High', color: FEASIBILITY_COLORS.high },
        { label: '50-75%', name: 'Mod-High', color: FEASIBILITY_COLORS.moderate_high },
        { label: '25-50%', name: 'Moderate', color: FEASIBILITY_COLORS.moderate },
        { label: '1-25%', name: 'Low', color: FEASIBILITY_COLORS.low },
        { label: '0%', name: 'Very Low', color: FEASIBILITY_COLORS.very_low },
        { label: 'No Data', name: 'No Data', color: FEASIBILITY_COLORS.no_data },
    ];

    const data = categories.map(cat => distribution[cat.label] || 0);
    const total = data.reduce((a, b) => a + b, 0);

    if (state.chart) {
        state.chart.destroy();
    }

    state.chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: categories.map(c => c.label),
            datasets: [{
                data: data,
                backgroundColor: categories.map(c => c.color),
                borderWidth: 1,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
            },
        },
    });

    // Update legend table
    const legendContainer = document.getElementById('chart-legend');
    const rows = categories.map((cat, i) => {
        const count = data[i];
        return `
            <tr>
                <td><span class="legend-color" style="background: ${cat.color};"></span></td>
                <td>${cat.name}</td>
                <td>${cat.label}</td>
                <td class="text-right">${count}</td>
            </tr>
        `;
    }).join('');

    legendContainer.innerHTML = `
        <table class="legend-table">
            <thead>
                <tr>
                    <th></th>
                    <th>Category</th>
                    <th>Range</th>
                    <th class="text-right">Count</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Update map legend with percentages
    const mapLegend = document.getElementById('map-legend');
    mapLegend.innerHTML = categories.map((cat, i) => {
        const count = data[i];
        const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0.0';
        return `
            <div class="legend-item">
                <span class="legend-color" style="background: ${cat.color};"></span>
                <span>${pct}%</span>
            </div>
        `;
    }).join('');
}

function updateActiveFilters(filters) {
    const container = document.getElementById('active-filters');

    if (!filters || filters.length === 0) {
        container.innerHTML = '<p class="no-filters">Select an intervention to see filters</p>';
        return;
    }

    const rows = filters.map(f => `
        <tr>
            <td>${f.label}</td>
            <td class="text-right">${f.min_val.toFixed(1)}</td>
            <td class="text-right">${f.max_val.toFixed(1)}</td>
            <td class="text-right">${f.weight.toFixed(1)}</td>
        </tr>
    `).join('');

    container.innerHTML = `
        <table class="filters-table">
            <thead>
                <tr class="filters-title-row">
                    <th colspan="4"><i class="bi bi-funnel"></i> Active Filters</th>
                </tr>
                <tr>
                    <th><i class="bi bi-tag"></i> Variable</th>
                    <th class="text-right"><i class="bi bi-arrow-down"></i> Min</th>
                    <th class="text-right"><i class="bi bi-arrow-up"></i> Max</th>
                    <th class="text-right"><i class="bi bi-speedometer2"></i> Weight</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;
}

// =============================================================================
// Block Details
// =============================================================================

function showBlockDetails(props) {
    const panel = document.getElementById('block-details');
    const nameEl = document.getElementById('block-name');
    const contentEl = document.getElementById('block-content');

    nameEl.textContent = props.Block_name || 'Unknown Block';

    // Build content
    const feasibility = props.feasibility !== null ? props.feasibility.toFixed(1) : 'N/A';
    const color = props.feasibility_color || FEASIBILITY_COLORS.no_data;

    let html = `
        <div class="detail-item">
            <div class="label">Feasibility</div>
            <div class="value">
                <span class="feasibility-badge" style="background: ${color}">
                    ${feasibility}%
                </span>
            </div>
        </div>
        <div class="detail-item">
            <div class="label">Category</div>
            <div class="value">${props.feasibility_label || 'No Data'}</div>
        </div>
    `;

    // Add filter variable values
    if (state.currentFilters.length > 0) {
        state.currentFilters.forEach(f => {
            const value = props[f.column];
            const displayValue = value !== null && value !== undefined ?
                (typeof value === 'number' ? value.toFixed(2) : value) : 'N/A';
            html += `
                <div class="detail-item">
                    <div class="label">${f.label}</div>
                    <div class="value">${displayValue}</div>
                </div>
            `;
        });
    }

    contentEl.innerHTML = html;
    panel.classList.remove('hidden');
}

function hideBlockDetails() {
    document.getElementById('block-details').classList.add('hidden');
}

// =============================================================================
// Export
// =============================================================================

async function exportCSV() {
    try {
        const response = await fetch('/api/export/csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                intervention: state.currentIntervention,
                filters: state.currentFilters,
                logic: state.logic,
            }),
        });

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'leaf_data.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

    } catch (error) {
        console.error('Error exporting CSV:', error);
        alert('Error exporting data');
    }
}
