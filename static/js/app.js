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
    currentDistrict: '',
    availableVariables: [],  // Available variables for adding
    districtData: [],  // Hierarchical district data from API
    // GP-level state
    currentLevel: 'block',  // 'block' or 'gp'
    allGPs: [],  // Store all GP data for filtering
    gpsByBlock: {},  // GPs grouped by block
    currentGP: '',
    gpAvailable: false,
    gpDistrict: null,  // Primary district where GP data is available
    gpDistricts: [],  // All districts with GP data
    gpMiniMap: null,  // Mini map for GP detail view
    gpVariables: [],  // Available GP variables for config
    blockGPFeatures: [],  // GP features for current block (used in block detail GP dropdown)
    previousLevel: 'block',  // Track previous level for map reload
    // URL state
    applyingInitialState: false,  // Flag to prevent URL updates during init
    // Variable choropleth toggle
    activeVariable: null,  // Currently toggled variable field name (null = default feasibility)
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

// Choropleth color scale (5-step sequential yellow→green)
const CHOROPLETH_COLORS = [
    { label: 'Very Low', color: '#ffffcc' },
    { label: 'Low',      color: '#c2e699' },
    { label: 'Medium',   color: '#78c679' },
    { label: 'High',     color: '#31a354' },
    { label: 'Very High',color: '#006837' },
];
const CHOROPLETH_NO_DATA = '#E0E0E0';

// =============================================================================
// Infotip Helper - builds tooltip text for variable labels
// =============================================================================

/**
 * Build an infotip string for a variable.
 * @param {object} opts - { field, label, description, group, min, max, mean, range_min, range_max }
 * @returns {string} Multi-line tooltip text for data-infotip attribute
 */
function buildInfotip(opts = {}) {
    const parts = [];
    if (opts.field) parts.push(`Code: ${opts.field}`);
    if (opts.description && opts.description !== opts.label && opts.description !== opts.field)
        parts.push(opts.description);
    if (opts.group && opts.group !== 'Other') parts.push(`Group: ${opts.group}`);
    if (opts.data_min !== undefined && opts.data_max !== undefined) {
        const mean = opts.data_mean !== undefined ? ` | Avg: ${Number(opts.data_mean).toFixed(1)}` : '';
        parts.push(`Range: ${Number(opts.data_min).toFixed(1)} – ${Number(opts.data_max).toFixed(1)}${mean}`);
    }
    if (opts.range_min !== undefined && opts.range_max !== undefined) {
        parts.push(`Filter: ${Number(opts.range_min).toFixed(1)} – ${Number(opts.range_max).toFixed(1)}`);
    }
    return parts.join('\n');
}

/** Escape HTML attribute value */
function escAttr(str) {
    return String(str).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;');
}

/**
 * Initialize the global infotip element and event delegation.
 * Shows instantly on hover (no delay), hides instantly on leave.
 */
function initInfotip() {
    const tip = document.createElement('div');
    tip.id = 'infotip-el';
    document.body.appendChild(tip);

    let activeTarget = null;

    document.addEventListener('mouseover', (e) => {
        const el = e.target.closest('[data-infotip]');
        if (!el || !el.dataset.infotip) { return; }
        activeTarget = el;

        tip.textContent = el.dataset.infotip;
        tip.style.opacity = '1';

        // Position near the element
        const rect = el.getBoundingClientRect();
        const pos = el.dataset.infotipPos || 'above';

        let top, left;
        if (pos === 'below') {
            top = rect.bottom + 6;
            left = rect.left;
        } else if (pos === 'right') {
            top = rect.top + rect.height / 2;
            left = rect.right + 8;
        } else {
            // above (default)
            top = rect.top - 6;
            left = rect.left;
        }

        // Apply position, then adjust if off-screen
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';

        // Measure tip after rendering
        requestAnimationFrame(() => {
            const tipRect = tip.getBoundingClientRect();
            if (pos === 'above') {
                tip.style.top = (rect.top - tipRect.height - 6) + 'px';
            } else if (pos === 'right') {
                tip.style.top = (rect.top + rect.height / 2 - tipRect.height / 2) + 'px';
            }
            // Keep within viewport
            const tr = tip.getBoundingClientRect();
            if (tr.right > window.innerWidth - 8) {
                tip.style.left = (window.innerWidth - tr.width - 8) + 'px';
            }
            if (tr.left < 8) {
                tip.style.left = '8px';
            }
            if (tr.top < 8) {
                tip.style.top = (rect.bottom + 6) + 'px';
            }
            if (tr.bottom > window.innerHeight - 8) {
                tip.style.top = (rect.top - tr.height - 6) + 'px';
            }
        });
    });

    document.addEventListener('mouseout', (e) => {
        const el = e.target.closest('[data-infotip]');
        if (el && el === activeTarget) {
            tip.style.opacity = '0';
            activeTarget = null;
        }
    });
}

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    initInfotip();
    initMap();
    initEventListeners();
    await loadLocationDropdowns();

    // Load initial block map data
    await loadInitialMapData();

    // Apply initial state from URL if present
    if (window.INITIAL_STATE && window.INITIAL_STATE.district) {
        await applyInitialState();
    } else {
        // Auto-select first intervention only if no URL state
        const interventionSelect = document.getElementById('intervention-select');
        if (interventionSelect.options.length > 1) {
            interventionSelect.selectedIndex = 1;
            handleInterventionChange();
        }
    }
});

// Load initial map data (blocks)
async function loadInitialMapData() {
    try {
        const response = await fetch('/api/blocks');
        const geojson = await response.json();
        updateMap(geojson);
    } catch (error) {
        console.error('Error loading initial map data:', error);
    }
}

// Apply state from URL
async function applyInitialState() {
    const initial = window.INITIAL_STATE;

    if (!initial.district) return;

    // Prevent URL updates during initial state application
    state.applyingInitialState = true;

    // Set district dropdown (find matching option)
    const districtSelect = document.getElementById('district-select');
    for (let option of districtSelect.options) {
        if (option.value === initial.district) {
            districtSelect.value = initial.district;
            break;
        }
    }

    // Update state
    state.currentDistrict = initial.district;

    // Block level setup (always start at block level)
    state.currentLevel = 'block';

    // Update block dropdown for selected district
    const blockSelect = document.getElementById('block-select');
    blockSelect.innerHTML = '<option value="">All Blocks</option>';
    const filteredBlocks = state.allBlocks.filter(b => b.district === initial.district);
    filteredBlocks.forEach(b => {
        const option = document.createElement('option');
        option.value = b.block_name;
        option.textContent = b.block_name;
        blockSelect.appendChild(option);
    });

    // Auto-select first intervention so chart/filters populate
    const interventionSelect = document.getElementById('intervention-select');
    if (interventionSelect.options.length > 1 && !interventionSelect.value) {
        interventionSelect.selectedIndex = 1;
        await handleInterventionChange();
    }

    // Filter map to show only selected district
    filterMapByLocation();

    // Check if GP level (URL has /district/block/gp)
    const isGPLevel = initial.level === 'gp' && initial.block && initial.gp;

    if (isGPLevel) {
        // Switch to GP mode for this block
        state.currentBlock = initial.block;
        state.currentLevel = 'gp';
        state.previousLevel = 'gp';
        blockSelect.value = initial.block;

        // Show GP dropdown
        document.getElementById('gp-filter-group').style.display = '';
        populateGPDropdown(initial.block);

        // Load GP map data
        await loadGPData();
        filterMapByLocation();

        // Wait for map then show GP detail
        await new Promise(resolve => setTimeout(resolve, 300));

        if (initial.gp) {
            const gpSelect = document.getElementById('gp-select');
            gpSelect.value = initial.gp;
            state.currentGP = initial.gp;

            if (state.geojsonLayer) {
                state.geojsonLayer.eachLayer(layer => {
                    const props = layer.feature.properties;
                    if (props.GP_NAME === initial.gp) {
                        showGPDetailView(layer.feature);
                    }
                });
            }
        }
    } else if (initial.block) {
        // Block detail view
        blockSelect.value = initial.block;
        state.currentBlock = initial.block;

        // Show block detail view (same for all districts, including GP-enabled)
        await new Promise(resolve => setTimeout(resolve, 300));

        if (state.geojsonLayer) {
            state.geojsonLayer.eachLayer(layer => {
                const props = layer.feature.properties;
                if (props.Block_name === initial.block) {
                    showBlockDetailView(layer.feature);
                }
            });
        }
    }

    // Re-enable URL updates
    state.applyingInitialState = false;
}

// Update URL based on current state
function updateURL() {
    // Don't update URL during initial state application
    if (state.applyingInitialState) return;

    let path = '/';

    if (state.currentDistrict) {
        path = `/${encodeURIComponent(state.currentDistrict)}`;

        if (state.currentBlock) {
            path += `/${encodeURIComponent(state.currentBlock)}`;
        }

        // GP name as third segment: /district/block/gp
        if (state.currentLevel === 'gp' && state.currentGP && state.currentBlock) {
            path += `/${encodeURIComponent(state.currentGP)}`;
        }
    }

    // Update URL without page reload
    if (window.location.pathname !== path) {
        history.pushState({ level: state.currentLevel, district: state.currentDistrict }, '', path);
    }
}

