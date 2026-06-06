// =============================================================================
// Download Summary report (LEAF-58): a table-based, print-to-PDF summary for
// the current view (state / district / block / cluster), consistent format.
// =============================================================================

// Capture the current view's map to a PNG dataURL via html2canvas (LEAF-19).
// In detail views the overview #map is display:none (html2canvas renders it
// blank), so capture the visible mini-map instead. allowTaint must stay off:
// a tainted canvas makes toDataURL throw and the report loses its map.
// Returns '' on any failure so the report still renders without the map.
async function captureMapImage() {
    try {
        if (typeof html2canvas === 'undefined') return '';
        const inDetail = state.currentViewLevel && state.currentViewLevel !== 'state';
        const miniEl = document.getElementById('block-mini-map');
        const mapEl = (inDetail && miniEl && miniEl.offsetParent !== null) ? miniEl : document.getElementById('map');
        if (!mapEl || mapEl.offsetParent === null) return '';
        const canvas = await html2canvas(mapEl, { useCORS: true, logging: false });
        return canvas.toDataURL('image/png');
    } catch (e) {
        console.warn('Map capture failed:', e);
        return '';
    }
}

async function downloadSummaryReport() {
    // Busy state on the Summary button - the map capture below takes a second
    // or two and the button looked unresponsive.
    const summaryBtn = document.getElementById('summary-btn');
    const summaryBtnHtml = summaryBtn ? summaryBtn.innerHTML : '';
    if (summaryBtn) {
        summaryBtn.disabled = true;
        summaryBtn.innerHTML = '<span class="btn-spinner"></span> Preparing…';
    }
    try {
    const level = state.currentViewLevel || 'state';
    const intervention = state.currentIntervention || '—';
    const sub = state.currentSubcategory ? ` › ${state.currentSubcategory}` : '';
    const now = new Date().toLocaleString();

    const levelLabel = { state: 'State', district: 'District', block: 'Block', cluster: 'Cluster' }[level] || 'Summary';
    let scopeLabel = 'Assam (all districts)';
    let props = null;
    let bodyHtml = '';

    if (level === 'block') {
        const p = state.blockFeature ? state.blockFeature.properties : {};
        scopeLabel = `${p.Dist_Name || ''} / ${state.currentBlock || ''}`;
        props = p;
    } else if (level === 'district') {
        scopeLabel = `${state.currentDistrict} (all blocks)`;
        props = state.districtAggProps;
    } else if (level === 'cluster' && state.currentCluster) {
        const c = state.currentCluster;
        scopeLabel = `${c.block_name || state.currentBlock || ''} / ${clusterDisplayName(c)}`;
        bodyHtml = buildClusterReportBody(c);
    } else {
        const feats = [];
        if (state.geojsonLayer) state.geojsonLayer.eachLayer(l => feats.push(l.feature));
        props = feats.length ? aggregateBlockProps(feats, 'All districts') : null;
    }

    if (level !== 'cluster') {
        // Group indicators by their group/category, emit a group header + rows +
        // a per-group summary line ("3 of 5 in range") (LEAF-20).
        const filters = state.currentFilters || [];
        const groups = [];
        const groupMap = {};
        filters.forEach(f => {
            const g = f.group || 'Other';
            if (!groupMap[g]) { groupMap[g] = []; groups.push(g); }
            groupMap[g].push(f);
        });
        // Target ranges shown to 1 decimal.
        const fmt1 = v => Number.isFinite(Number(v)) ? Number(v).toFixed(1) : '—';
        // Per-category tallies, reused for the category-wise summary table.
        const catSummary = [];
        const rows = groups.map(g => {
            let inCount = 0, total = 0;
            const outLabels = [];
            const groupRows = groupMap[g].map(f => {
                const v = props ? Number(props[f.column]) : NaN;
                const val = Number.isFinite(v) ? v.toFixed(1) : '—';
                const inRange = Number.isFinite(v) && v >= f.min_val && v <= f.max_val;
                if (Number.isFinite(v)) {
                    total++;
                    if (inRange) inCount++; else outLabels.push(f.label || f.column);
                }
                const status = !Number.isFinite(v) ? '—' : (inRange ? 'In range' : 'Out of range');
                const cls = !Number.isFinite(v) ? '' : (inRange ? 'in-range' : 'out-range');
                return `<tr class="${cls}"><td>${escapeText(f.label || f.column)}</td><td>${val}</td><td>${fmt1(f.min_val)}–${fmt1(f.max_val)}</td><td>${status}</td></tr>`;
            }).join('');
            catSummary.push({ group: g, inCount, total, outLabels });
            const groupHeader = `<tr class="group-header"><td colspan="4">${escapeText(g)}</td></tr>`;
            const groupSummary = `<tr class="group-summary"><td colspan="4">${inCount} of ${total} in range</td></tr>`;
            return groupHeader + groupRows + groupSummary;
        }).join('');
        // Category-wise summary: counts plus a plain-language statement per
        // category, naming the indicators that need attention.
        const catStatement = (c) => {
            if (c.total === 0) return 'No data available for this category.';
            if (c.inCount === c.total) return 'All indicators are within the target range — conditions are favourable.';
            const listed = c.outLabels.slice(0, 4).join(', ');
            const more = c.outLabels.length > 4 ? ` and ${c.outLabels.length - 4} more` : '';
            if (c.inCount === 0) return `None of the indicators meet the target range. Key gaps: ${listed}${more}.`;
            return `${c.inCount} of ${c.total} indicators are within range. Needs attention: ${listed}${more}.`;
        };
        const catRows = catSummary.map(c => {
            const pct = c.total > 0 ? Math.round((c.inCount / c.total) * 100) + '%' : '—';
            return `<tr><td>${escapeText(c.group)}</td><td>${c.inCount}/${c.total} (${pct})</td><td>${escapeText(catStatement(c))}</td></tr>`;
        }).join('');
        const catSection = catRows ? `
            <h2>Category-wise summary</h2>
            <table>
                <thead><tr><th>Category</th><th>In range</th><th>Remarks</th></tr></thead>
                <tbody>${catRows}</tbody>
            </table>` : '';
        const feas = props && Number.isFinite(Number(props.feasibility)) ? Number(props.feasibility).toFixed(1) + '%' : 'N/A';
        const aggNote = level === 'district' ? ' Values are averaged across all blocks in the district.'
            : level === 'state' ? ' Values are averaged across all blocks in the state.' : '';
        bodyHtml = `
            <p>This summary shows how <strong>${escapeText(scopeLabel)}</strong> performs against the selected
            <strong>${escapeText(intervention)}${escapeText(sub)}</strong> criteria. Overall feasibility is
            <strong>${feas}</strong>.${aggNote} Indicators marked <em>Out of range</em> fall outside the target band and
            point to where conditions are less suitable and may need targeted support.</p>
            ${catSection}
            <table>
                <thead><tr><th>Indicator</th><th>Value</th><th>Target range</th><th>Status</th></tr></thead>
                <tbody>${rows || '<tr><td colspan="4">No indicators selected — pick an intervention to populate this table.</td></tr>'}</tbody>
            </table>`;
    }

    // Capture the overall map and embed it at the top of the report (LEAF-19).
    const mapImg = await captureMapImage();
    const mapSection = mapImg
        ? `<h2>Overall map</h2><img class="map-img" src="${mapImg}" alt="Overall map" />`
        : '';

    const printContent = `
        <!DOCTYPE html><html><head><title>LEAF DSS - ${levelLabel} Summary</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; font-size: 11px; line-height: 1.6; color: #222; }
            h1 { color: #28537D; font-size: 17px; border-bottom: 2px solid #0297A6; padding-bottom: 10px; margin-bottom: 5px; }
            h2 { color: #0297A6; font-size: 13px; margin-top: 22px; border-left: 3px solid #0297A6; padding-left: 8px; }
            .header-info { background: #f0fdfa; padding: 12px; border-radius: 6px; margin: 12px 0 4px; }
            .header-info p { margin: 3px 0; } .header-info strong { color: #28537D; }
            table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10px; }
            th { background: #28537D; color: white; padding: 7px 8px; text-align: left; }
            td { padding: 7px 8px; border-bottom: 1px solid #ddd; }
            tr.in-range { border-left: 3px solid #10b981; } tr.out-range { border-left: 3px solid #ef4444; }
            tr.group-header td { background: #e6f6f5; color: #28537D; font-weight: 700; font-size: 11px; border-bottom: 1px solid #0297A6; }
            tr.group-summary td { background: #fafafa; color: #555; font-style: italic; font-size: 9px; border-bottom: 2px solid #ddd; }
            .map-img { display: block; margin: 10px auto; width: auto; height: auto; max-width: 460px; max-height: 300px; border: 1px solid #ddd; border-radius: 6px; }
            .footer { margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; font-size: 9px; color: #666; }
            @media print { body { padding: 20px; } }
        </style></head><body>
            <h1>LEAF DSS — ${levelLabel} Summary</h1>
            <div class="header-info">
                <p><strong>Scope:</strong> ${escapeText(scopeLabel)}</p>
                <p><strong>Intervention:</strong> ${escapeText(intervention)}${escapeText(sub)}</p>
                <p><strong>Generated:</strong> ${now}</p>
            </div>
            ${mapSection}
            <h2>Summary</h2>
            ${bodyHtml}
            <div class="footer">
                <p><strong>LEAF DSS</strong> — Landscape Evaluation &amp; Assessment Framework</p>
            </div>
        </body></html>`;

    const w = window.open('', '_blank');
    w.document.write(printContent);
    w.document.close();
    setTimeout(() => w.print(), 300);
    } finally {
        if (summaryBtn) {
            summaryBtn.disabled = false;
            summaryBtn.innerHTML = summaryBtnHtml;
        }
    }
}

