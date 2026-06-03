// =============================================================================
// Intervention Handling
// =============================================================================

// Load the intervention hierarchy (top-level + parents/children) so the UI
// can show the livestock sub-category dropdown (LEAF-49/50/51).
async function loadInterventionsHierarchy() {
    try {
        const resp = await fetch('/api/interventions');
        const data = await resp.json();
        state.interventionsByKey = {};
        (data.interventions || []).forEach(i => { state.interventionsByKey[i.key] = i; });
    } catch (e) {
        console.error('Error loading interventions hierarchy:', e);
        state.interventionsByKey = {};
    }
}

// Populate + show/hide the sub-category dropdown based on the selected
// intervention's children. Returns true if a sub-filter is shown.
function updateSubcategoryDropdown(interventionKey) {
    const group = document.getElementById('subcategory-filter-group');
    const select = document.getElementById('subcategory-select');
    const info = state.interventionsByKey[interventionKey];
    const children = (info && info.children) || [];
    select.innerHTML = '';
    if (!children.length) {
        group.style.display = 'none';
        const opt = document.createElement('option');
        opt.value = ''; opt.textContent = 'All';
        select.appendChild(opt);
        return false;
    }
    const allOpt = document.createElement('option');
    allOpt.value = ''; allOpt.textContent = 'All ' + interventionKey;
    select.appendChild(allOpt);
    children.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        select.appendChild(opt);
    });
    group.style.display = '';
    return true;
}

async function handleInterventionChange() {
    const select = document.getElementById('intervention-select');
    const intervention = select.value;

    // Reset any previous sub-category selection when the parent changes.
    state.currentSubcategory = null;

    if (!intervention) {
        state.currentIntervention = null;
        state.interventionConfig = null;
        state.activeVariable = null;
        updateSubcategoryDropdown('');
        updateActiveFilters([]);
        renderVariableToggles();
        restoreDefaultLegend();
        // Clear the cluster dropdown too — no commodity is active (LEAF-53).
        if (state.currentBlock) updateBlockClusterDropdown(state.currentBlock);
        return;
    }

    state.currentIntervention = intervention;
    // Show the sub-category dropdown if this intervention has children. The
    // parent itself shows its combined config until a child is picked.
    updateSubcategoryDropdown(intervention);

    await applyIntervention(intervention);
    // After feasibility recalculates, re-render whichever detail view is open so
    // its badges + metric cards reflect the new intervention (LEAF #18). Without
    // this the district/block detail showed stale data.
    rerenderActiveDetailView();
    // Switching intervention away from Livestock (or to a non-livestock parent
    // before a sub-category is picked) leaves currentSubcategory null, so the
    // cluster dropdown should hide. Refresh it (LEAF-53).
    if (state.currentBlock) updateBlockClusterDropdown(state.currentBlock);
}

// Re-render whichever detail view is currently open so it picks up freshly
// recalculated feasibility after applyIntervention() (LEAF #18).
function rerenderActiveDetailView() {
    if (state.currentBlock && state.blockFeature) {
        renderBlockDetail(state.blockFeature);
    } else if (state.currentViewLevel === 'district' && state.currentDistrict) {
        showDistrictDetailView(state.currentDistrict);
    } else if (state.currentViewLevel === 'gp' && state.currentGP) {
        showGPDetailView(state.blockFeature);
    }
}

// React to a livestock sub-category choice: load that child's config, or fall
// back to the parent's combined config when "All" is selected (LEAF-50).
// Also refresh the block-level cluster dropdown (LEAF-53) so the available
// clusters reflect the newly-picked commodity — the dropdown used to update
// only when the block view first loaded, so changing sub-category mid-view
// left the cluster list stale.
async function handleSubcategoryChange() {
    const sub = document.getElementById('subcategory-select').value;
    state.currentSubcategory = sub || null;
    const effective = state.currentSubcategory || state.currentIntervention;
    if (effective) await applyIntervention(effective);
    // Re-render the open detail view so its badges + metric cards reflect the
    // sub-category's recalculated feasibility (LEAF #18).
    rerenderActiveDetailView();
    if (state.currentBlock) {
        // If a cluster was being viewed, drop back to block view first so the
        // user isn't stuck on a stale cluster detail from the old commodity.
        if (state.currentCluster) {
            setClusterMode(false);
            state.currentCluster = null;
            state.currentViewLevel = 'block';
            if (state.blockFeature) {
                renderActiveMetricsByGroup(state.blockFeature.properties);
                initBlockMiniMap(state.blockFeature);
            }
        }
        updateBlockClusterDropdown(state.currentBlock);
    }
}

// Load an intervention's variable config and recalculate feasibility. `name`
// is the effective intervention (a sub-category when one is selected).
async function applyIntervention(name) {
    try {
        const response = await fetch(`/api/intervention/${encodeURIComponent(name)}/config`);
        const data = await response.json();

        // At GP level, filter to only variables available in GP data
        if (state.currentLevel === 'gp' && state.gpVariables.length > 0) {
            const gpFields = new Set(state.gpVariables.map(v => v.field));
            data.variables = data.variables.filter(v => gpFields.has(v.field));

            // Update GP-level stats (data_min/max/mean) from GP data
            data.variables.forEach(v => {
                const gpVar = state.gpVariables.find(gv => gv.field === v.field);
                if (gpVar) {
                    v.data_min = gpVar.data_min;
                    v.data_max = gpVar.data_max;
                    v.data_mean = gpVar.data_mean;
                }
            });
        }

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