// Handle browser back/forward
window.addEventListener('popstate', () => {
    // Reload page to apply URL state
    window.location.reload();
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

    // Fit bounds only when no district is selected
    // (when a district IS selected, filterMapByLocation() handles zoom to that district)
    if (!state.currentDistrict && state.geojsonLayer.getBounds().isValid()) {
        state.map.fitBounds(state.geojsonLayer.getBounds(), { padding: [100, 100], maxZoom: 12 });
    }
}

function featureStyle(feature) {
    let color;
    if (state.activeVariable) {
        color = getChoroplethColor(feature);
    } else {
        color = feature.properties.feasibility_color || FEASIBILITY_COLORS.no_data;
    }
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

    // Get name based on current level
    const isGP = state.currentLevel === 'gp';
    const name = isGP
        ? (props.GP_NAME || 'Unknown GP')
        : (props.Block_name || 'Unknown Block');

    const hasFeasibility = props.feasibility !== null && props.feasibility !== undefined;
    const feasibility = hasFeasibility ? props.feasibility.toFixed(1) + '%' : null;
    const label = props.feasibility_label || null;

    // Build tooltip content
    let tooltipContent = `<strong>${name}</strong>`;

    if (isGP) {
        // GP-specific info
        const vilCount = props.VIL_COUNT || props['NUMBER OF VILLAGE'];
        if (vilCount) {
            tooltipContent += `<br>Villages: ${vilCount}`;
        }
        tooltipContent += `<br>District: Tinsukia`;
    } else {
        // Block-specific info
        const district = props.Dist_Name;
        if (district) {
            tooltipContent += `<br>District: ${district}`;
        }
    }

    // Add active indicator values
    if (state.currentFilters.length > 0) {
        tooltipContent += `<br><hr style="margin:4px 0;border:none;border-top:1px solid #ccc;">`;
        state.currentFilters.forEach(f => {
            const value = props[f.column];
            const displayValue = (value !== null && value !== undefined && !isNaN(value))
                ? parseFloat(value).toFixed(1)
                : 'N/A';
            const inRange = value >= f.min_val && value <= f.max_val;
            const icon = inRange ? '✓' : '✗';
            const color = inRange ? '#22AD7A' : '#ff6b6b';
            tooltipContent += `<br><span style="color:${color}">${icon}</span> ${f.label}: <strong>${displayValue}</strong>`;
        });
    }

    // Add feasibility if calculated
    if (hasFeasibility) {
        tooltipContent += `<br><hr style="margin:4px 0;border:none;border-top:1px solid #ccc;">`;
        tooltipContent += `<strong>Feasibility: ${feasibility}</strong>`;
        tooltipContent += `<br>Category: ${label}`;
    } else if (state.currentFilters.length === 0) {
        tooltipContent += `<br><br><em>Click Configure to set filters</em>`;
    }

    // Tooltip
    layer.bindTooltip(tooltipContent, { className: 'custom-tooltip' });

    // Click handler - pass the full feature for detail view
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
    document.getElementById('district-select').addEventListener('change', handleDistrictChange);
    document.getElementById('block-select').addEventListener('change', handleBlockChange);
    document.getElementById('gp-select').addEventListener('change', handleGPChange);

    // Intervention change
    document.getElementById('intervention-select').addEventListener('change', handleInterventionChange);

    // Logic toggle
    document.getElementById('logic-and').addEventListener('click', () => setLogic('AND'));
    document.getElementById('logic-or').addEventListener('click', () => setLogic('OR'));

    // Block detail GP dropdown
    document.getElementById('block-gp-select').addEventListener('change', handleBlockGPSelect);

    // Configure button
    document.getElementById('configure-btn').addEventListener('click', openConfigModal);

    // Modal buttons
    document.getElementById('modal-close').addEventListener('click', closeConfigModal);
    document.getElementById('cancel-config').addEventListener('click', closeConfigModal);
    document.getElementById('apply-config').addEventListener('click', applyConfig);
    document.getElementById('add-variable-btn').addEventListener('click', openAddVariableModal);

    // Add Variable Modal
    document.getElementById('add-var-modal-close').addEventListener('click', closeAddVariableModal);
    document.getElementById('variable-search').addEventListener('input', (e) => filterVariables(e.target.value));
    document.getElementById('add-variable-modal').addEventListener('click', (e) => {
        if (e.target.id === 'add-variable-modal') closeAddVariableModal();
    });

    // AI Recommendation Modal
    document.getElementById('ai-modal-close').addEventListener('click', closeAIModal);
    document.getElementById('ai-modal').addEventListener('click', (e) => {
        if (e.target.id === 'ai-modal') closeAIModal();
    });

    // Close modal on backdrop click
    document.getElementById('config-modal').addEventListener('click', (e) => {
        if (e.target.id === 'config-modal') closeConfigModal();
    });

    // Export button
    document.getElementById('export-btn').addEventListener('click', exportCSV);

    // Back to overview link (Block view)
    document.getElementById('back-to-overview').addEventListener('click', (e) => {
        e.preventDefault();
        // Reset block dropdown to "All Blocks"
        const blockSelect = document.getElementById('block-select');
        if (blockSelect) blockSelect.value = '';
        showOverviewView();
    });

    // Back to overview link (GP view)
    document.getElementById('back-to-overview-gp').addEventListener('click', (e) => {
        e.preventDefault();
        // Reset GP dropdown
        const gpSelect = document.getElementById('gp-select');
        if (gpSelect) gpSelect.value = '';
        showOverviewView();
    });
}

// =============================================================================
// GP (Gram Panchayat) Functions
// =============================================================================

async function loadGPData() {
    try {
        const [geoResponse, varResponse] = await Promise.all([
            fetch('/api/gp/geojson'),
            fetch('/api/gp/variables')
        ]);
        const geojson = await geoResponse.json();
        updateMap(geojson);

        // Preload GP variable metadata for detail panels
        const gpVars = await varResponse.json();
        if (Array.isArray(gpVars)) {
            state.gpVariables = gpVars;
        }

        // Update map center for GP area
        if (state.map && geojson.features && geojson.features.length > 0) {
            state.map.fitBounds(state.geojsonLayer.getBounds(), { padding: [50, 50] });
        }

        // Sync block info from geojson features to allGPs
        syncGPBlockInfo();
    } catch (error) {
        console.error('Error loading GP data:', error);
    }
}

// Sync block info from geojson to allGPs array
function syncGPBlockInfo() {
    if (!state.geojsonLayer || state.allGPs.length === 0) return;

    state.geojsonLayer.eachLayer(layer => {
        const props = layer.feature.properties;
        const gpName = props.GP_NAME;
        const blockName = props.Block_Name;
        if (gpName && blockName) {
            const gp = state.allGPs.find(g => g.gp_name === gpName);
            if (gp) {
                gp.block = blockName;
            }
        }
    });
}

async function loadGPLocations() {
    try {
        const response = await fetch('/api/gp/locations');
        const data = await response.json();

        // Store GPs with block info (API now includes block field)
        state.allGPs = data.gps || [];
        state.gpsByBlock = data.by_block || {};

    } catch (error) {
        console.error('Error loading GP locations:', error);
    }
}

function populateGPDropdown(filterByBlock = null) {
    const gpSelect = document.getElementById('gp-select');
    gpSelect.innerHTML = '<option value="">All GPs</option>';

    // Get GPs, optionally filtered by block
    let gpsToShow = state.allGPs;
    if (filterByBlock) {
        gpsToShow = state.allGPs.filter(g => g.block === filterByBlock);
    }

    const gpNames = [...new Set(gpsToShow.map(g => g.gp_name).filter(g => g))].sort();
    gpNames.forEach(g => {
        const option = document.createElement('option');
        option.value = g;
        option.textContent = g;
        gpSelect.appendChild(option);
    });
}

function handleGPChange() {
    const selectedGP = document.getElementById('gp-select').value;
    state.currentGP = selectedGP;

    if (selectedGP) {
        // Find the GP feature and show detail view
        if (state.geojsonLayer) {
            state.geojsonLayer.eachLayer(layer => {
                const props = layer.feature.properties;
                const gpName = props.GP_NAME || '';
                if (gpName === selectedGP) {
                    // Store the block name and update block dropdown
                    const blockName = props.Block_Name || '';
                    state.currentBlock = blockName;

                    // Update block dropdown to show the GP's block
                    const blockSelect = document.getElementById('block-select');
                    if (blockName && blockSelect) {
                        // Check if block option exists, if not add it
                        let blockExists = false;
                        for (let opt of blockSelect.options) {
                            if (opt.value === blockName) {
                                blockExists = true;
                                break;
                            }
                        }
                        if (!blockExists) {
                            const option = document.createElement('option');
                            option.value = blockName;
                            option.textContent = blockName;
                            blockSelect.appendChild(option);
                        }
                        blockSelect.value = blockName;
                    }

                    showGPDetailView(layer.feature);
                }
            });
        }
    } else {
        state.currentBlock = '';
        // Reset block dropdown to "All Blocks"
        document.getElementById('block-select').value = '';
        showOverviewView();
        if (state.currentFilters.length > 0) {
            calculateFeasibility();
        }
    }

    // Update URL
    updateURL();
}

// =============================================================================
// Location Dropdown Handling
// =============================================================================

async function loadLocationDropdowns() {
    try {
        // Check GP availability first
        const levelsResponse = await fetch('/api/levels');
        const levelsData = await levelsResponse.json();

        const gpLevel = levelsData.levels.find(l => l.id === 'gp');
        if (gpLevel && gpLevel.available) {
            state.gpAvailable = true;
            // Now supports multiple districts with GP data
            state.gpDistricts = gpLevel.districts || [];
            state.gpDistrict = state.gpDistricts[0] || null;  // Primary GP district for backward compat
            await loadGPLocations();
        } else {
            state.gpAvailable = false;
            state.gpDistricts = [];
        }

        // Load location data
        const response = await fetch('/api/locations');
        const data = await response.json();

        // Store both flat and hierarchical data
        state.allBlocks = data.blocks || [];
        state.districtData = data.districts || [];

        // Populate district dropdown (GP-enabled districts at top)
        const districtSelect = document.getElementById('district-select');
        districtSelect.innerHTML = '<option value="">All Districts</option>';

        // Districts are already sorted by the API (GP-enabled first)
        state.districtData.forEach(d => {
            const option = document.createElement('option');
            option.value = d.name;
            // Mark districts with GP data available
            if (d.has_gp_data) {
                option.textContent = `★ ${d.name} (GP Data)`;
                option.classList.add('gp-available');
            } else {
                option.textContent = d.name;
            }
            districtSelect.appendChild(option);
        });

        // Populate block dropdown with all blocks initially
        const blockSelect = document.getElementById('block-select');
        blockSelect.innerHTML = '<option value="">All Blocks</option>';
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

async function handleDistrictChange() {
    const selectedDistrict = document.getElementById('district-select').value;
    state.currentDistrict = selectedDistrict;

    // Update block dropdown
    const blockSelect = document.getElementById('block-select');
    blockSelect.innerHTML = '<option value="">All Blocks</option>';

    let filteredBlocks = state.allBlocks;
    if (selectedDistrict) {
        filteredBlocks = filteredBlocks.filter(b => b.district === selectedDistrict);
    }

    const blockNames = [...new Set(filteredBlocks.map(b => b.block_name).filter(b => b))].sort();
    blockNames.forEach(b => {
        const option = document.createElement('option');
        option.value = b;
        option.textContent = b;
        blockSelect.appendChild(option);
    });

    // Reset block and GP selections when changing district
    state.currentBlock = '';
    state.currentGP = '';

    // Switch back to overview if currently in a detail view
    const inDetailView = document.getElementById('blockDetailView').style.display !== 'none'
        || document.getElementById('gpDetailView').style.display !== 'none';
    if (inDetailView) {
        document.getElementById('overviewView').style.display = 'grid';
        document.getElementById('blockDetailView').style.display = 'none';
        document.getElementById('gpDetailView').style.display = 'none';

        // Destroy mini maps
        if (state.blockMiniMap) { state.blockMiniMap.remove(); state.blockMiniMap = null; }
        if (state.gpMiniMap) { state.gpMiniMap.remove(); state.gpMiniMap = null; }

        // Leaflet needs size recalc after un-hiding
        if (state.map) setTimeout(() => state.map.invalidateSize(), 50);
    }

    // Always start at block level — GP drill-down happens when a block is selected
    state.currentLevel = 'block';

    // Hide GP dropdown initially (shown when a block is selected in GP-enabled district)
    document.getElementById('gp-filter-group').style.display = 'none';

    // If we were in GP mode, reload block map data and restore intervention
    if (state.previousLevel === 'gp') {
        await loadInitialMapData();

        // Re-select first intervention (was cleared when entering GP mode)
        const interventionSelect = document.getElementById('intervention-select');
        if (interventionSelect.options.length > 1 && !interventionSelect.value) {
            interventionSelect.selectedIndex = 1;
            await handleInterventionChange();
        } else {
            filterMapByLocation();
        }
    } else if (state.currentIntervention) {
        calculateFeasibility();
    } else {
        filterMapByLocation();
    }
    state.previousLevel = state.currentLevel;

    // Update URL
    updateURL();
}

async function handleBlockChange() {
    const selectedBlock = document.getElementById('block-select').value;
    state.currentBlock = selectedBlock;

    // Check if this district has GP data
    const hasGPData = state.gpAvailable && state.gpDistricts.includes(state.currentDistrict);

    if (selectedBlock) {
        // Show block detail view for all districts (including GP-enabled)
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
        // No block selected: back to district overview
        if (state.currentLevel === 'gp') {
            // Switching back from GP to block level
            state.currentLevel = 'block';
            state.previousLevel = 'gp';
            document.getElementById('gp-filter-group').style.display = 'none';

            // Reload block map
            await loadInitialMapData();

            // Re-select intervention if needed
            const interventionSelect = document.getElementById('intervention-select');
            if (interventionSelect.options.length > 1 && !interventionSelect.value) {
                interventionSelect.selectedIndex = 1;
                await handleInterventionChange();
            } else {
                filterMapByLocation();
            }
        } else {
            showOverviewView();
            filterMapByLocation();
        }
    }

    // Update URL
    updateURL();
}

function filterMapByLocation() {
    if (!state.geojsonLayer) return;

    const visibleLayers = [];

    state.geojsonLayer.eachLayer(layer => {
        const props = layer.feature.properties;
        let visible = true;

        // District filter
        if (state.currentDistrict) {
            const blockDistrict = props.Dist_Name || props.district || '';
            visible = String(blockDistrict) === String(state.currentDistrict);
        }

        // Block filter (GP mode: only show GPs belonging to selected block)
        if (visible && state.currentLevel === 'gp' && state.currentBlock) {
            const gpBlock = props.Block_Name || '';
            visible = String(gpBlock) === String(state.currentBlock);
        }

        if (visible) {
            // Restore color based on active mode (choropleth or feasibility)
            let color;
            if (state.activeVariable) {
                color = getChoroplethColor(layer.feature);
            } else {
                color = props.feasibility_color || FEASIBILITY_COLORS.no_data;
            }
            layer.setStyle({ fillColor: color, fillOpacity: 0.7, weight: 1, opacity: 1, color: '#333' });
            visibleLayers.push(layer);
        } else {
            // Hide non-matching features
            layer.setStyle({ fillColor: '#ffffff', fillOpacity: 0, weight: 0, opacity: 0 });
        }
    });

    // Auto-zoom to visible layers
    if (visibleLayers.length > 0) {
        const group = L.featureGroup(visibleLayers);
        state.map.fitBounds(group.getBounds(), { padding: [50, 50], maxZoom: 12 });
    } else if (!state.currentDistrict) {
        // Reset to full view when no district selected
        state.map.fitBounds(state.geojsonLayer.getBounds(), { padding: [50, 50] });
    }
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
        state.activeVariable = null;
        updateActiveFilters([]);
        renderVariableToggles();
        restoreDefaultLegend();
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
            group: v.group || 'Other',
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
        // Use different API endpoint based on current level
        const apiUrl = state.currentLevel === 'gp'
            ? '/api/gp/calculate-feasibility'
            : '/api/calculate-feasibility';

        const payload = {
            intervention: state.currentLevel === 'block' ? state.currentIntervention : null,
            filters: state.currentFilters,
            logic: state.logic,
            district: state.currentDistrict || null,
        };

        // Send block filter for GP-level so backend only returns GPs in that block
        if (state.currentLevel === 'gp' && state.currentBlock) {
            payload.block = state.currentBlock;
        }

        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        // Update map
        updateMap(data.geojson);

        // Update statistics (only for filtered district if selected)
        updateStatistics(data.statistics);

        // Update active filters display
        updateActiveFilters(state.currentFilters);

        // Render variable toggle buttons
        renderVariableToggles();

        // Apply district filter to map visuals
        filterMapByLocation();

    } catch (error) {
        console.error('Error calculating feasibility:', error);
    }
}

// =============================================================================
// Configuration Modal
// =============================================================================

async function openConfigModal() {
    // For GP level, allow configuration without intervention
    if (state.currentLevel === 'gp') {
        await openGPConfigModal();
        return;
    }

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
        const preference = currentFilter.preference || v.preference || 'moderate';

        rows += buildConfigRow(v, index, minVal, maxVal, preference);
    });

    form.innerHTML = `
        <table class="config-table">
            <thead>
                <tr>
                    <th><i class="bi bi-hash"></i> S.No</th>
                    <th><i class="bi bi-tag"></i> Variable</th>
                    <th><i class="bi bi-sliders2"></i> Preference</th>
                    <th><i class="bi bi-arrow-down"></i> Min Value</th>
                    <th><i class="bi bi-arrow-up"></i> Max Value</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Add event listeners for sliders and preference dropdowns
    form.querySelectorAll('.range-min, .range-max').forEach(input => {
        input.addEventListener('input', updateRangeDisplay);
    });
    form.querySelectorAll('.preference-select').forEach(select => {
        select.addEventListener('change', handlePreferenceChange);
    });

    modal.classList.add('show');
}

function buildConfigRow(v, index, minVal, maxVal, preference) {
    const minDisabled = preference === 'lower' ? 'disabled' : '';
    const maxDisabled = preference === 'higher' ? 'disabled' : '';
    const actualMinVal = preference === 'lower' ? v.data_min : minVal;
    const actualMaxVal = preference === 'higher' ? v.data_max : maxVal;

    const configTip = escAttr(buildInfotip({
        field: v.field, label: v.label, description: v.description,
        group: v.group, data_min: v.data_min, data_max: v.data_max, data_mean: v.data_mean,
    }));

    return `
        <tr class="config-row" data-field="${v.field}" data-data-min="${v.data_min}" data-data-max="${v.data_max}">
            <td class="config-sno-cell">${index + 1}</td>
            <td class="config-label-cell" data-infotip="${configTip}" data-infotip-pos="below">
                <div class="config-label">${v.label}</div>
                <div class="config-description">${v.description || ''}</div>
            </td>
            <td class="config-pref-cell">
                <select class="preference-select" data-field="${v.field}">
                    <option value="higher" ${preference === 'higher' ? 'selected' : ''}>Higher is better</option>
                    <option value="lower" ${preference === 'lower' ? 'selected' : ''}>Lower is better</option>
                    <option value="moderate" ${preference === 'moderate' ? 'selected' : ''}>Moderate is better</option>
                </select>
            </td>
            <td class="config-min-cell">
                <span class="min-display">${actualMinVal.toFixed(1)}</span>
                <input type="range" class="range-min"
                    min="${v.data_min}" max="${v.data_max}"
                    value="${actualMinVal}" step="0.1"
                    data-field="${v.field}" ${minDisabled}>
            </td>
            <td class="config-max-cell">
                <span class="max-display">${actualMaxVal.toFixed(1)}</span>
                <input type="range" class="range-max"
                    min="${v.data_min}" max="${v.data_max}"
                    value="${actualMaxVal}" step="0.1"
                    data-field="${v.field}" ${maxDisabled}>
            </td>
        </tr>
    `;
}

function handlePreferenceChange(e) {
    const select = e.target;
    const preference = select.value;
    const row = select.closest('.config-row');
    const dataMin = parseFloat(row.dataset.dataMin);
    const dataMax = parseFloat(row.dataset.dataMax);

    const minInput = row.querySelector('.range-min');
    const maxInput = row.querySelector('.range-max');
    const minDisplay = row.querySelector('.min-display');
    const maxDisplay = row.querySelector('.max-display');

    if (preference === 'lower') {
        // Lower is better: fix min at data_min (0 or lowest)
        minInput.value = dataMin;
        minInput.disabled = true;
        maxInput.disabled = false;
        minDisplay.textContent = dataMin.toFixed(1);
    } else if (preference === 'higher') {
        // Higher is better: fix max at data_max
        maxInput.value = dataMax;
        maxInput.disabled = true;
        minInput.disabled = false;
        maxDisplay.textContent = dataMax.toFixed(1);
    } else {
        // Moderate: both adjustable
        minInput.disabled = false;
        maxInput.disabled = false;
    }
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

// GP-level configuration modal
async function openGPConfigModal() {
    try {
        const response = await fetch('/api/gp/variables');
        const gpVariables = await response.json();

        const modal = document.getElementById('config-modal');
        const title = document.getElementById('modal-title');
        const form = document.getElementById('config-form');

        title.textContent = 'Configure GP Filters (Tinsukia)';

        // Group variables by category
        const grouped = {};
        gpVariables.forEach(v => {
            const group = v.group || 'Other';
            if (!grouped[group]) grouped[group] = [];
            grouped[group].push(v);
        });

        // Build table HTML with grouped variables
        let rows = '';
        let index = 0;
        Object.entries(grouped).forEach(([group, vars]) => {
            rows += `<tr class="group-header"><td colspan="5"><strong>${group}</strong></td></tr>`;
            vars.forEach(v => {
                const currentFilter = state.currentFilters.find(f => f.column === v.field) || {};
                const minVal = currentFilter.min_val !== undefined ? currentFilter.min_val : v.data_min;
                const maxVal = currentFilter.max_val !== undefined ? currentFilter.max_val : v.data_max;
                const isActive = currentFilter.column !== undefined;

                const gpTip = escAttr(buildInfotip({
                    field: v.field, label: v.label, description: v.description,
                    group: v.group, data_min: v.data_min, data_max: v.data_max, data_mean: v.data_mean,
                }));

                rows += `
                    <tr class="config-row ${isActive ? 'active-filter' : ''}" data-field="${v.field}" data-data-min="${v.data_min}" data-data-max="${v.data_max}">
                        <td class="config-check-cell">
                            <input type="checkbox" class="gp-var-check" data-field="${v.field}" ${isActive ? 'checked' : ''}>
                        </td>
                        <td class="config-label-cell" data-infotip="${gpTip}" data-infotip-pos="below">
                            <div class="config-label">${v.label}</div>
                        </td>
                        <td class="config-pref-cell">
                            <select class="preference-select" data-field="${v.field}">
                                <option value="higher">Higher is better</option>
                                <option value="lower">Lower is better</option>
                                <option value="moderate" selected>Moderate is better</option>
                            </select>
                        </td>
                        <td class="config-min-cell">
                            <span class="min-display">${v.data_min.toFixed(1)}</span>
                            <input type="range" class="range-min"
                                min="${v.data_min}" max="${v.data_max}"
                                value="${minVal}" step="0.1"
                                data-field="${v.field}">
                        </td>
                        <td class="config-max-cell">
                            <span class="max-display">${v.data_max.toFixed(1)}</span>
                            <input type="range" class="range-max"
                                min="${v.data_min}" max="${v.data_max}"
                                value="${maxVal}" step="0.1"
                                data-field="${v.field}">
                        </td>
                    </tr>
                `;
                index++;
            });
        });

        form.innerHTML = `
            <p style="margin-bottom: 1rem; color: #666;">Select variables to filter Gram Panchayats:</p>
            <table class="config-table">
                <thead>
                    <tr>
                        <th style="width: 40px;"><i class="bi bi-check-square"></i></th>
                        <th><i class="bi bi-tag"></i> Variable</th>
                        <th><i class="bi bi-sliders2"></i> Preference</th>
                        <th><i class="bi bi-arrow-down"></i> Min</th>
                        <th><i class="bi bi-arrow-up"></i> Max</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;

        // Store GP variables for later use
        state.gpVariables = gpVariables;

        // Add event listeners
        form.querySelectorAll('.range-min, .range-max').forEach(input => {
            input.addEventListener('input', updateRangeDisplay);
        });
        form.querySelectorAll('.preference-select').forEach(select => {
            select.addEventListener('change', handlePreferenceChange);
        });

        modal.classList.add('show');
    } catch (error) {
        console.error('Error loading GP variables:', error);
        alert('Error loading GP variables');
    }
}