// Cluster summary body: facts + member-village table (LEAF-58).
function buildClusterReportBody(c) {
    const villages = c.villages || [];
    const memberRows = villages.map(v =>
        `<tr><td>${escapeText(v.vill_name || 'Village')}</td><td>${escapeText(v.gp_name || '')}</td><td>${Number(v.members || 0).toLocaleString()}</td></tr>`).join('');
    const statusTxt = c.finalized ? 'Finalised (published to production tool)' : 'Proposed (not yet published)';
    return `
        <p>This cluster groups <strong>${villages.length}</strong> nearby villages for
        <strong>${escapeText(c.commodity || '')}</strong> with a combined <strong>${Number(c.total_members || 0).toLocaleString()}</strong>
        interested members (max span ${c.max_span_km != null ? c.max_span_km + ' km' : '—'}). Status: <strong>${statusTxt}</strong>.</p>
        <table>
            <thead><tr><th>Total members</th><th>Villages</th><th>Max span</th><th>Status</th></tr></thead>
            <tbody><tr><td>${Number(c.total_members || 0).toLocaleString()}</td><td>${villages.length}</td><td>${c.max_span_km != null ? c.max_span_km + ' km' : '—'}</td><td>${c.finalized ? 'Finalised' : 'Proposed'}</td></tr></tbody>
        </table>
        <h2>Member villages</h2>
        <table>
            <thead><tr><th>Village</th><th>Gram Panchayat</th><th>Members</th></tr></thead>
            <tbody>${memberRows || '<tr><td colspan="3">No villages.</td></tr>'}</tbody>
        </table>
        ${(c.pashu_sakhi || c.block_coordinator) ? `<h2>Assignment</h2><div class="header-info">
            ${c.pashu_sakhi ? `<p><strong>Pashu Sakhi:</strong> ${escapeText(c.pashu_sakhi)}</p>` : ''}
            ${c.block_coordinator ? `<p><strong>Block coordinator:</strong> ${escapeText(c.block_coordinator)}</p>` : ''}
        </div>` : ''}`;
}

