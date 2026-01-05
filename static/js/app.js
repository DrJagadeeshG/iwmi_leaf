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
    currentBlock: null,
    blockMiniMap: null,
    blockFeature: null,
    allBlocks: [],  // Store all block data for filtering
    currentState: '',
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
    loadLocationDropdowns();

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

    // Click handler - pass the full feature for block detail view
    layer.on('click', () => showBlockDetails(props, feature));

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
    // Location dropdowns
    document.getElementById('state-select').addEventListener('change', handleStateChange);
    document.getElementById('block-select').addEventListener('change', handleBlockChange);

    // Intervention change
    document.getElementById('intervention-select').addEventListener('change', handleInterventionChange);

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

    // Back to overview link
    document.getElementById('back-to-overview').addEventListener('click', (e) => {
        e.preventDefault();
        showOverviewView();
    });
}

// =============================================================================
// Location Dropdown Handling
// =============================================================================

async function loadLocationDropdowns() {
    try {
        const response = await fetch('/api/locations');
        const data = await response.json();

        state.allBlocks = data.blocks || [];

        // Populate state dropdown
        const stateSelect = document.getElementById('state-select');
        const states = [...new Set(state.allBlocks.map(b => b.state).filter(s => s))].sort();
        states.forEach(s => {
            const option = document.createElement('option');
            option.value = s;
            option.textContent = s;
            stateSelect.appendChild(option);
        });

        // Populate block dropdown with all blocks initially
        const blockSelect = document.getElementById('block-select');
        const blockNames = [...new Set(state.allBlocks.map(b => b.block_name).filter(b => b))].sort();
        blockNames.forEach(b => {
            const option = document.createElement('option');
            option.value = b;
            option.textContent = b;
            blockSelect.appendChild(option);
        });

    } catch (error) {
        console.error('Error loading locations:', error);
    }
}

function handleStateChange() {
    const selectedState = document.getElementById('state-select').value;
    state.currentState = selectedState;

    // Update block dropdown
    const blockSelect = document.getElementById('block-select');
    blockSelect.innerHTML = '<option value="">All Blocks</option>';

    let filteredBlocks = state.allBlocks;
    if (selectedState) {
        filteredBlocks = filteredBlocks.filter(b => b.state === selectedState);
    }

    const blockNames = [...new Set(filteredBlocks.map(b => b.block_name).filter(b => b))].sort();
    blockNames.forEach(b => {
        const option = document.createElement('option');
        option.value = b;
        option.textContent = b;
        blockSelect.appendChild(option);
    });

    // Update map to show filtered blocks
    filterMapByLocation();
}

function handleBlockChange() {
    const selectedBlock = document.getElementById('block-select').value;

    if (selectedBlock) {
        // Find the block feature and show detail view
        if (state.geojsonLayer) {
            state.geojsonLayer.eachLayer(layer => {
                const props = layer.feature.properties;
                const blockName = props.Block_name || '';
                if (blockName === selectedBlock) {
                    showBlockDetailView(layer.feature);
                }
            });
        }
    } else {
        showOverviewView();
        filterMapByLocation();
    }
}

function filterMapByLocation() {
    if (!state.geojsonLayer) return;

    state.geojsonLayer.eachLayer(layer => {
        const props = layer.feature.properties;
        let visible = true;

        if (state.currentState) {
            const blockState = props.State_name || props.STATE || props.state || '';
            visible = visible && (blockState === state.currentState);
        }

        if (visible) {
            layer.setStyle({ fillOpacity: 0.7 });
        } else {
            layer.setStyle({ fillOpacity: 0.1 });
        }
    });
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
// View Switching
// =============================================================================

function showOverviewView() {
    document.getElementById('overviewView').style.display = 'grid';
    document.getElementById('blockDetailView').style.display = 'none';
    state.currentBlock = null;

    // Destroy mini map if exists
    if (state.blockMiniMap) {
        state.blockMiniMap.remove();
        state.blockMiniMap = null;
    }
}

function showBlockDetailView(feature) {
    document.getElementById('overviewView').style.display = 'none';
    document.getElementById('blockDetailView').style.display = 'block';

    const props = feature.properties;
    state.currentBlock = props.Block_name || '';
    state.blockFeature = feature;

    renderBlockDetail(feature);
    initBlockMiniMap(feature);
}

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

    // Update header
    const blockName = props.Block_name || 'Unknown Block';
    document.getElementById('detail-block-name').textContent = blockName;

    // State name - hardcoded as Assam since shapefile only has STATE_ID
    document.getElementById('detail-block-location').textContent = 'Assam';

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

    // Render metrics by category
    renderLandAgriMetrics(props);
    renderWaterMetrics(props);
    renderInfrastructureMetrics(props);
    renderLivestockMetrics(props);
    renderPeopleMetrics(props);
}