function closeConfigModal() {
    document.getElementById('config-modal').classList.remove('show');
}

async function openAddVariableModal() {
    try {
        // Fetch all available variables
        const response = await fetch('/api/variables');
        const allVariables = await response.json();

        // Get currently used fields
        const usedFields = new Set(state.interventionConfig.variables.map(v => v.field));

        // Filter out already used variables
        const availableVars = allVariables.filter(v => !usedFields.has(v.field));

        // Store for filtering
        state.availableVariables = availableVars;

        // Render variable list
        renderVariableList(availableVars);

        // Show modal
        document.getElementById('add-variable-modal').classList.add('show');

    } catch (error) {
        console.error('Error loading variables:', error);
    }
}

function renderVariableList(variables) {
    const container = document.getElementById('variable-list');

    if (variables.length === 0) {
        container.innerHTML = '<div class="no-variables">No variables available</div>';
        return;
    }

    const header = `
        <div class="variable-list-header">
            <span>Code</span>
            <span>Label</span>
            <span>Category</span>
            <span></span>
        </div>
    `;

    const rows = variables.map(v => {
        const vTip = escAttr(buildInfotip({
            field: v.field, label: v.label, description: v.description,
            group: v.group, data_min: v.data_min, data_max: v.data_max, data_mean: v.data_mean,
        }));
        return `
        <div class="variable-item" data-field="${v.field}" data-infotip="${vTip}" data-infotip-pos="below">
            <div class="variable-item-code">${v.field}</div>
            <div class="variable-item-label">${v.label}</div>
            <div class="variable-item-group">${v.group || 'Other'}</div>
            <button class="variable-item-add" onclick="addVariable('${v.field}')">
                <i class="bi bi-plus"></i> Add
            </button>
        </div>
    `;
    }).join('');

    container.innerHTML = header + rows;
}

