let aiLocationMap = null;

function closeAIModal() {
    document.getElementById('ai-modal').style.display = 'none';
    // Destroy the map when closing
    if (aiLocationMap) {
        aiLocationMap.remove();
        aiLocationMap = null;
    }
}

function initAILocationMap() {
    // Destroy existing map
    if (aiLocationMap) {
        aiLocationMap.remove();
        aiLocationMap = null;
    }

    const mapContainer = document.getElementById('ai-location-map');
    if (!mapContainer || !currentBlockFeature) return;

    // Create map
    aiLocationMap = L.map('ai-location-map', {
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
    });

    // Add tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
    }).addTo(aiLocationMap);

    // Use the stored feature
    const blockLayer = L.geoJSON(currentBlockFeature, {
        style: {
            fillColor: '#0297A6',
            color: '#28537D',
            weight: 2,
            fillOpacity: 0.4,
        }
    }).addTo(aiLocationMap);

    aiLocationMap.fitBounds(blockLayer.getBounds(), { padding: [10, 10] });
}

function toggleRetrievedContext() {
    const body = document.getElementById('ai-context-body');
    const icon = document.getElementById('context-toggle-icon');
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

function copyAIRecommendation() {
    const modalBody = document.getElementById('ai-modal-body');
    const btn = document.getElementById('ai-copy-btn');

    // Get text content from the modal
    const header = modalBody.querySelector('.ai-recommendation-header');
    const content = modalBody.querySelector('.ai-text');

    let textToCopy = '';

    if (header) {
        const title = header.querySelector('h3');
        const meta = header.querySelectorAll('.ai-meta span');
        if (title) textToCopy += title.textContent + '\n';
        meta.forEach(m => textToCopy += m.textContent + '\n');
        textToCopy += '\n';
    }

    if (content) {
        // Get clean text without HTML tags
        textToCopy += content.innerText;
    }

    // Copy to clipboard
    navigator.clipboard.writeText(textToCopy).then(() => {
        // Show success feedback
        btn.classList.add('copied');
        btn.innerHTML = '<i class="bi bi-check"></i>';

        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<i class="bi bi-clipboard"></i>';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

function downloadAIRecommendation() {
    const modalBody = document.getElementById('ai-modal-body');
    const footer = document.getElementById('ai-modal-footer');

    // Get content
    const header = modalBody.querySelector('.ai-recommendation-header');
    const content = modalBody.querySelector('.ai-text');
    const table = modalBody.querySelector('.metrics-table');

    let title = 'Recommendations';
    let blockName = '';
    let intervention = '';
    let feasibility = '';

    if (header) {
        const h3 = header.querySelector('h3');
        if (h3) {
            title = h3.textContent;
            blockName = h3.textContent;
        }
        const metaSpans = header.querySelectorAll('.ai-meta span');
        metaSpans.forEach(span => {
            if (span.classList.contains('ai-intervention')) {
                intervention = span.textContent.trim();
            } else if (span.classList.contains('ai-feasibility')) {
                feasibility = span.textContent.trim();
            }
        });
    }

    // Get sources
    let sourcesHtml = '';
    const sourceItems = footer?.querySelectorAll('.source-item');
    if (sourceItems && sourceItems.length > 0) {
        sourcesHtml = '<h2>Reference Documents</h2><ul>';
        sourceItems.forEach(item => {
            const name = item.querySelector('.source-name')?.textContent || '';
            const num = item.querySelector('.source-number')?.textContent || '';
            sourcesHtml += `<li>${num} ${name}</li>`;
        });
        sourcesHtml += '</ul>';
    }

    // Create printable HTML
    const printContent = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>${title} - LEAF DSS</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; font-size: 11px; line-height: 1.6; }
                h1 { color: #28537D; font-size: 16px; border-bottom: 2px solid #0297A6; padding-bottom: 10px; margin-bottom: 5px; }
                h2 { color: #0297A6; font-size: 13px; margin-top: 20px; border-left: 3px solid #0297A6; padding-left: 8px; }
                .header-info { background: #f0fdfa; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
                .header-info p { margin: 3px 0; }
                .header-info strong { color: #28537D; }
                .recommendation { background: #fff; padding: 15px; border: 1px solid #e0e0e0; border-radius: 6px; margin: 15px 0; }
                .recommendation p { margin-bottom: 10px; }
                .ai-section-title { background: #f0fdfa; padding: 8px 12px; border-left: 3px solid #0297A6; margin: 15px 0 10px 0; font-weight: bold; color: #28537D; font-size: 12px; }
                .ai-section-title i { margin-right: 6px; }
                .ai-recommendation-item { display: flex; gap: 8px; margin: 8px 0; padding: 8px 10px; background: #fafafa; border-radius: 6px; border-left: 3px solid #0297A6; }
                .item-number { font-weight: bold; color: #0297A6; min-width: 18px; }
                .item-content { flex: 1; }
                .ai-bullet-item { display: flex; gap: 6px; margin: 4px 0; padding: 4px 10px; }
                .ai-bullet-item .bullet { color: #0297A6; font-weight: bold; }
                .citation { color: #0297A6; font-size: 8px; cursor: default; }
                table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 10px; }
                th { background: #28537D; color: white; padding: 8px; text-align: left; }
                td { padding: 8px; border-bottom: 1px solid #ddd; }
                tr.in-range { border-left: 3px solid #10b981; }
                tr.out-range { border-left: 3px solid #ef4444; }
                .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 9px; }
                .status-badge.pass { background: #d1fae5; color: #059669; }
                .status-badge.fail { background: #fee2e2; color: #dc2626; }
                ul { padding-left: 20px; }
                li { margin: 5px 0; }
                .footer { margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; font-size: 9px; color: #666; }
                @media print {
                    body { padding: 20px; }
                }
            </style>
        </head>
        <body>
            <h1>LEAF DSS - Recommendations Report</h1>
            <div class="header-info">
                <p><strong>Location:</strong> ${blockName}</p>
                <p><strong>Intervention:</strong> ${intervention}</p>
                <p><strong>${feasibility}</strong></p>
                <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
            </div>

            <h2>Recommendations</h2>
            <div class="recommendation">
                ${content ? content.innerHTML : '<p>No recommendation available</p>'}
            </div>

            ${table ? '<h2>Indicators Analyzed</h2>' + table.outerHTML : ''}

            ${sourcesHtml}

            <div class="footer">
                <p><strong>LEAF DSS</strong> - Landscape Evaluation & Assessment Framework</p>
                <p>IWMI - International Water Management Institute</p>
                <p>This report was generated using AI-powered analysis based on official policy documents.</p>
            </div>
        </body>
        </html>
    `;

    // Open print dialog (user can save as PDF)
    const printWindow = window.open('', '_blank');
    printWindow.document.write(printContent);
    printWindow.document.close();
    setTimeout(() => printWindow.print(), 300);
}

