
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
        },
        onEachFeature: (feat, layer) => {
            const p = feat.properties || {};
            const name = p.Block_name || 'Block';
            const feas = (p.feasibility !== null && p.feasibility !== undefined) ? p.feasibility.toFixed(1) + '%' : null;
            const tip = feas ? `<strong>${name}</strong><br>Feasibility: ${feas}` : `<strong>${name}</strong>`;
            layer.bindTooltip(tip, { className: 'custom-tooltip' });
        }
    }).addTo(state.blockMiniMap);

    // Fit bounds
    state.blockMiniMap.fitBounds(blockLayer.getBounds(), { padding: [20, 20] });

    // The 50/50 layout gives the map a tall container that may have been
    // display:none at creation - resize + refit once it's laid out (LEAF-54).
    setTimeout(() => {
        if (state.blockMiniMap) {
            state.blockMiniMap.invalidateSize();
            try { state.blockMiniMap.fitBounds(blockLayer.getBounds(), { padding: [20, 20] }); } catch (e) {}
        }
    }, 150);

    // For GP-enabled districts, load GP polygons inside this block
    const props = feature.properties;
    const blockName = props.Block_name || '';
    const districtName = props.Dist_Name || '';
    const hasGPData = state.gpAvailable && state.gpDistricts.includes(districtName);

    if (hasGPData && blockName) {
        loadGPPolygonsInMiniMap(blockName);
    }

    // Feasibility legend (LEAF #4) - loadGPPolygonsInMiniMap re-adds it for GP layers.
    addMiniMapLegend(state.blockMiniMap);
}

/**
 * Get fill color for a GP feature.
 * Uses feasibility color if calculated, otherwise falls back to default green.
 */
function gpFillColor(feature) {
    const fc = feature.properties.feasibility_color;
    return (fc && fc !== FEASIBILITY_COLORS.no_data) ? fc : '#22AD7A';
}

async function loadGPPolygonsInMiniMap(blockName) {
    // Spinner over the detail view (the overview map - and its loader - is
    // hidden while the block view is open, so setMapLoader was invisible here).
    setDetailLoader(true);
    try {
        // If feasibility filters are active, fetch scored GP data; otherwise plain geojson
        let geojson;
        if (state.currentFilters.length > 0) {
            const resp = await fetch('/api/gp/calculate-feasibility', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    intervention: state.currentIntervention || null,
                    filters: state.currentFilters,
                    block: blockName,
                }),
            });
            const data = await resp.json();
            geojson = data.geojson;
        } else {
            const resp = await fetch('/api/gp/geojson');
            geojson = await resp.json();
        }

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

        // Add GP polygons to the mini map with feasibility colors
        const gpLayer = L.geoJSON(blockGPs, {
            style: (feature) => ({
                fillColor: gpFillColor(feature),
                color: '#1b5e20',
                weight: 1.5,
                fillOpacity: 0.6,
            }),
            onEachFeature: (feat, layer) => {
                const gpName = feat.properties.GP_NAME || 'Unknown GP';
                const feas = feat.properties.feasibility;
                const feasLabel = feas != null ? ` (${feas.toFixed(1)}%)` : '';
                layer.bindTooltip(gpName + feasLabel, { className: 'custom-tooltip' });
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

        // Add feasibility legend if filters are active
        if (state.currentFilters.length > 0) {
            addMiniMapLegend(state.blockMiniMap);
        }
    } catch (error) {
        console.error('Error loading GP polygons in mini map:', error);
    } finally {
        setDetailLoader(false);
    }
}

/**
 * Add a compact feasibility legend to a mini-map as a Leaflet control.
 */
function addMiniMapLegend(map) {
    // Remove existing legend if any
    if (map._miniLegend) {
        map.removeControl(map._miniLegend);
    }

    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = function () {
        const div = L.DomUtil.create('div', 'mini-map-legend');
        const items = [
            { label: '100%', color: FEASIBILITY_COLORS.very_high },
            { label: '75%+', color: FEASIBILITY_COLORS.high },
            { label: '50%+', color: FEASIBILITY_COLORS.moderate_high },
            { label: '25%+', color: FEASIBILITY_COLORS.moderate },
            { label: '1%+',  color: FEASIBILITY_COLORS.low },
            { label: '0%',   color: FEASIBILITY_COLORS.very_low },
        ];
        div.innerHTML = '<div class="mini-legend-title">Feasibility</div>' +
            items.map(i =>
                `<span class="mini-legend-item"><i style="background:${i.color}"></i>${i.label}</span>`
            ).join('');
        return div;
    };
    legend.addTo(map);
    map._miniLegend = legend;
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
        // "Select GP" chosen - restore block-level metrics
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
                layer.setStyle({ fillColor: gpFillColor(layer.feature), fillOpacity: 0.6, weight: 1.5, color: '#1b5e20' });
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

        // Swap metric cards to GP data
        renderGPMetricsInBlockView(props);

        // Re-select GP in dropdown (renderBlockDetail may have reset it)
        document.getElementById('block-gp-select').value = selectedGP;
    }
}