function filterVariables(searchTerm) {
    const filtered = state.availableVariables.filter(v =>
        v.field.toLowerCase().includes(searchTerm.toLowerCase()) ||
        v.label.toLowerCase().includes(searchTerm.toLowerCase())
    );
    renderVariableList(filtered);
}

function addVariable(field) {
    const selectedVar = state.availableVariables.find(v => v.field === field);
    if (!selectedVar) return;

    // Add to intervention config
    state.interventionConfig.variables.push(selectedVar);

    // Re-render the config table
    const form = document.getElementById('config-form');
    const tbody = form.querySelector('tbody');
    const newIndex = state.interventionConfig.variables.length - 1;
    const newRow = buildConfigRow(selectedVar, newIndex, selectedVar.data_min, selectedVar.data_max, selectedVar.preference || 'moderate');
    tbody.insertAdjacentHTML('beforeend', newRow);

    // Add event listeners to new row
    const lastRow = tbody.lastElementChild;
    lastRow.querySelectorAll('.range-min, .range-max').forEach(input => {
        input.addEventListener('input', updateRangeDisplay);
    });
    lastRow.querySelector('.preference-select').addEventListener('change', handlePreferenceChange);

    // Remove from available list
    state.availableVariables = state.availableVariables.filter(v => v.field !== field);
    renderVariableList(state.availableVariables);

    // Close modal if no more variables
    if (state.availableVariables.length === 0) {
        closeAddVariableModal();
    }
}

