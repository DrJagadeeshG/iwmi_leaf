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
