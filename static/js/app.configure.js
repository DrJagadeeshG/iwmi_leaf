// =============================================================================
// Configuration Modal
// =============================================================================

async function openConfigModal() {
    if (!state.interventionConfig) {
        alert('Please select an intervention first');
        return;
    }

    const modal = document.getElementById('config-modal');
    const title = document.getElementById('modal-title');
    const form = document.getElementById('config-form');

    // #15: when a Livestock (or other) sub-category is active, show the parent
    // and sub-type in the title so it's clear which variable set is being
    // configured. The sub-type's variable set is already loaded via
    // applyIntervention, so no backend change is needed here.
    if (state.currentSubcategory && state.currentIntervention) {
        title.textContent = `Configure ${state.currentIntervention} › ${state.currentSubcategory}`;
    } else {
        title.textContent = `Configure ${state.interventionConfig.name}`;
    }

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
                    <th><i class="bi bi-trash"></i></th>
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
            <td class="config-delete-cell">
                <button type="button" class="config-delete-btn" title="Remove variable"
                    onclick="deleteVariable('${v.field}')">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        </tr>
    `;
}

// #12: remove a variable from the active config. Drops it from
// state.interventionConfig.variables and the DOM, re-numbers the remaining
// rows, and returns the variable to the add-variable list so it can be
// re-added later.
function deleteVariable(field) {
    if (!state.interventionConfig) return;

    const removed = state.interventionConfig.variables.find(v => v.field === field);
    state.interventionConfig.variables = state.interventionConfig.variables
        .filter(v => v.field !== field);

    const form = document.getElementById('config-form');
    if (form) {
        const row = form.querySelector(`.config-row[data-field="${field}"]`);
        if (row) row.remove();

        // Re-render S.No indices on the remaining rows.
        form.querySelectorAll('.config-row').forEach((r, i) => {
            const snoCell = r.querySelector('.config-sno-cell');
            if (snoCell) snoCell.textContent = i + 1;
        });
    }

    // Return the variable to the add-list so it can be added back.
    if (removed && Array.isArray(state.availableVariables)
        && !state.availableVariables.some(v => v.field === field)) {
        state.availableVariables.push(removed);
    }
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

        // #14: order by category (group) then label so the list reads in
        // grouped sections, mirroring the GP-config grouping.
        availableVars.sort((a, b) => {
            const ga = (a.group || 'Other');
            const gb = (b.group || 'Other');
            if (ga !== gb) return ga.localeCompare(gb);
            return (a.label || '').localeCompare(b.label || '');
        });

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

    // #13: dropped the raw "Code" column — keep Label + Category only.
    const header = `
        <div class="variable-list-header">
            <span>Label</span>
            <span>Category</span>
            <span></span>
        </div>
    `;

    // #14: render grouped by category with a section header per group. Input is
    // already sorted by group then label, so emit a header whenever the group
    // changes.
    let rows = '';
    let lastGroup = null;
    variables.forEach(v => {
        const group = v.group || 'Other';
        if (group !== lastGroup) {
            rows += `<div class="variable-group-header">${group}</div>`;
            lastGroup = group;
        }
        const vTip = escAttr(buildInfotip({
            field: v.field, label: v.label, description: v.description,
            group: v.group, data_min: v.data_min, data_max: v.data_max, data_mean: v.data_mean,
        }));
        rows += `
        <div class="variable-item" data-field="${v.field}" data-infotip="${vTip}" data-infotip-pos="below">
            <div class="variable-item-label">${v.label}</div>
            <div class="variable-item-group">${group}</div>
            <button class="variable-item-add" onclick="addVariable('${v.field}')">
                <i class="bi bi-plus"></i> Add
            </button>
        </div>
    `;
    });

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

