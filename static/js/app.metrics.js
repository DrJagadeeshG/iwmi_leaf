function escapeText(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function renderActiveMetricsByGroup(props) {
    // Group icons mapping
    const groupIcons = {
        'Land & Agri': 'bi-flower2',
        'Water': 'bi-droplet',
        'Infrastructure': 'bi-building',
        'Livestock': 'bi-piggy-bank',
        'People': 'bi-people',
        'MMUA Scheme': 'bi-clipboard-data',
        'Soil': 'bi-globe',
        'Climate': 'bi-cloud-sun',
        'Other': 'bi-grid'
    };

    // Container IDs mapping. Soil/Climate/Other have their own cards so
    // Configure-added variables in those groups actually show up (they were
    // silently skipped before — groups without a card never rendered).
    const groupContainers = {
        'Land & Agri': 'land-agri-metrics',
        'Water': 'water-metrics',
        'Infrastructure': 'infrastructure-metrics',
        'Livestock': 'livestock-metrics',
        'People': 'people-metrics',
        'MMUA Scheme': 'mmua-metrics',
        'Soil': 'soil-metrics',
        'Climate': 'climate-metrics',
        'Other': 'other-metrics'
    };

    // Count IDs mapping
    const groupCounts = {
        'Land & Agri': 'count-land-agri',
        'Water': 'count-water',
        'Infrastructure': 'count-infrastructure',
        'Livestock': 'count-livestock',
        'People': 'count-people',
        'MMUA Scheme': 'count-mmua',
        'Soil': 'count-soil',
        'Climate': 'count-climate',
        'Other': 'count-other'
    };

    // Clear all containers and counts first
    Object.keys(groupContainers).forEach(group => {
        const container = document.getElementById(groupContainers[group]);
        const countEl = document.getElementById(groupCounts[group]);
        if (container) {
            container.innerHTML = '';
            container.closest('.detail-card').style.display = 'none';
        }
        if (countEl) {
            countEl.innerHTML = '';
        }
    });

    let totalOutsideCount = 0;
    let totalRenderedCount = 0;

    // If no filters, show all available data from the block
    if (!state.currentFilters || state.currentFilters.length === 0) {
        renderAllBlockMetrics(props, groupContainers);
        return { outside: totalOutsideCount, rendered: totalRenderedCount };
    }

    // Group active filters by their group
    const groupedFilters = {};
    state.currentFilters.forEach(f => {
        const group = f.group || 'Other';
        if (!groupedFilters[group]) {
            groupedFilters[group] = [];
        }
        groupedFilters[group].push(f);
    });

    // Render each group
    Object.entries(groupedFilters).forEach(([group, filters]) => {
        const containerId = groupContainers[group];
        const countId = groupCounts[group];
        if (!containerId) return;

        const container = document.getElementById(containerId);
        const countEl = document.getElementById(countId);
        if (!container) return;

        // Show the card
        container.closest('.detail-card').style.display = 'block';

        // Build metrics
        const metrics = filters.map(f => ({
            key: f.column,
            label: f.label,
            unit: '',
            icon: groupIcons[group] || 'bi-check-circle',
            min: f.min_val,
            max: f.max_val
        }));

        const { outside, total } = renderMetricItemsWithStatus(container, props, metrics);
        totalOutsideCount += outside;
        totalRenderedCount += total;

        // Update count in header
        if (countEl && outside > 0) {
            countEl.innerHTML = `${outside} outside range`;
        }
    });

    // rendered = variables that actually have data for this scope. The
    // feasibility summary uses it as denominator so its % matches the
    // backend feasibility score (which excludes no-data variables).
    return { outside: totalOutsideCount, rendered: totalRenderedCount };
}

// Render all available block metrics when no filters applied
function renderAllBlockMetrics(props, groupContainers) {
    // Define which fields belong to which group
    const fieldGroups = {
        'Land & Agri': ['A', 'AD', 'AE', 'AF', 'AG', 'AH', 'AI', 'AJ', 'AK', 'AL', 'AM', 'J'],
        'Water': ['B', 'C', 'D', 'E', 'BC', 'BD', 'AU'],
        'Infrastructure': ['G', 'H', 'I', 'K', 'L', 'S', 'T', 'U', 'V', 'W', 'X'],
        'Livestock': ['BF', 'BG', 'M', 'N', 'O', 'P', 'Q', 'R'],
        'People': ['Y', 'Z', 'AA', 'AB', 'AC', 'F'],
        // LEAF-68: MMUA livelihood-activity participation (BYp..CEp) + Mahila
        // Kisan scheme metrics (CSp, CTp, DFp). Faiz's new backdata variable,
        // once added with its own field code, is appended to this list.
        'MMUA Scheme': ['BYp', 'BZp', 'CAp', 'CBp', 'CCp', 'CDp', 'CEp', 'CSp', 'CTp', 'DFp']
    };

    // Show each group with its data
    Object.entries(fieldGroups).forEach(([group, fields]) => {
        const containerId = groupContainers[group];
        if (!containerId) return;

        const container = document.getElementById(containerId);
        if (!container) return;

        let rowsHtml = '';
        let hasData = false;

        fields.forEach(field => {
            const value = props[field];
            if (value !== null && value !== undefined && value !== '') {
                hasData = true;
                const numVal = typeof value === 'number' ? value : parseFloat(value);
                const displayValue = isNaN(numVal) ? value : numVal.toFixed(2);
                const fTip = escAttr(buildInfotip({ field: field, group: group }));
                rowsHtml += `
                    <div class="metric-row">
                        <span class="metric-label" data-infotip="${fTip}">${field}</span>
                        <span class="metric-value">${displayValue}</span>
                    </div>
                `;
            }
        });

        if (hasData) {
            container.innerHTML = wrapInScrollStructure(rowsHtml);
            container.closest('.detail-card').style.display = 'block';
            setTimeout(() => initScrollSync(container), 0);
        } else {
            // No data for this group: leave the card hidden instead of
            // rendering an empty "No data available" box.
            container.innerHTML = '';
        }
    });
}

// Helper to wrap content in scroll structure
function wrapInScrollStructure(html) {
    // Generate unique ID for syncing scrolls
    const scrollId = 'scroll-' + Math.random().toString(36).substr(2, 9);
    return `
        <div class="metrics-scroll-wrapper" id="${scrollId}-v">
            <div class="metrics-content" id="${scrollId}-content">
                ${html}
            </div>
        </div>
        <div class="metrics-h-scroll" id="${scrollId}-h">
            <div class="scroll-spacer" id="${scrollId}-spacer"></div>
        </div>
    `;
}

// Sync horizontal scrollbar with content (call after rendering)
function initScrollSync(container) {
    const wrapper = container.querySelector('.metrics-scroll-wrapper');
    const content = container.querySelector('.metrics-content');
    const hScroll = container.querySelector('.metrics-h-scroll');
    const spacer = container.querySelector('.scroll-spacer');

    if (!wrapper || !content || !hScroll || !spacer) return;

    // Check if content overflows horizontally
    const contentWidth = content.scrollWidth;
    const wrapperWidth = wrapper.clientWidth;
    const hasOverflow = contentWidth > wrapperWidth + 5; // 5px tolerance

    if (hasOverflow) {
        // Show scrollbar and set up sync
        hScroll.classList.add('visible');
        wrapper.classList.remove('no-h-scroll');
        spacer.style.width = contentWidth + 'px';

        // Sync scrolls
        wrapper.addEventListener('scroll', () => {
            hScroll.scrollLeft = wrapper.scrollLeft;
        });

        hScroll.addEventListener('scroll', () => {
            wrapper.scrollLeft = hScroll.scrollLeft;
        });

        // Enable horizontal scroll on wrapper (hidden scrollbar)
        wrapper.style.overflowX = 'scroll';
        wrapper.style.scrollbarWidth = 'none';
        wrapper.style.msOverflowStyle = 'none';
    } else {
        // No overflow - hide scrollbar
        hScroll.classList.remove('visible');
        wrapper.classList.add('no-h-scroll');
        wrapper.style.overflowX = 'hidden';
    }
}

// Returns { outside, total }: out-of-range count and the number of rendered
// (non-empty) metrics, so callers can show "3 (38%) outside range".
function renderMetricItemsWithStatus(container, props, metrics) {
    let rowsHtml = '';
    let outsideCount = 0;
    let renderedCount = 0;

    metrics.forEach(m => {
        const value = props[m.key];

        // Empty variables are not rendered at all - no "N/A" rows. (At block
        // level these were showing as empty boxes; district scale already
        // drops them because aggregation omits valueless fields.)
        if (value === null || value === undefined || value === '') return;

        const numVal = typeof value === 'number' ? value : parseFloat(value);
        if (!Number.isFinite(numVal)) return;

        renderedCount++;
        const displayValue = numVal.toFixed(2);
        let statusClass = '';
        let statusIcon = '';

        // Check if value is within range
        if (m.min !== undefined && m.max !== undefined) {
            if (numVal >= m.min && numVal <= m.max) {
                statusClass = 'metric-pass';
                statusIcon = '<i class="bi bi-check-circle-fill status-icon pass"></i>';
            } else {
                statusClass = 'metric-fail';
                statusIcon = '<i class="bi bi-x-circle-fill status-icon fail"></i>';
                outsideCount++;
            }
        }

        const mTip = escAttr(buildInfotip({
            field: m.key, label: m.label, group: m.group,
            range_min: m.min, range_max: m.max,
        }));

        rowsHtml += `
            <div class="metric-item ${statusClass}">
                <span class="metric-label" data-infotip="${mTip}">
                    <i class="bi ${m.icon}"></i>
                    ${m.label}
                </span>
                <span class="metric-value">${statusIcon}${displayValue}<span class="metric-unit">${m.unit}</span></span>
            </div>
        `;
    });
    if (rowsHtml) {
        container.innerHTML = wrapInScrollStructure(rowsHtml);
        setTimeout(() => initScrollSync(container), 0);
    } else {
        // No renderable metrics in this group: hide the whole card rather
        // than showing an empty box.
        container.innerHTML = '';
        const card = container.closest('.detail-card');
        if (card) card.style.display = 'none';
    }
    return { outside: outsideCount, total: renderedCount };
}

function renderMetricItems(container, props, metrics) {
    let rowsHtml = '';
    metrics.forEach(m => {
        const value = props[m.key];
        let displayValue = 'N/A';
        if (value !== null && value !== undefined && value !== '') {
            displayValue = typeof value === 'number' ? value.toFixed(2) : value;
        }
        const mTip2 = escAttr(buildInfotip({ field: m.key, label: m.label, group: m.group }));
        rowsHtml += `
            <div class="metric-item">
                <span class="metric-label" data-infotip="${mTip2}">
                    <i class="bi ${m.icon}"></i>
                    ${m.label}
                </span>
                <span class="metric-value">${displayValue}<span class="metric-unit">${m.unit}</span></span>
            </div>
        `;
    });
    if (rowsHtml) {
        container.innerHTML = wrapInScrollStructure(rowsHtml);
        setTimeout(() => initScrollSync(container), 0);
    } else {
        container.innerHTML = '<p class="no-data">No data available</p>';
    }
}
