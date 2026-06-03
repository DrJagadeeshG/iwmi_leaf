// =============================================================================
// Statistics & Charts
// =============================================================================

function updateStatistics(stats) {
    // Update chart
    updateChart(stats.distribution);
}

function updateChart(distribution) {
    const ctx = document.getElementById('distribution-chart').getContext('2d');

    const categories = [
        { label: '100%', name: 'Very High', color: FEASIBILITY_COLORS.very_high },
        { label: '75-100%', name: 'High', color: FEASIBILITY_COLORS.high },
        { label: '50-75%', name: 'Mod-High', color: FEASIBILITY_COLORS.moderate_high },
        { label: '25-50%', name: 'Moderate', color: FEASIBILITY_COLORS.moderate },
        { label: '1-25%', name: 'Low', color: FEASIBILITY_COLORS.low },
        { label: '0%', name: 'Very Low', color: FEASIBILITY_COLORS.very_low },
        { label: 'No Data', name: 'No Data', color: FEASIBILITY_COLORS.no_data },
    ];

    const data = categories.map(cat => distribution[cat.label] || 0);
    const total = data.reduce((a, b) => a + b, 0);

    if (state.chart) {
        state.chart.destroy();
    }

    state.chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: categories.map(c => c.label),
            datasets: [{
                data: data,
                backgroundColor: categories.map(c => c.color),
                borderWidth: 1,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
            },
        },
    });

    // Update legend table
    const legendContainer = document.getElementById('chart-legend');
    const rows = categories.map((cat, i) => {
        const count = data[i];
        return `
            <tr>
                <td><span class="legend-color" style="background: ${cat.color};"></span></td>
                <td>${cat.name}</td>
                <td>${cat.label}</td>
                <td class="text-right">${count}</td>
            </tr>
        `;
    }).join('');

    legendContainer.innerHTML = `
        <table class="legend-table">
            <thead>
                <tr>
                    <th></th>
                    <th>Category</th>
                    <th>Range</th>
                    <th class="text-right">Count</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Update map legend with percentages
    const mapLegend = document.getElementById('map-legend');
    mapLegend.innerHTML = categories.map((cat, i) => {
        const count = data[i];
        const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0.0';
        return `
            <div class="legend-item">
                <span class="legend-color" style="background: ${cat.color};"></span>
                <span>${pct}%</span>
            </div>
        `;
    }).join('');
}

