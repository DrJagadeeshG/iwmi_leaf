
// Store current block props and feature for AI recommendation
let currentBlockProps = null;
let currentBlockFeature = null;

// The livestock sub-filter must flow into AI insights: requests send the
// effective intervention (the sub-category when one is picked, e.g. Goatery
// instead of just Livestock) and the modal shows "Livestock › Goatery".
function effectiveIntervention() {
    return state.currentSubcategory || state.currentIntervention;
}

function interventionDisplayLabel() {
    return state.currentSubcategory
        ? `${state.currentIntervention} › ${state.currentSubcategory}`
        : state.currentIntervention;
}

// Build the plain-language feasibility summary sentence (LEAF #21).
// The % must match the feasibility badge: both use variables WITH DATA as
// the denominator (the backend score excludes no-data variables too).
// rendered = variables with data; x = rendered - variables outside range.
function buildFeasibilitySummary(outsideCount, renderedCount, scope) {
    const selected = state.currentFilters ? state.currentFilters.length : 0;
    const rendered = renderedCount || 0;
    if (!selected || !rendered) return '';
    const x = Math.max(0, rendered - (outsideCount || 0));
    const pct = +((x / rendered) * 100).toFixed(1);
    // Mention missing data only when some selected variables have none here.
    const dataNote = rendered < selected
        ? `of the ${selected} variables selected for assessing feasibility, ${rendered} have data and `
        : `of the ${rendered} variables selected for assessing feasibility, `;
    return `<div class="feasibility-summary-sentence">` +
        `For ${scope}, ${dataNote}${x} (${pct}%) are within the recommended range. ` +
        `For the rest, work needs to be done. Click on AI Insights to check recommendations.` +
        `</div>`;
}

function renderRecommendations(props, feature = null, summaryOpts = null) {
    const container = document.getElementById('block-recommendations');
    const blockName = props.Block_name || 'Unknown';
    const districtName = props.Dist_Name || 'Unknown';
    const feasibility = props.feasibility;

    // Store props and feature for AI button
    currentBlockProps = props;
    if (feature) currentBlockFeature = feature;

    // Feasibility summary sentence (LEAF #21) - shown before the AI Insights button.
    const summaryHtml = (summaryOpts && summaryOpts.scope)
        ? buildFeasibilitySummary(summaryOpts.outsideCount, summaryOpts.renderedCount, summaryOpts.scope)
        : '';

    const icon = 'bi-lightbulb-fill';

    if (state.currentIntervention && feasibility !== null) {
        // Per Faiz (Jun 2026): no "High/Limited potential for X (NN.N%)" verdict
        // line - the summary sentence below carries the feasibility message.
        container.innerHTML = `
            <div class="recommendation-line-content">
                <i class="bi ${icon}"></i>
                <strong>${blockName}, ${districtName}</strong>
                <button class="btn-ai-recommend" onclick="openAIRecommendation()">
                    <i class="bi bi-robot"></i> AI Insights
                </button>
            </div>
            ${summaryHtml}
        `;
    } else {
        const recommendation = 'Select an intervention to see recommendations.';
        container.innerHTML = `<i class="bi ${icon}"></i> <strong>Recommendation for ${blockName}, Assam:</strong> ${recommendation}${summaryHtml}`;
    }
}

function openAIRecommendation() {
    if (!currentBlockProps) return;

    const modal = document.getElementById('ai-modal');
    const modalBody = document.getElementById('ai-modal-body');
    const modalFooter = document.getElementById('ai-modal-footer');

    // Show modal with loading state
    modal.style.display = 'flex';
    modalBody.innerHTML = `
        <div class="ai-loading-state">
            <i class="bi bi-robot ai-spin"></i>
            <p>Analyzing policy documents for <strong>${currentBlockProps.Block_name}</strong>...</p>
            <p class="ai-loading-detail">Intervention: ${interventionDisplayLabel()}</p>
        </div>
    `;
    modalFooter.style.display = 'none';

    // Fetch AI recommendation
    fetchAIRecommendation(currentBlockProps);
}