async function applyConfig() {
    const form = document.getElementById('config-form');
    const rows = form.querySelectorAll('.config-row');

    state.currentFilters = [];

    rows.forEach(row => {
        const field = row.dataset.field;
        const minInput = row.querySelector('.range-min');
        const maxInput = row.querySelector('.range-max');
        const prefSelect = row.querySelector('.preference-select');

        // For GP mode with checkbox-based config (legacy), only include checked
        const checkbox = row.querySelector('.gp-var-check');
        if (checkbox && !checkbox.checked) return;

        const configVar = state.interventionConfig
            ? state.interventionConfig.variables.find(v => v.field === field)
            : null;
        const gpVar = state.gpVariables
            ? state.gpVariables.find(v => v.field === field)
            : null;
        const labelSource = configVar || gpVar;

        state.currentFilters.push({
            column: field,
            min_val: parseFloat(minInput.value),
            max_val: parseFloat(maxInput.value),
            weight: 1,
            label: labelSource ? labelSource.label : field,
            group: labelSource ? (labelSource.group || 'Other') : 'Other',
            preference: prefSelect ? prefSelect.value : 'moderate',
        });
    });

    closeConfigModal();
    await calculateFeasibility();
    // Configure changes must reach the open district/block/GP view too — the
    // recalculation above only refreshes the (hidden) state-level map.
    rerenderActiveDetailView();
}