function closeAddVariableModal() {
    document.getElementById('add-variable-modal').classList.remove('show');
    document.getElementById('variable-search').value = '';
}

let aiLocationMap = null;

function closeAIModal() {
    document.getElementById('ai-modal').style.display = 'none';
    // Destroy the map when closing
    if (aiLocationMap) {
        aiLocationMap.remove();
        aiLocationMap = null;
    }
}

function initAILocationMap() {
    // Destroy existing map
    if (aiLocationMap) {
        aiLocationMap.remove();
        aiLocationMap = null;
    }

    const mapContainer = document.getElementById('ai-location-map');
    if (!mapContainer || !currentBlockFeature) return;

    // Create map
    aiLocationMap = L.map('ai-location-map', {
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
    });

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
    }).addTo(aiLocationMap);

    // Use the stored feature
    const blockLayer = L.geoJSON(currentBlockFeature, {
        style: {
            fillColor: '#0297A6',
            color: '#28537D',
            weight: 2,
            fillOpacity: 0.4,
        }
    }).addTo(aiLocationMap);

    aiLocationMap.fitBounds(blockLayer.getBounds(), { padding: [10, 10] });
}

function toggleRetrievedContext() {
    const body = document.getElementById('ai-context-body');
    const icon = document.getElementById('context-toggle-icon');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        icon.classList.remove('bi-chevron-down');
        icon.classList.add('bi-chevron-up');
    } else {
        body.style.display = 'none';
        icon.classList.remove('bi-chevron-up');
        icon.classList.add('bi-chevron-down');
    }
}