function renderLandAgriMetrics(props) {
    const container = document.getElementById('land-agri-metrics');
    const metrics = [
        { key: 'J', label: 'Cropping Intensity', unit: '%', icon: 'bi-graph-up-arrow' },
        { key: 'AD', label: 'Paddy Area', unit: '%', icon: 'bi-flower1' },
        { key: 'AF', label: 'Horticulture Area', unit: '%', icon: 'bi-tree' },
        { key: 'AG', label: 'Crop Diversification Index', unit: '', icon: 'bi-diagram-3' },
        { key: 'AE', label: 'Fodder Crop Area', unit: '%', icon: 'bi-flower2' },
        { key: 'A', label: 'Farming Households', unit: '%', icon: 'bi-house' },
    ];
    renderMetricItems(container, props, metrics);
}

function renderWaterMetrics(props) {
    const container = document.getElementById('water-metrics');
    const metrics = [
        { key: 'C', label: 'Cultivated Area Irrigated', unit: '%', icon: 'bi-droplet' },
        { key: 'BC', label: 'Groundwater Development', unit: '%', icon: 'bi-moisture' },
        { key: 'AK', label: 'Micro-irrigation Coverage', unit: '%', icon: 'bi-water' },
        { key: 'E', label: 'Community Rainwater Harvesting', unit: '%', icon: 'bi-cloud-rain' },
        { key: 'B', label: 'Source of Irrigation', unit: '', icon: 'bi-droplet-half' },
    ];
    renderMetricItems(container, props, metrics);
}

function renderInfrastructureMetrics(props) {
    const container = document.getElementById('infrastructure-metrics');
    const metrics = [
        { key: 'X', label: 'Regular Markets/Mandies', unit: '%', icon: 'bi-shop' },
        { key: 'V', label: 'Banks (<5 km)', unit: '%', icon: 'bi-bank' },
        { key: 'I', label: 'Custom Hiring Centre', unit: '%', icon: 'bi-tools' },
        { key: 'K', label: 'Soil Testing Centres', unit: '%', icon: 'bi-clipboard-check' },
        { key: 'G', label: 'Warehouse for Food Grain', unit: '%', icon: 'bi-box-seam' },
        { key: 'S', label: 'All Weather Road', unit: '%', icon: 'bi-signpost-split' },
    ];
    renderMetricItems(container, props, metrics);
}

function renderLivestockMetrics(props) {
    const container = document.getElementById('livestock-metrics');
    const metrics = [
        { key: 'BF', label: 'Cattle Density', unit: 'per 100 ha', icon: 'bi-piggy-bank' },
        { key: 'BG', label: 'Buffalo Density', unit: 'per 100 ha', icon: 'bi-piggy-bank' },
        { key: 'M', label: 'Livestock Extension', unit: '%', icon: 'bi-building' },
        { key: 'N', label: 'Milk Collection Facility', unit: '%', icon: 'bi-cup-straw' },
        { key: 'O', label: 'Veterinary Clinic', unit: '%', icon: 'bi-hospital' },
    ];
    renderMetricItems(container, props, metrics);
}

function renderPeopleMetrics(props) {
    const container = document.getElementById('people-metrics');
    const metrics = [
        { key: 'Z', label: 'Households in SHGs', unit: '%', icon: 'bi-people' },
        { key: 'F', label: 'Villages with FPOs/PACs', unit: '%', icon: 'bi-building' },
        { key: 'AB', label: 'Households in Producer Groups', unit: '%', icon: 'bi-diagram-2' },
        { key: 'AC', label: 'SHGs Accessing Bank Loans', unit: '%', icon: 'bi-cash-coin' },
        { key: 'W', label: 'Jan Dhan Accounts', unit: '%', icon: 'bi-credit-card' },
        { key: 'BP', label: 'Literacy Rate', unit: '%', icon: 'bi-book' },
    ];
    renderMetricItems(container, props, metrics);
}

function renderMetricItems(container, props, metrics) {
    let html = '';
    metrics.forEach(m => {
        const value = props[m.key];
        let displayValue = 'N/A';
        if (value !== null && value !== undefined && value !== '') {
            displayValue = typeof value === 'number' ? value.toFixed(2) : value;
        }
        html += `
            <div class="metric-item">
                <span class="metric-label">
                    <i class="bi ${m.icon}"></i>
                    ${m.label}
                </span>
                <span class="metric-value">${displayValue}<span class="metric-unit">${m.unit}</span></span>
            </div>
        `;
    });
    container.innerHTML = html || '<p class="no-data">No data available</p>';
}

function initBlockMiniMap(feature) {
    // Destroy existing mini map
    if (state.blockMiniMap) {
        state.blockMiniMap.remove();
    }

    // Create new mini map
    state.blockMiniMap = L.map('block-mini-map', {
        zoomControl: false,
        attributionControl: false,
    });

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
    }).addTo(state.blockMiniMap);

    // Add block boundary
    const blockLayer = L.geoJSON(feature, {
        style: {
            fillColor: '#0297A6',
            color: '#28537D',
            weight: 2,
            fillOpacity: 0.3,
        }
    }).addTo(state.blockMiniMap);

    // Fit bounds
    state.blockMiniMap.fitBounds(blockLayer.getBounds(), { padding: [20, 20] });
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
