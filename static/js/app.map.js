// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    initInfotip();
    initMap();
    initEventListeners();
    // Show the map spinner from the very start - the dropdown/hierarchy loads
    // below run before the first map data request, and the map looked dead
    // until then. loadInitialMapData() takes the loader over from here.
    setMapLoader(true);
    await loadInterventionsHierarchy();
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

// #6: toggle the small centered spinner overlay on the map container.
function setMapLoader(show) {
    const loader = document.getElementById('map-loader');
    if (loader) loader.style.display = show ? 'flex' : 'none';
}

// Loader overlay for the district/block detail grid. Shown alongside the map
// loader so recalculations are visible whichever view is open - without it,
// the detail cards just froze and looked broken while data reloaded.
function setDetailLoader(show) {
    const loader = document.getElementById('detail-loader');
    if (loader) loader.style.display = show ? 'flex' : 'none';
}

// Load initial map data (blocks)
async function loadInitialMapData() {
    setMapLoader(true);
    try {
        const response = await fetch('/api/blocks');
        const geojson = await response.json();
        updateMap(geojson);
    } catch (error) {
        console.error('Error loading initial map data:', error);
    } finally {
        setMapLoader(false);
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
    const isGPLevel = GP_FEATURE_ENABLED && initial.level === 'gp' && initial.block && initial.gp;

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
    } else if (initial.district) {
        // District-level aggregated card view (LEAF-52)
        await new Promise(resolve => setTimeout(resolve, 300));
        showDistrictDetailView(initial.district);
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
    // General tooltip on the map title word ("Feasibility Map") explaining
    // what the map shows. Attributes survive the innerHTML rewrites done by
    // updateChoroplethLegend/restoreDefaultLegend.
    const mapTitle = document.querySelector('.map-header h3');
    if (mapTitle) {
        mapTitle.dataset.infotip = FEASIBILITY_MAP_TIP;
        mapTitle.dataset.infotipPos = 'below';
    }

    // While the cursor is on the hover panel, never swap its content - the
    // user is reading/scrolling it (see hover-intent above).
    const hoverPanel = document.getElementById('map-hover-panel');
    if (hoverPanel) {
        hoverPanel.addEventListener('mouseenter', cancelPendingMapHoverTip);
    }

    // Initialize Leaflet map
    state.map = L.map('map').setView([22.5, 82.5], 7);

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        maxZoom: 18,
    }).addTo(state.map);

    // Load district boundary layer
    loadDistrictBoundaries();

    // Pre-load protected areas (not added to map until toggled)
    loadProtectedAreas();
}

async function loadDistrictBoundaries() {
    try {
        const response = await fetch('/api/districts/geojson');
        if (!response.ok) return;
        const geojson = await response.json();

        state.districtLayer = L.geoJSON(geojson, {
            style: {
                fillColor: 'transparent',
                fillOpacity: 0,
                color: '#28537D',
                weight: 1.5,
                opacity: 0.8,
                dashArray: '6, 4',
            },
            interactive: false,  // Don't capture mouse events - let block/GP layers handle clicks
            pane: 'overlayPane',
        });

        state.districtLayer.addTo(state.map);
    } catch (err) {
        console.warn('Could not load district boundaries:', err);
    }
}

async function loadProtectedAreas() {
    try {
        const response = await fetch('/api/protected-areas/geojson');
        if (!response.ok) return;
        const geojson = await response.json();

        state.protectedAreasLayer = L.geoJSON(geojson, {
            style: {
                fillColor: '#2e7d32',
                fillOpacity: 0.25,
                color: '#1b5e20',
                weight: 1.5,
                opacity: 0.8,
            },
            onEachFeature: function(feature, layer) {
                const p = feature.properties || {};
                const lines = [];
                if (p.name) lines.push(`<strong>${p.name}</strong>`);
                if (p.Type) lines.push(`Type: ${p.Type}`);
                if (p.State) lines.push(`State: ${p.State}`);
                if (p.Area) lines.push(`Area: ${Number(p.Area).toFixed(1)} km²`);
                if (p.Year) lines.push(`Year: ${p.Year}`);
                if (lines.length) layer.bindTooltip(lines.join('<br>'));
            },
            interactive: true,
            pane: 'overlayPane',
        });
        // Don't add to map - user toggles it via checkbox
    } catch (err) {
        console.warn('Could not load protected areas:', err);
    }
}

