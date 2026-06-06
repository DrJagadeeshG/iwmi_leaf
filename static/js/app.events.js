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

    // Click handler - pass the full feature for detail view
    layer.on('click', () => {
        showBlockDetails(props, feature);
    });

    // Hover effects: outline highlight only (the docked hover-info panel was
    // removed per 06-Jun feedback - block/GP details live in the click-through
    // detail views instead).
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

