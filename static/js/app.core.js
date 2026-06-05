/**
 * LEAF DSS - Frontend Application
 * Map, filters, and interactivity
 */

// =============================================================================
// Feature Flags
// =============================================================================

// LEAF-55: Gram Panchayat (GP) level is switched off for now. All GP code,
// routes and views are kept intact - flip this to true to re-enable the feature.
const GP_FEATURE_ENABLED = false;

// =============================================================================
// Global State
// =============================================================================

const state = {
    map: null,
    geojsonLayer: null,
    currentIntervention: null,      // main dropdown value (top-level or parent)
    currentSubcategory: null,       // sub-filter value (a child of the parent) or null
    interventionsByKey: {},         // name -> { parent, children, ... } hierarchy (LEAF-49/50/51)
    blockClusters: [],              // clusters for the current block+commodity (LEAF-53)
    currentViewLevel: 'state',      // state | district | block | cluster (for Download Summary, LEAF-58)
    districtAggProps: null,         // last district aggregate props (for the summary report)
    currentCluster: null,           // last selected cluster object (for the summary report)
    currentFilters: [],
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
    districtLayer: null,  // District boundary overlay layer
    protectedAreasLayer: null,  // Protected areas overlay layer
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

// Explanatory tooltip for the "Feasibility Map" title (shown on hover via the
// infotip; swapped for a variable-specific text when a choropleth is active).
const FEASIBILITY_MAP_TIP =
    'Each block is coloured by its feasibility score - the share of selected ' +
    'indicators that fall within their target range.\n' +
    'Green = high, yellow/orange = moderate, red = low, grey = no data.\n' +
    'Hover a block to see its values; click it to open the detail view.';

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
    // Field code omitted from tooltip for cleaner display
    if (opts.description && opts.description !== opts.label && opts.description !== opts.field)
        parts.push(opts.description);
    if (opts.group && opts.group !== 'Other') parts.push(`Group: ${opts.group}`);
    if (opts.data_min !== undefined && opts.data_max !== undefined) {
        const mean = opts.data_mean !== undefined ? ` | Avg: ${Number(opts.data_mean).toFixed(1)}` : '';
        parts.push(`Range: ${Number(opts.data_min).toFixed(1)} - ${Number(opts.data_max).toFixed(1)}${mean}`);
    }
    if (opts.range_min !== undefined && opts.range_max !== undefined) {
        parts.push(`Filter: ${Number(opts.range_min).toFixed(1)} - ${Number(opts.range_max).toFixed(1)}`);
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