function toggleProtectedAreas(show) {
    if (!state.protectedAreasLayer) return;
    if (show) {
        state.protectedAreasLayer.addTo(state.map);
        // Ensure district boundaries stay on top
        if (state.districtLayer) state.districtLayer.bringToFront();
    } else {
        state.map.removeLayer(state.protectedAreasLayer);
    }
}

// =============================================================================
// Map hover panel: docked info box in the map's top-right corner (the classic
// Leaflet "info control" pattern). Hovering a block updates the content in
// place - the panel never moves, so a long variable list can be scrolled
// naturally. A cursor-following tooltip can't do that: it moves away as you
// chase it, and Leaflet-bound tooltips get clipped by the map container.
// The panel is sticky: it keeps showing the last hovered block until the map
// data refreshes or the user clicks through to a detail view.
// =============================================================================

// Hover-intent: the panel swaps content only after the cursor DWELLS on a
// block for a moment. Blocks merely crossed on the way to the panel (to
// scroll it) don't steal the content; entering the panel itself cancels any
// pending swap, so what you're reading is guaranteed to hold.
const MAP_PANEL_DWELL_MS = 300;
let mapPanelTimer = null;
let mapPanelCurrentHtml = '';

function cancelPendingMapHoverTip() {
    if (mapPanelTimer) { clearTimeout(mapPanelTimer); mapPanelTimer = null; }
}

function showMapHoverTip(html) {
    const panel = document.getElementById('map-hover-panel');
    if (!panel) return;

    // Re-entering the block already shown: keep it, drop any pending swap.
    if (html === mapPanelCurrentHtml && panel.style.display !== 'none') {
        cancelPendingMapHoverTip();
        return;
    }

    const render = () => {
        mapPanelCurrentHtml = html;
        // Close button: the panel is sticky (so it can be scrolled), which
        // means it needs an explicit dismiss too.
        panel.innerHTML =
            '<button class="map-hover-panel-close" title="Close" ' +
            'onclick="hideMapHoverTip()">&times;</button>' + html;
        panel.style.display = 'block';
        panel.scrollTop = 0;
    };

    // First show is instant; afterwards wait out the dwell delay.
    if (panel.style.display === 'none' || !panel.innerHTML) {
        cancelPendingMapHoverTip();
        render();
    } else {
        cancelPendingMapHoverTip();
        mapPanelTimer = setTimeout(render, MAP_PANEL_DWELL_MS);
    }
}

function hideMapHoverTip() {
    cancelPendingMapHoverTip();
    mapPanelCurrentHtml = '';
    const panel = document.getElementById('map-hover-panel');
    if (panel) panel.style.display = 'none';
}

function updateMap(geojsonData) {
    // The hover panel belongs to the old layer's features - never leave it
    // stuck on screen across a data refresh.
    hideMapHoverTip();

    // Remove existing layer
    if (state.geojsonLayer) {
        state.map.removeLayer(state.geojsonLayer);
    }

    // Add new GeoJSON layer
    state.geojsonLayer = L.geoJSON(geojsonData, {
        style: featureStyle,
        onEachFeature: onEachFeature,
    }).addTo(state.map);

    // Bring overlay layers to front so they draw over data polygons
    if (state.protectedAreasLayer && state.map.hasLayer(state.protectedAreasLayer)) {
        state.protectedAreasLayer.bringToFront();
    }
    if (state.districtLayer) {
        state.districtLayer.bringToFront();
    }

    // Fit bounds only when no district is selected
    // (when a district IS selected, filterMapByLocation() handles zoom to that district)
    if (!state.currentDistrict && state.geojsonLayer.getBounds().isValid()) {
        state.map.fitBounds(state.geojsonLayer.getBounds(), { padding: [100, 100], maxZoom: 12 });
    }
}

