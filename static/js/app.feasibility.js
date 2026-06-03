// =============================================================================
// Feasibility Calculation
// =============================================================================

async function calculateFeasibility() {
    setMapLoader(true);  // #6: show map spinner while recalculating
    try {
        // Use different API endpoint based on current level
        const apiUrl = state.currentLevel === 'gp'
            ? '/api/gp/calculate-feasibility'
            : '/api/calculate-feasibility';

        const payload = {
            intervention: state.currentIntervention || null,
            filters: state.currentFilters,
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

        // Update active filters display with district-scoped variable stats
        updateActiveFilters(state.currentFilters, data.statistics.variable_stats);

        // Render variable toggle buttons
        renderVariableToggles();

        // Apply district filter to map visuals
        filterMapByLocation();

    } catch (error) {
        console.error('Error calculating feasibility:', error);
    } finally {
        setMapLoader(false);  // #6
    }
}