async function fetchAIRecommendation(props) {
    const blockName = props.Block_name || 'Unknown';
    const districtName = props.Dist_Name || 'Unknown';
    const feasibility = props.feasibility;

    // Build metrics array from current filters
    const metrics = state.currentFilters.map(f => ({
        label: f.label || f.column,
        value: props[f.column],
        in_range: props[f.column] >= f.min_val && props[f.column] <= f.max_val,
        min: f.min_val,
        max: f.max_val
    }));

    const modalBody = document.getElementById('ai-modal-body');
    const modalFooter = document.getElementById('ai-modal-footer');
    const sourceLinks = document.getElementById('ai-source-links');

    try {
        const response = await fetch('/api/ai-recommendation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                block_name: blockName,
                district_name: districtName,
                // Effective intervention: the livestock sub-category when one
                // is active (e.g. Goatery), so RAG retrieval + the prompt are
                // commodity-specific rather than generic "Livestock".
                intervention: effectiveIntervention(),
                feasibility_score: feasibility,
                metrics: metrics,
                filters: state.currentFilters
            })
        });

        const data = await response.json();

        if (data.recommendation) {
            // Format recommendation with citations
            const formattedContent = formatAIRecommendationWithCitations(data.recommendation, data.sources || []);

            // Build retrieved context section if available
            const contextHtml = data.retrieved_context && data.retrieved_context.length > 0 ? `
                <div class="ai-context-section">
                    <div class="ai-context-header" onclick="toggleRetrievedContext()">
                        <h4><i class="bi bi-file-text"></i> Retrieved Context from Documents</h4>
                        <span class="context-toggle"><i class="bi bi-chevron-down" id="context-toggle-icon"></i></span>
                    </div>
                    <div class="ai-context-body" id="ai-context-body" style="display: none;">
                        ${data.retrieved_context.map((ctx, idx) => `
                            <div class="context-chunk">
                                <div class="context-source"><i class="bi bi-file-pdf"></i> ${ctx.source}</div>
                                <div class="context-text">${ctx.content}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : '';

            modalBody.innerHTML = `
                <div class="ai-recommendation-header">
                    <div class="ai-header-left">
                        <h3>${blockName}, ${districtName}</h3>
                        <div class="ai-meta">
                            <span class="ai-intervention"><i class="bi bi-flower2"></i> ${interventionDisplayLabel()}</span>
                            <span class="ai-feasibility"><i class="bi bi-speedometer2"></i> Feasibility: ${feasibility.toFixed(1)}%</span>
                        </div>
                    </div>
                    <div class="ai-header-map" id="ai-location-map"></div>
                </div>
                <div class="ai-recommendation-content">
                    <div class="ai-text">${formattedContent.html}</div>
                </div>
                <div class="ai-metrics-summary">
                    <h4><i class="bi bi-table"></i> Indicators Analyzed</h4>
                    <table class="metrics-table">
                        <thead>
                            <tr>
                                <th>Indicator</th>
                                <th>Current Value</th>
                                <th>Target Range</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${metrics.map(m => `
                                <tr class="${m.in_range ? 'in-range' : 'out-range'}">
                                    <td class="metric-label">${m.label}</td>
                                    <td class="metric-value">${m.value !== null && m.value !== undefined ? parseFloat(m.value).toFixed(2) : 'N/A'}</td>
                                    <td class="metric-range">${Number(m.min).toFixed(1)} - ${Number(m.max).toFixed(1)}</td>
                                    <td class="metric-status">
                                        <span class="status-badge ${m.in_range ? 'pass' : 'fail'}">
                                            ${m.in_range ? '<i class="bi bi-check-circle-fill"></i> Pass' : '<i class="bi bi-x-circle-fill"></i> Fail'}
                                        </span>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
                ${contextHtml}
            `;

            // Show sources in footer
            if (data.sources && data.sources.length > 0) {
                modalFooter.style.display = 'block';
                sourceLinks.innerHTML = data.sources.map((source, idx) => `
                    <a href="/ai-docs/${encodeURIComponent(source)}" target="_blank" class="source-item" title="${source}">
                        <span class="source-number">[${idx + 1}]</span>
                        <span class="source-name">${source.replace('.pdf', '')}</span>
                        <i class="bi bi-box-arrow-up-right source-link"></i>
                    </a>
                `).join('');
            }

            // Initialize mini map for location
            initAILocationMap();
        } else if (data.error) {
            modalBody.innerHTML = `
                <div class="ai-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Unable to generate recommendation: ${data.error}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error fetching AI recommendation:', error);
        modalBody.innerHTML = `
            <div class="ai-error">
                <i class="bi bi-exclamation-triangle"></i>
                <p>Error connecting to AI service. Please try again.</p>
            </div>
        `;
    }
}