function copyAIRecommendation() {
    const modalBody = document.getElementById('ai-modal-body');
    const btn = document.getElementById('ai-copy-btn');

    // Get text content from the modal
    const header = modalBody.querySelector('.ai-recommendation-header');
    const content = modalBody.querySelector('.ai-text');

    let textToCopy = '';

    if (header) {
        const title = header.querySelector('h3');
        const meta = header.querySelectorAll('.ai-meta span');
        if (title) textToCopy += title.textContent + '\n';
        meta.forEach(m => textToCopy += m.textContent + '\n');
        textToCopy += '\n';
    }

    if (content) {
        // Get clean text without HTML tags
        textToCopy += content.innerText;
    }

    // Copy to clipboard
    navigator.clipboard.writeText(textToCopy).then(() => {
        // Show success feedback
        btn.classList.add('copied');
        btn.innerHTML = '<i class="bi bi-check"></i>';

        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<i class="bi bi-clipboard"></i>';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

function downloadAIRecommendation() {
    const modalBody = document.getElementById('ai-modal-body');
    const footer = document.getElementById('ai-modal-footer');

    // Get content
    const header = modalBody.querySelector('.ai-recommendation-header');
    const content = modalBody.querySelector('.ai-text');
    const table = modalBody.querySelector('.metrics-table');

    let title = 'Recommendations';
    let blockName = '';
    let intervention = '';
    let feasibility = '';

    if (header) {
        const h3 = header.querySelector('h3');
        if (h3) {
            title = h3.textContent;
            blockName = h3.textContent;
        }
        const metaSpans = header.querySelectorAll('.ai-meta span');
        metaSpans.forEach(span => {
            if (span.classList.contains('ai-intervention')) {
                intervention = span.textContent.trim();
            } else if (span.classList.contains('ai-feasibility')) {
                feasibility = span.textContent.trim();
            }
        });
    }

    // Get sources
    let sourcesHtml = '';
    const sourceItems = footer?.querySelectorAll('.source-item');
    if (sourceItems && sourceItems.length > 0) {
        sourcesHtml = '<h2>Reference Documents</h2><ul>';
        sourceItems.forEach(item => {
            const name = item.querySelector('.source-name')?.textContent || '';
            const num = item.querySelector('.source-number')?.textContent || '';
            sourcesHtml += `<li>${num} ${name}</li>`;
        });
        sourcesHtml += '</ul>';
    }

    // Create printable HTML
    const printContent = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>${title} - LEAF DSS</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; font-size: 11px; line-height: 1.6; }
                h1 { color: #28537D; font-size: 16px; border-bottom: 2px solid #0297A6; padding-bottom: 10px; margin-bottom: 5px; }
                h2 { color: #0297A6; font-size: 13px; margin-top: 20px; border-left: 3px solid #0297A6; padding-left: 8px; }
                .header-info { background: #f0fdfa; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
                .header-info p { margin: 3px 0; }
                .header-info strong { color: #28537D; }
                .recommendation { background: #fff; padding: 15px; border: 1px solid #e0e0e0; border-radius: 6px; margin: 15px 0; }
                .recommendation p { margin-bottom: 10px; }
                .ai-section-title { background: #f0fdfa; padding: 8px 12px; border-left: 3px solid #0297A6; margin: 15px 0 10px 0; font-weight: bold; color: #28537D; font-size: 12px; }
                .ai-section-title i { margin-right: 6px; }
                .ai-recommendation-item { display: flex; gap: 8px; margin: 8px 0; padding: 8px 10px; background: #fafafa; border-radius: 6px; border-left: 3px solid #0297A6; }
                .item-number { font-weight: bold; color: #0297A6; min-width: 18px; }
                .item-content { flex: 1; }
                .ai-bullet-item { display: flex; gap: 6px; margin: 4px 0; padding: 4px 10px; }
                .ai-bullet-item .bullet { color: #0297A6; font-weight: bold; }
                .citation { color: #0297A6; font-size: 8px; cursor: default; }
                table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 10px; }
                th { background: #28537D; color: white; padding: 8px; text-align: left; }
                td { padding: 8px; border-bottom: 1px solid #ddd; }
                tr.in-range { border-left: 3px solid #10b981; }
                tr.out-range { border-left: 3px solid #ef4444; }
                .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 9px; }
                .status-badge.pass { background: #d1fae5; color: #059669; }
                .status-badge.fail { background: #fee2e2; color: #dc2626; }
                ul { padding-left: 20px; }
                li { margin: 5px 0; }
                .footer { margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; font-size: 9px; color: #666; }
                @media print {
                    body { padding: 20px; }
                }
            </style>
        </head>
        <body>
            <h1>LEAF DSS - Recommendations Report</h1>
            <div class="header-info">
                <p><strong>Location:</strong> ${blockName}</p>
                <p><strong>Intervention:</strong> ${intervention}</p>
                <p><strong>${feasibility}</strong></p>
                <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
            </div>

            <h2>Recommendations</h2>
            <div class="recommendation">
                ${content ? content.innerHTML : '<p>No recommendation available</p>'}
            </div>

            ${table ? '<h2>Indicators Analyzed</h2>' + table.outerHTML : ''}

            ${sourcesHtml}

            <div class="footer">
                <p><strong>LEAF DSS</strong> - Landscape Evaluation & Assessment Framework</p>
                <p>IWMI - International Water Management Institute</p>
                <p>This report was generated using AI-powered analysis based on official policy documents.</p>
            </div>
        </body>
        </html>
    `;

    // Open print dialog (user can save as PDF)
    const printWindow = window.open('', '_blank');
    printWindow.document.write(printContent);
    printWindow.document.close();
    setTimeout(() => printWindow.print(), 300);
}

function applyConfig() {
    const form = document.getElementById('config-form');
    const rows = form.querySelectorAll('.config-row');

    state.currentFilters = [];

    rows.forEach(row => {
        const field = row.dataset.field;
        const minInput = row.querySelector('.range-min');
        const maxInput = row.querySelector('.range-max');
        const prefSelect = row.querySelector('.preference-select');

        // For GP mode, only include checked variables
        if (state.currentLevel === 'gp') {
            const checkbox = row.querySelector('.gp-var-check');
            if (!checkbox || !checkbox.checked) return;

            const gpVar = state.gpVariables ? state.gpVariables.find(v => v.field === field) : null;

            state.currentFilters.push({
                column: field,
                min_val: parseFloat(minInput.value),
                max_val: parseFloat(maxInput.value),
                weight: 1,
                label: gpVar ? gpVar.label : field,
                group: gpVar ? gpVar.group : 'Other',
                preference: prefSelect ? prefSelect.value : 'moderate',
            });
        } else {
            // Block mode - include all variables from intervention config
            const configVar = state.interventionConfig.variables.find(v => v.field === field);

            state.currentFilters.push({
                column: field,
                min_val: parseFloat(minInput.value),
                max_val: parseFloat(maxInput.value),
                weight: 1,
                label: configVar ? configVar.label : field,
                group: configVar ? configVar.group : 'Other',
                preference: prefSelect ? prefSelect.value : 'moderate',
            });
        }
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
 * No-op stub — toggle icons are now inline in the filters table.
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
                <span>${lo}–${hi}</span>
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

function updateActiveFilters(filters) {
    const container = document.getElementById('active-filters');

    if (!filters || filters.length === 0) {
        container.innerHTML = '<p class="no-filters">Select an intervention to see filters</p>';
        return;
    }

    // Get average values from intervention config if available
    const configVars = state.interventionConfig?.variables || [];

    const rows = filters.map(f => {
        const configVar = configVars.find(v => v.field === f.column);
        const avg = configVar?.data_mean ?? f.data_mean ?? '-';
        const avgDisplay = typeof avg === 'number' ? avg.toFixed(1) : avg;

        const tip = escAttr(buildInfotip({
            field: f.column,
            label: f.label,
            description: configVar?.description || f.description || '',
            group: f.group,
            data_min: configVar?.data_min,
            data_max: configVar?.data_max,
            data_mean: configVar?.data_mean,
            range_min: f.min_val,
            range_max: f.max_val,
        }));

        const isActive = state.activeVariable === f.column;
        const toggleCls = isActive ? 'var-map-toggle active' : 'var-map-toggle';
        const toggleIcon = isActive ? 'bi-map-fill' : 'bi-map';
        const rowCls = isActive ? 'var-row-active' : '';

        return `
            <tr class="${rowCls}">
                <td class="var-toggle-cell">
                    <button class="${toggleCls}" data-field="${escAttr(f.column)}" title="Show on map">
                        <i class="bi ${toggleIcon}"></i>
                    </button>
                </td>
                <td data-infotip="${tip}" data-infotip-pos="right">${f.label}</td>
                <td class="text-right">${f.min_val.toFixed(1)}</td>
                <td class="text-right">${avgDisplay}</td>
                <td class="text-right">${f.max_val.toFixed(1)}</td>
            </tr>
        `;
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

// =============================================================================
// View Switching
// =============================================================================

function showOverviewView() {
    document.getElementById('overviewView').style.display = 'grid';
    document.getElementById('blockDetailView').style.display = 'none';
    document.getElementById('gpDetailView').style.display = 'none';
    state.currentBlock = null;
    state.currentGP = null;

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

    renderBlockDetail(feature);
    initBlockMiniMap(feature);
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

    // Render recommendations (pass feature for map)
    renderRecommendations(props, feature);
}

function renderActiveMetricsByGroup(props) {
    // Group icons mapping
    const groupIcons = {
        'Land & Agri': 'bi-flower2',
        'Water': 'bi-droplet',
        'Infrastructure': 'bi-building',
        'Livestock': 'bi-piggy-bank',
        'People': 'bi-people',
        'Soil': 'bi-globe',
        'Climate': 'bi-cloud-sun',
        'Other': 'bi-grid'
    };

    // Container IDs mapping
    const groupContainers = {
        'Land & Agri': 'land-agri-metrics',
        'Water': 'water-metrics',
        'Infrastructure': 'infrastructure-metrics',
        'Livestock': 'livestock-metrics',
        'People': 'people-metrics'
    };

    // Count IDs mapping
    const groupCounts = {
        'Land & Agri': 'count-land-agri',
        'Water': 'count-water',
        'Infrastructure': 'count-infrastructure',
        'Livestock': 'count-livestock',
        'People': 'count-people'
    };

    // Clear all containers and counts first
    Object.keys(groupContainers).forEach(group => {
        const container = document.getElementById(groupContainers[group]);
        const countEl = document.getElementById(groupCounts[group]);
        if (container) {
            container.innerHTML = '';
            container.closest('.detail-card').style.display = 'none';
        }
        if (countEl) {
            countEl.innerHTML = '';
        }
    });

    let totalOutsideCount = 0;

    // If no filters, show all available data from the block
    if (!state.currentFilters || state.currentFilters.length === 0) {
        renderAllBlockMetrics(props, groupContainers);
        return totalOutsideCount;
    }

    // Group active filters by their group
    const groupedFilters = {};
    state.currentFilters.forEach(f => {
        const group = f.group || 'Other';
        if (!groupedFilters[group]) {
            groupedFilters[group] = [];
        }
        groupedFilters[group].push(f);
    });

    // Render each group
    Object.entries(groupedFilters).forEach(([group, filters]) => {
        const containerId = groupContainers[group];
        const countId = groupCounts[group];
        if (!containerId) return;

        const container = document.getElementById(containerId);
        const countEl = document.getElementById(countId);
        if (!container) return;

        // Show the card
        container.closest('.detail-card').style.display = 'block';

        // Build metrics
        const metrics = filters.map(f => ({
            key: f.column,
            label: f.label,
            unit: '',
            icon: groupIcons[group] || 'bi-check-circle',
            min: f.min_val,
            max: f.max_val
        }));

        const outsideCount = renderMetricItemsWithStatus(container, props, metrics);
        totalOutsideCount += outsideCount;

        // Update count in header
        if (countEl && outsideCount > 0) {
            countEl.innerHTML = `${outsideCount} outside range`;
        }
    });

    return totalOutsideCount;
}

// Render all available block metrics when no filters applied
function renderAllBlockMetrics(props, groupContainers) {
    // Define which fields belong to which group
    const fieldGroups = {
        'Land & Agri': ['A', 'AD', 'AE', 'AF', 'AG', 'AH', 'AI', 'AJ', 'AK', 'AL', 'AM', 'J'],
        'Water': ['B', 'C', 'D', 'E', 'BC', 'BD', 'AU'],
        'Infrastructure': ['G', 'H', 'I', 'K', 'L', 'S', 'T', 'U', 'V', 'W', 'X'],
        'Livestock': ['BF', 'BG', 'M', 'N', 'O', 'P', 'Q', 'R'],
        'People': ['Y', 'Z', 'AA', 'AB', 'AC', 'F']
    };

    // Show each group with its data
    Object.entries(fieldGroups).forEach(([group, fields]) => {
        const containerId = groupContainers[group];
        if (!containerId) return;

        const container = document.getElementById(containerId);
        if (!container) return;

        let rowsHtml = '';
        let hasData = false;

        fields.forEach(field => {
            const value = props[field];
            if (value !== null && value !== undefined && value !== '') {
                hasData = true;
                const numVal = typeof value === 'number' ? value : parseFloat(value);
                const displayValue = isNaN(numVal) ? value : numVal.toFixed(2);
                const fTip = escAttr(buildInfotip({ field: field, group: group }));
                rowsHtml += `
                    <div class="metric-row">
                        <span class="metric-label" data-infotip="${fTip}">${field}</span>
                        <span class="metric-value">${displayValue}</span>
                    </div>
                `;
            }
        });

        if (hasData) {
            container.innerHTML = wrapInScrollStructure(rowsHtml);
            container.closest('.detail-card').style.display = 'block';
            setTimeout(() => initScrollSync(container), 0);
        } else {
            container.innerHTML = '<p class="no-data">No data available</p>';
            container.closest('.detail-card').style.display = 'block';
        }
    });
}

// Helper to wrap content in scroll structure
function wrapInScrollStructure(html) {
    // Generate unique ID for syncing scrolls
    const scrollId = 'scroll-' + Math.random().toString(36).substr(2, 9);
    return `
        <div class="metrics-scroll-wrapper" id="${scrollId}-v">
            <div class="metrics-content" id="${scrollId}-content">
                ${html}
            </div>
        </div>
        <div class="metrics-h-scroll" id="${scrollId}-h">
            <div class="scroll-spacer" id="${scrollId}-spacer"></div>
        </div>
    `;
}

// Sync horizontal scrollbar with content (call after rendering)
function initScrollSync(container) {
    const wrapper = container.querySelector('.metrics-scroll-wrapper');
    const content = container.querySelector('.metrics-content');
    const hScroll = container.querySelector('.metrics-h-scroll');
    const spacer = container.querySelector('.scroll-spacer');

    if (!wrapper || !content || !hScroll || !spacer) return;

    // Check if content overflows horizontally
    const contentWidth = content.scrollWidth;
    const wrapperWidth = wrapper.clientWidth;
    const hasOverflow = contentWidth > wrapperWidth + 5; // 5px tolerance

    if (hasOverflow) {
        // Show scrollbar and set up sync
        hScroll.classList.add('visible');
        wrapper.classList.remove('no-h-scroll');
        spacer.style.width = contentWidth + 'px';

        // Sync scrolls
        wrapper.addEventListener('scroll', () => {
            hScroll.scrollLeft = wrapper.scrollLeft;
        });

        hScroll.addEventListener('scroll', () => {
            wrapper.scrollLeft = hScroll.scrollLeft;
        });

        // Enable horizontal scroll on wrapper (hidden scrollbar)
        wrapper.style.overflowX = 'scroll';
        wrapper.style.scrollbarWidth = 'none';
        wrapper.style.msOverflowStyle = 'none';
    } else {
        // No overflow - hide scrollbar
        hScroll.classList.remove('visible');
        wrapper.classList.add('no-h-scroll');
        wrapper.style.overflowX = 'hidden';
    }
}

function renderMetricItemsWithStatus(container, props, metrics) {
    let rowsHtml = '';
    let outsideCount = 0;

    metrics.forEach(m => {
        const value = props[m.key];
        let displayValue = 'N/A';
        let statusClass = '';
        let statusIcon = '';

        if (value !== null && value !== undefined && value !== '') {
            const numVal = typeof value === 'number' ? value : parseFloat(value);
            displayValue = numVal.toFixed(2);

            // Check if value is within range
            if (m.min !== undefined && m.max !== undefined) {
                if (numVal >= m.min && numVal <= m.max) {
                    statusClass = 'metric-pass';
                    statusIcon = '<i class="bi bi-check-circle-fill status-icon pass"></i>';
                } else {
                    statusClass = 'metric-fail';
                    statusIcon = '<i class="bi bi-x-circle-fill status-icon fail"></i>';
                    outsideCount++;
                }
            }
        }

        const mTip = escAttr(buildInfotip({
            field: m.key, label: m.label, group: m.group,
            range_min: m.min, range_max: m.max,
        }));

        rowsHtml += `
            <div class="metric-item ${statusClass}">
                <span class="metric-label" data-infotip="${mTip}">
                    <i class="bi ${m.icon}"></i>
                    ${m.label}
                </span>
                <span class="metric-value">${statusIcon}${displayValue}<span class="metric-unit">${m.unit}</span></span>
            </div>
        `;
    });
    if (rowsHtml) {
        container.innerHTML = wrapInScrollStructure(rowsHtml);
        setTimeout(() => initScrollSync(container), 0);
    } else {
        container.innerHTML = '<p class="no-data">No data available</p>';
    }
    return outsideCount;
}

function renderMetricItems(container, props, metrics) {
    let rowsHtml = '';
    metrics.forEach(m => {
        const value = props[m.key];
        let displayValue = 'N/A';
        if (value !== null && value !== undefined && value !== '') {
            displayValue = typeof value === 'number' ? value.toFixed(2) : value;
        }
        const mTip2 = escAttr(buildInfotip({ field: m.key, label: m.label, group: m.group }));
        rowsHtml += `
            <div class="metric-item">
                <span class="metric-label" data-infotip="${mTip2}">
                    <i class="bi ${m.icon}"></i>
                    ${m.label}
                </span>
                <span class="metric-value">${displayValue}<span class="metric-unit">${m.unit}</span></span>
            </div>
        `;
    });
    if (rowsHtml) {
        container.innerHTML = wrapInScrollStructure(rowsHtml);
        setTimeout(() => initScrollSync(container), 0);
    } else {
        container.innerHTML = '<p class="no-data">No data available</p>';
    }
}

// Store current block props and feature for AI recommendation
let currentBlockProps = null;
let currentBlockFeature = null;

function renderRecommendations(props, feature = null) {
    const container = document.getElementById('block-recommendations');
    const blockName = props.Block_name || 'Unknown';
    const districtName = props.Dist_Name || 'Unknown';
    const feasibility = props.feasibility;

    // Store props and feature for AI button
    currentBlockProps = props;
    if (feature) currentBlockFeature = feature;

    let icon = 'bi-lightbulb-fill';
    let recommendation = '';

    if (state.currentIntervention && feasibility !== null) {
        if (feasibility >= 75) {
            icon = 'bi-check-circle-fill';
            recommendation = `High potential for ${state.currentIntervention}`;
        } else if (feasibility >= 50) {
            icon = 'bi-arrow-up-circle-fill';
            recommendation = `Moderate potential for ${state.currentIntervention}`;
        } else if (feasibility >= 25) {
            icon = 'bi-exclamation-triangle-fill';
            recommendation = `Limited potential for ${state.currentIntervention}`;
        } else {
            icon = 'bi-x-circle-fill';
            recommendation = `Low potential for ${state.currentIntervention}`;
        }

        container.innerHTML = `
            <div class="recommendation-line-content">
                <i class="bi ${icon}"></i>
                <strong>${blockName}, ${districtName}:</strong> ${recommendation}
                <span class="feasibility-value">(${feasibility.toFixed(1)}%)</span>
            </div>
            <button class="btn-ai-recommend" onclick="openAIRecommendation()">
                <i class="bi bi-robot"></i> AI Insights
            </button>
        `;
    } else {
        recommendation = 'Select an intervention to see recommendations.';
        container.innerHTML = `<i class="bi ${icon}"></i> <strong>Recommendation for ${blockName}, Assam:</strong> ${recommendation}`;
    }
}

function openAIRecommendation() {
    if (!currentBlockProps) return;

    const modal = document.getElementById('ai-modal');
    const modalBody = document.getElementById('ai-modal-body');
    const modalFooter = document.getElementById('ai-modal-footer');

    // Show modal with loading state
    modal.style.display = 'flex';
    modalBody.innerHTML = `
        <div class="ai-loading-state">
            <i class="bi bi-robot ai-spin"></i>
            <p>Analyzing policy documents for <strong>${currentBlockProps.Block_name}</strong>...</p>
            <p class="ai-loading-detail">Intervention: ${state.currentIntervention}</p>
        </div>
    `;
    modalFooter.style.display = 'none';

    // Fetch AI recommendation
    fetchAIRecommendation(currentBlockProps);
}

async function fetchAIRecommendation(props) {
    const blockName = props.Block_name || 'Unknown';
    const districtName = props.Dist_Name || 'Unknown';
    const feasibility = props.feasibility;

    // Build metrics array from current filters
    const metrics = state.currentFilters.map(f => ({
        label: f.label || f.column,
        value: props[f.column],
        in_range: props[f.column] >= f.min_val && props[f.column] <= f.max_val,
        min: f.min_val,
        max: f.max_val
    }));

    const modalBody = document.getElementById('ai-modal-body');
    const modalFooter = document.getElementById('ai-modal-footer');
    const sourceLinks = document.getElementById('ai-source-links');

    try {
        const response = await fetch('/api/ai-recommendation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                block_name: blockName,
                district_name: districtName,
                intervention: state.currentIntervention,
                feasibility_score: feasibility,
                metrics: metrics,
                filters: state.currentFilters
            })
        });

        const data = await response.json();

        if (data.recommendation) {
            // Format recommendation with citations
            const formattedContent = formatAIRecommendationWithCitations(data.recommendation, data.sources || []);

            // Build retrieved context section if available
            const contextHtml = data.retrieved_context && data.retrieved_context.length > 0 ? `
                <div class="ai-context-section">
                    <div class="ai-context-header" onclick="toggleRetrievedContext()">
                        <h4><i class="bi bi-file-text"></i> Retrieved Context from Documents</h4>
                        <span class="context-toggle"><i class="bi bi-chevron-down" id="context-toggle-icon"></i></span>
                    </div>
                    <div class="ai-context-body" id="ai-context-body" style="display: none;">
                        ${data.retrieved_context.map((ctx, idx) => `
                            <div class="context-chunk">
                                <div class="context-source"><i class="bi bi-file-pdf"></i> ${ctx.source}</div>
                                <div class="context-text">${ctx.content}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : '';

            modalBody.innerHTML = `
                <div class="ai-recommendation-header">
                    <div class="ai-header-left">
                        <h3>${blockName}, ${districtName}</h3>
                        <div class="ai-meta">
                            <span class="ai-intervention"><i class="bi bi-flower2"></i> ${state.currentIntervention}</span>
                            <span class="ai-feasibility"><i class="bi bi-speedometer2"></i> Feasibility: ${feasibility.toFixed(1)}%</span>
                        </div>
                    </div>
                    <div class="ai-header-map" id="ai-location-map"></div>
                </div>
                <div class="ai-recommendation-content">
                    <div class="ai-text">${formattedContent.html}</div>
                </div>
                <div class="ai-metrics-summary">
                    <h4><i class="bi bi-table"></i> Indicators Analyzed</h4>
                    <table class="metrics-table">
                        <thead>
                            <tr>
                                <th>Indicator</th>
                                <th>Current Value</th>
                                <th>Target Range</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${metrics.map(m => `
                                <tr class="${m.in_range ? 'in-range' : 'out-range'}">
                                    <td class="metric-label">${m.label}</td>
                                    <td class="metric-value">${m.value !== null && m.value !== undefined ? parseFloat(m.value).toFixed(2) : 'N/A'}</td>
                                    <td class="metric-range">${m.min} - ${m.max}</td>
                                    <td class="metric-status">
                                        <span class="status-badge ${m.in_range ? 'pass' : 'fail'}">
                                            ${m.in_range ? '<i class="bi bi-check-circle-fill"></i> Pass' : '<i class="bi bi-x-circle-fill"></i> Fail'}
                                        </span>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
                ${contextHtml}
            `;

            // Show sources in footer
            if (data.sources && data.sources.length > 0) {
                modalFooter.style.display = 'block';
                sourceLinks.innerHTML = data.sources.map((source, idx) => `
                    <a href="/ai-docs/${encodeURIComponent(source)}" target="_blank" class="source-item" title="${source}">
                        <span class="source-number">[${idx + 1}]</span>
                        <span class="source-name">${source.replace('.pdf', '')}</span>
                        <i class="bi bi-box-arrow-up-right source-link"></i>
                    </a>
                `).join('');
            }

            // Initialize mini map for location
            initAILocationMap();
        } else if (data.error) {
            modalBody.innerHTML = `
                <div class="ai-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Unable to generate recommendation: ${data.error}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error fetching AI recommendation:', error);
        modalBody.innerHTML = `
            <div class="ai-error">
                <i class="bi bi-exclamation-triangle"></i>
                <p>Error connecting to AI service. Please try again.</p>
            </div>
        `;
    }
}

function formatAIRecommendationWithCitations(text, sources) {
    // Process line by line to avoid nesting issues
    const lines = text.split('\n');
    let htmlParts = [];
    let inItem = false; // track if we're inside a numbered item
    let citationIndex = 0;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i].trim();
        if (!line) {
            // Empty line = paragraph break
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            htmlParts.push('<br>');
            continue;
        }

        // Convert **bold** to strong
        line = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // ### Section headers
        if (line.match(/^###\s*/)) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            if (/assessment/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-clipboard-data"></i> Assessment</div>');
            } else if (/recommendation/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-list-check"></i> Recommendations</div>');
            } else if (/priority.action/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-exclamation-circle"></i> Priority Actions</div>');
            } else {
                htmlParts.push(`<div class="ai-section-title">${line.replace(/^###\s*/, '')}</div>`);
            }
            continue;
        }

        // Numbered items: "1. Title: content"
        const numMatch = line.match(/^(\d+)\.\s+([^:]+):\s*(.*)/);
        if (numMatch) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            const [, num, title, rest] = numMatch;
            citationIndex = (citationIndex % Math.max(sources.length, 1)) + 1;
            htmlParts.push(
                `<div class="ai-recommendation-item"><span class="item-number">${num}</span>` +
                `<div class="item-content"><strong>${title}</strong><sup class="citation" data-ref="${citationIndex}">[${citationIndex}]</sup>: ${rest}`
            );
            inItem = true;
            continue;
        }

        // Bullet points
        const bulletMatch = line.match(/^[-•]\s+(.*)/);
        if (bulletMatch) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            htmlParts.push(`<div class="ai-bullet-item"><span class="bullet">&bull;</span>${bulletMatch[1]}</div>`);
            continue;
        }

        // Regular text — continuation of current item or standalone paragraph
        if (inItem) {
            htmlParts.push(' ' + line);
        } else {
            htmlParts.push(`<p>${line}</p>`);
        }
    }

    // Close any open item
    if (inItem) { htmlParts.push('</div></div>'); }

    let html = htmlParts.join('\n');

    // Add citations to sentences mentioning policy keywords
    const policyKeywords = ['DAY-NRLM', 'NRLM', 'MKSP', 'SHG', 'organic', 'farming', 'training', 'guidelines', 'advisory', 'cluster', 'IFC'];
    policyKeywords.forEach(keyword => {
        const regex = new RegExp(`(${keyword}[^.]*)(\\.)`, 'gi');
        html = html.replace(regex, (match, content, dot) => {
            if (!content.includes('citation')) {
                const refNum = Math.floor(Math.random() * Math.max(sources.length, 1)) + 1;
                return `${content}<sup class="citation">[${refNum}]</sup>${dot}`;
            }
            return match;
        });
    });

    return { html, sources };
}

function formatAIRecommendation(text) {
    // Convert markdown-like formatting to HTML (kept for backward compatibility)
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n- /g, '</p><ul><li>')
        .replace(/\n(\d+)\. /g, '</p><ol><li>')
        .replace(/<\/li>\n/g, '</li>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>')
        .replace(/<p><\/p>/g, '');
}

function toggleAIRecommendation() {
    const body = document.getElementById('ai-recommendation-body');
    const icon = document.querySelector('.ai-toggle-icon');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        icon.classList.remove('bi-chevron-down');
        icon.classList.add('bi-chevron-up');
    } else {
        body.style.display = 'none';
        icon.classList.remove('bi-chevron-up');
        icon.classList.add('bi-chevron-down');
    }
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

    // For GP-enabled districts, load GP polygons inside this block
    const props = feature.properties;
    const blockName = props.Block_name || '';
    const districtName = props.Dist_Name || '';
    const hasGPData = state.gpAvailable && state.gpDistricts.includes(districtName);

    if (hasGPData && blockName) {
        loadGPPolygonsInMiniMap(blockName);
    }
}

async function loadGPPolygonsInMiniMap(blockName) {
    try {
        const response = await fetch('/api/gp/geojson');
        const geojson = await response.json();

        if (!geojson || !geojson.features || !state.blockMiniMap) return;

        // Filter GPs belonging to this block
        const blockGPs = {
            type: 'FeatureCollection',
            features: geojson.features.filter(f => {
                const gpBlock = f.properties.Block_Name || '';
                return gpBlock === blockName;
            })
        };

        if (blockGPs.features.length === 0) return;

        // Store GP features for metric lookup when GP is selected
        state.blockGPFeatures = blockGPs.features;

        // Add GP polygons to the mini map
        const gpLayer = L.geoJSON(blockGPs, {
            style: {
                fillColor: '#22AD7A',
                color: '#1b5e20',
                weight: 1.5,
                fillOpacity: 0.4,
            },
            onEachFeature: (feat, layer) => {
                const gpName = feat.properties.GP_NAME || 'Unknown GP';
                layer.bindTooltip(gpName, { className: 'custom-tooltip' });
                layer.on('click', () => {
                    // Update dropdown and trigger the same logic
                    const gpSelect = document.getElementById('block-gp-select');
                    gpSelect.value = gpName;
                    handleBlockGPSelect();
                });
            }
        }).addTo(state.blockMiniMap);

        // Fit bounds to show GP polygons
        state.blockMiniMap.fitBounds(gpLayer.getBounds(), { padding: [20, 20] });
    } catch (error) {
        console.error('Error loading GP polygons in mini map:', error);
    }
}

async function populateBlockGPDropdown(blockName) {
    const gpSelect = document.getElementById('block-gp-select');
    gpSelect.innerHTML = '<option value="">All GPs</option>';

    try {
        const response = await fetch(`/api/gp/block/${encodeURIComponent(blockName)}`);
        if (!response.ok) return;
        const data = await response.json();

        const gps = data.gps || [];
        gps.forEach(gp => {
            const option = document.createElement('option');
            option.value = gp.name;
            option.textContent = gp.name;
            gpSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Error populating block GP dropdown:', error);
    }
}

function handleBlockGPSelect() {
    const selectedGP = document.getElementById('block-gp-select').value;

    if (!selectedGP) {
        // "Select GP" chosen — restore block-level metrics
        if (state.blockFeature) {
            renderBlockDetail(state.blockFeature);
            initBlockMiniMap(state.blockFeature);
        }
        return;
    }

    // Highlight GP on mini map
    if (state.blockMiniMap) {
        state.blockMiniMap.eachLayer(layer => {
            if (!layer.feature) return;
            const gpName = layer.feature.properties.GP_NAME || '';
            if (gpName === selectedGP) {
                layer.setStyle({ fillColor: '#E86933', fillOpacity: 0.6, weight: 2.5, color: '#c0392b' });
                state.blockMiniMap.fitBounds(layer.getBounds(), { padding: [20, 20] });
                layer.openTooltip();
            } else if (layer.feature.properties.GP_NAME) {
                layer.setStyle({ fillColor: '#22AD7A', fillOpacity: 0.4, weight: 1.5, color: '#1b5e20' });
            }
        });
    }

    // Find the GP feature and swap metric cards to GP data
    const gpFeatures = state.blockGPFeatures || [];
    const gpFeature = gpFeatures.find(f => f.properties.GP_NAME === selectedGP);
    if (gpFeature) {
        const props = gpFeature.properties;

        // Update location title to show GP path
        const blockName = props.Block_Name || '';
        const districtName = props.Dist_Name || 'Tinsukia';
        document.getElementById('location-card-title').innerHTML = blockName
            ? `${districtName} / ${blockName} / <strong>${props.GP_NAME}</strong>`
            : `${districtName} / <strong>${props.GP_NAME}</strong>`;

        // Clear outside count (GP data has no block-level filter ranges)
        document.getElementById('total-outside-count').innerHTML = '';

        // Swap metric cards to GP data
        renderGPMetricsInBlockView(props);

        // Re-select GP in dropdown (renderBlockDetail may have reset it)
        document.getElementById('block-gp-select').value = selectedGP;
    }
}

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

    // Clear outside count
    document.getElementById('total-outside-count').innerHTML = '';

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
        'People': 'people-metrics'
    };

    const groupCounts = {
        'Land & Agri': 'count-land-agri',
        'Water': 'count-water',
        'Infrastructure': 'count-infrastructure',
        'Livestock': 'count-livestock',
        'People': 'count-people'
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
        'Soil': 'Land & Agri',
        'Climate': 'Water',
    };

    // Categorize GP properties using DSS metadata groups
    const grouped = {
        'Land & Agri': [],
        'Water': [],
        'Infrastructure': [],
        'Livestock': [],
        'People': []
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

    // Add GP boundary
    const gpLayer = L.geoJSON(feature, {
        style: {
            fillColor: '#22AD7A',
            color: '#1b5e20',
            weight: 2,
            fillOpacity: 0.3,
        }
    }).addTo(state.gpMiniMap);

    // Fit bounds
    state.gpMiniMap.fitBounds(gpLayer.getBounds(), { padding: [20, 20] });
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
