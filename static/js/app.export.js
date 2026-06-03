
// =============================================================================
// Export
// =============================================================================

async function exportCSV() {
    try {
        const response = await fetch('/api/export/csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                intervention: state.currentIntervention,
                filters: state.currentFilters,
            }),
        });

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'leaf_data.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

    } catch (error) {
        console.error('Error exporting CSV:', error);
        alert('Error exporting data');
    }
}