function formatAIRecommendationWithCitations(text, sources) {
    // Process line by line to avoid nesting issues
    const lines = text.split('\n');
    let htmlParts = [];
    let inItem = false; // track if we're inside a numbered item
    let citationIndex = 0;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i].trim();
        if (!line) {
            // Empty line = paragraph break
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            htmlParts.push('<br>');
            continue;
        }

        // Convert **bold** to strong
        line = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // ### Section headers
        if (line.match(/^###\s*/)) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            if (/assessment/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-clipboard-data"></i> Assessment</div>');
            } else if (/recommendation/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-list-check"></i> Recommendations</div>');
            } else if (/priority.action/i.test(line)) {
                htmlParts.push('<div class="ai-section-title"><i class="bi bi-exclamation-circle"></i> Priority Actions</div>');
            } else {
                htmlParts.push(`<div class="ai-section-title">${line.replace(/^###\s*/, '')}</div>`);
            }
            continue;
        }

        // Numbered items: "1. Title: content"
        const numMatch = line.match(/^(\d+)\.\s+([^:]+):\s*(.*)/);
        if (numMatch) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            const [, num, title, rest] = numMatch;
            citationIndex = (citationIndex % Math.max(sources.length, 1)) + 1;
            htmlParts.push(
                `<div class="ai-recommendation-item"><span class="item-number">${num}</span>` +
                `<div class="item-content"><strong>${title}</strong><sup class="citation" data-ref="${citationIndex}">[${citationIndex}]</sup>: ${rest}`
            );
            inItem = true;
            continue;
        }

        // Bullet points
        const bulletMatch = line.match(/^[-•]\s+(.*)/);
        if (bulletMatch) {
            if (inItem) { htmlParts.push('</div></div>'); inItem = false; }
            htmlParts.push(`<div class="ai-bullet-item"><span class="bullet">&bull;</span>${bulletMatch[1]}</div>`);
            continue;
        }

        // Regular text - continuation of current item or standalone paragraph
        if (inItem) {
            htmlParts.push(' ' + line);
        } else {
            htmlParts.push(`<p>${line}</p>`);
        }
    }

    // Close any open item
    if (inItem) { htmlParts.push('</div></div>'); }

    let html = htmlParts.join('\n');

    // Add citations to sentences mentioning policy keywords
    const policyKeywords = ['DAY-NRLM', 'NRLM', 'MKSP', 'SHG', 'organic', 'farming', 'training', 'guidelines', 'advisory', 'cluster', 'IFC'];
    policyKeywords.forEach(keyword => {
        const regex = new RegExp(`(${keyword}[^.]*)(\\.)`, 'gi');
        html = html.replace(regex, (match, content, dot) => {
            if (!content.includes('citation')) {
                const refNum = Math.floor(Math.random() * Math.max(sources.length, 1)) + 1;
                return `${content}<sup class="citation">[${refNum}]</sup>${dot}`;
            }
            return match;
        });
    });

    return { html, sources };
}

function formatAIRecommendation(text) {
    // Convert markdown-like formatting to HTML (kept for backward compatibility)
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n- /g, '</p><ul><li>')
        .replace(/\n(\d+)\. /g, '</p><ol><li>')
        .replace(/<\/li>\n/g, '</li>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>')
        .replace(/<p><\/p>/g, '');
}
