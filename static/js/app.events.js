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
        // #8: use the feature's own district rather than a hardcoded value.
        const gpDistrict = props.Dist_Name || props.district;
        if (gpDistrict) {
            tooltipContent += `<br>District: ${gpDistrict}`;
        }
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

    // Livestock sub-category change (LEAF-49/50/51)
    document.getElementById('subcategory-select').addEventListener('change', handleSubcategoryChange);

    // Block detail GP dropdown
    document.getElementById('block-gp-select').addEventListener('change', handleBlockGPSelect);

    // Block detail cluster dropdown (LEAF-53)
    document.getElementById('block-cluster-select').addEventListener('change', handleBlockClusterSelect);

    // Download Summary report (LEAF-58)
    document.getElementById('summary-btn').addEventListener('click', downloadSummaryReport);

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

