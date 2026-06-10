// Location Dropdown Handling
// =============================================================================

async function loadLocationDropdowns() {
    try {
        // Check GP availability first
        const levelsResponse = await fetch('/api/levels');
        const levelsData = await levelsResponse.json();

        const gpLevel = levelsData.levels.find(l => l.id === 'gp');
        if (GP_FEATURE_ENABLED && gpLevel && gpLevel.available) {
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
            // Mark districts with GP data available — only while the GP
            // drill-down feature is on. With GP_FEATURE_ENABLED off, Tinsukia
            // shows as a plain block-level district like the other 33 (the GP
            // pilot was the only reason it was ever special-cased here).
            if (GP_FEATURE_ENABLED && d.has_gp_data) {
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

    // Always start at block level - GP drill-down happens when a block is selected
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
        await calculateFeasibility();
    } else {
        filterMapByLocation();
    }
    state.previousLevel = state.currentLevel;

    // District-level card view (LEAF-52): a specific district shows aggregated
    // cards like a block; "All Districts" keeps the state-level overview.
    if (selectedDistrict) {
        showDistrictDetailView(selectedDistrict);
    } else {
        showOverviewView();
    }

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
        } else if (state.currentDistrict) {
            // Back to district-level aggregated cards (LEAF-52)
            showDistrictDetailView(state.currentDistrict);
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

