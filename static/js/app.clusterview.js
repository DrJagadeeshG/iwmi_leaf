// =============================================================================
// Block -> Cluster drill-down view  (cluster_view_spec.md)
// =============================================================================
//
// A new "Cluster" dropdown in the top filter bar (#filterbar-cluster-select),
// sitting between Sub-category and Configure, drives a three-state machine on
// the block detail view:
//
//   State 1  Sub-category = "All Livestock" (or intervention != Livestock)
//            -> dropdown hidden/disabled; map shows the plain block boundary;
//               ribbon + variable cards are the normal block view.
//   State 2  A specific activity (Goatery/Dairy/...) is selected
//            -> dropdown ACTIVE, defaulting to "All clusters"; the block
//               mini-map immediately switches to the clusters overlay (village
//               bubbles + radius circles) for that block+commodity. The ribbon
//               and variable cards stay EXACTLY the block view ("info same as
//               before").
//   State 3  A specific cluster is selected (dropdown OR clicking it on the map)
//            -> that cluster is highlighted (dark ring); the ribbon is replaced
//               by 4 stat tiles (Villages / Gram Panchayat / Members / Max span)
//               and the variable cards are replaced by 6 new cluster cards.
//
// The map switches on ACTIVITY selection (state 2); the info panel switches
// only on CLUSTER selection (state 3). These are deliberately separate.
//
// This module supersedes the older LEAF-92 in-header cluster dropdown
// (#block-cluster-select) — see CLUSTERVIEW_ENABLED in app.core.js. It plugs in
// via two hooks: clusterViewSync(blockName) (called from
// updateBlockClusterDropdown) and clusterViewReset() (called on overview).
// =============================================================================

(function () {
    'use strict';

    // Per-commodity bubble colour (mirrors clusters.js COMMODITY_COLOR so the
    // block overlay reads the same as the /clustering page).
    var COMMODITY_COLOR = {
        Dairy: '#5088C6',
        Goatery: '#22AD7A',
        Piggery: '#E86933',
        Backyard_Poultry: '#0297A6',
        Duckery: '#DD9103',
        Fishery_Activity: '#46BBD4',
    };
    var CLUSTER_STROKE = '#00BCD4';        // cyan — fundable clusters
    var PROVISIONAL_STROKE = '#E8833A';    // amber — below-floor review groups
    var SELECTED_STROKE = '#16314d';       // dark ring for the selected cluster

    // Fallback worksheet links for the linked cards (Cards 3/5/6). The cluster
    // record may carry its own `links.{mmua,infrastructure,members}` (populated
    // by ASRLM later); when neither is present the link renders disabled with
    // "Link pending (ASRLM)". Build the plumbing, not the data.
    //
    // INTERIM LINKS (per client request, Jun 2026): until ASRLM supplies
    // per-cluster data, each linked card points to a shared Google Sheet.
    // These are temporary placeholders — swap/clear them when real data lands.
    var DEFAULT_CARD_LINKS = {
        mmua: 'https://docs.google.com/spreadsheets/d/1SzF1Sy0k31_RccOVp9jtPbQTouw0iX_T/edit?usp=drive_link&ouid=115622155937193541879&rtpof=true&sd=true',
        infrastructure: 'https://docs.google.com/spreadsheets/d/1U-7lD9gLSrMW55gG4j17MBsJjNMc9bX5/edit?usp=drive_link&ouid=115622155937193541879&rtpof=true&sd=true',
        members: 'https://docs.google.com/spreadsheets/d/1vHbbzT_CapzZDUKBDmusgLnfEwlgS-_H/edit?usp=drive_link&ouid=115622155937193541879&rtpof=true&sd=true',
    };

    // Module-local state. `state` (global) holds the cross-cutting app state;
    // these are private to the cluster overlay.
    var local = {
        clusters: [],            // clusters for the current block+commodity
        selectedId: null,        // cluster_id of the highlighted cluster, or null
        overlayActive: false,    // true when the cluster overlay is on the map
        clusterLayer: null,      // L.featureGroup of village dots + radius rings
        ringById: {},            // cluster_id -> L.circle (for highlight toggling)
        blockName: null,         // current block (for the MMUA "other activities" fetch)
        blockOther: null,        // block-level "other activities" {label: count} from
                                 // /api/blocks/<block>/shg-summary; {} for fallback
                                 // (June-2) blocks, null until fetched.
        blockConvergence: null,  // {biophysical:[], infrastructure:[]} from
                                 // /api/blocks/<block>/convergence (column-P tags);
                                 // null until fetched.
    };

    // ----- small helpers -------------------------------------------------------

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function clusterLabel(c) {
        // cluster_name is the editable display-name OVERRIDE for cluster_code
        // (2026-06-08); when set it wins everywhere the cluster name shows.
        if (c.cluster_name) return c.cluster_name;
        // cluster_code is the human-readable unique ID (e.g. MO-BH-GO-01,
        // Faiz 2026-06-07); older payloads fall back to the tier label.
        if (c.cluster_code != null) return c.cluster_code;
        if (c.cluster_label != null) return c.cluster_label;
        if (c.cluster_num != null) return String(c.cluster_num);
        return c.cluster_id;
    }

    // Display name: a custom cluster_name or the self-descriptive code is shown
    // as-is; the legacy "1"/"P1" labels still need the "Cluster " prefix.
    function clusterDisplay(c) {
        if (c.cluster_name) return c.cluster_name;
        return c.cluster_code != null ? c.cluster_code : ('Cluster ' + clusterLabel(c));
    }

    function activeCommodity() {
        // Sub-category values are exactly the commodity enum (Dairy, Goatery,
        // Piggery, Backyard_Poultry, Duckery, Fishery_Activity), so they map
        // straight to the /api/clusters commodity param.
        return state.currentSubcategory || null;
    }

    function getDropdown() {
        return document.getElementById('filterbar-cluster-select');
    }

    function getCardLink(cluster, key) {
        var links = (cluster && cluster.links) || {};
        var url = links[key] || DEFAULT_CARD_LINKS[key] || '';
        url = (typeof url === 'string') ? url.trim() : '';
        if (!url) return '';
        // Whitelist http(s) and relative URLs only. The worksheet links are
        // externally/ASRLM-supplied, so reject javascript:/data:/etc. schemes
        // before they reach the anchor href (esc() is HTML-escaping, not URL
        // sanitisation, and would let "javascript:..." through as a live link).
        if (/^https?:\/\//i.test(url)) return url;            // absolute http(s)
        if (/^(\/|\.\/|\.\.\/|[?#])/.test(url)) return url;   // relative / fragment / query
        if (/^[a-z][a-z0-9+.-]*:/i.test(url)) return '';      // any other scheme -> reject
        return url;                                           // bare relative path (no scheme)
    }

    // Fetch the block's "other activities" breakdown (Fodder cultivation / Feed
    // manufacturing / Livestock transport / Meat shop counts) from the SHG
    // summary endpoint and cache it for the MMUA card. The summary's `other`
    // dict is {} for June-2 fallback blocks (village master has no per-activity
    // data) — we keep it as {} so the card can show its empty-state line. On any
    // failure we leave blockOther null (treated identically as "no data yet").
    // If the user has a cluster open when this resolves, re-render its cards so
    // the MMUA card fills in without needing a reselect.
    async function fetchBlockOther(blockName) {
        try {
            var r = await fetch('/api/blocks/' + encodeURIComponent(blockName) + '/shg-summary');
            var s = await r.json();
            // Only adopt if still on the same block (user may have moved on).
            if (local.blockName !== blockName) return;
            local.blockOther = (s && typeof s.other === 'object' && s.other) ? s.other : {};
        } catch (e) {
            if (local.blockName === blockName) local.blockOther = {};
        }
        // Refresh the open cluster's cards so the MMUA card picks up the data.
        if (local.selectedId) {
            var c = local.clusters.find(function (x) {
                return String(x.cluster_id) === String(local.selectedId);
            });
            if (c) renderClusterCards(c);
        }
    }

    // Build the MMUA card body from the cached block "other activities" counts.
    // Empty/absent -> a graceful single line instead of a blank card.
    function mmuaBody() {
        var other = local.blockOther;
        var keys = other ? Object.keys(other) : [];
        if (!keys.length) {
            return '<p class="no-filters">No activity breakdown for this block yet.</p>';
        }
        return keys.map(function (label) {
            return row(esc(label), Number(other[label] || 0).toLocaleString());
        }).join('');
    }

    // 07-Jun: Biophysical / Infrastructure (convergence) cards. The client tags
    // variables in the dss_input sheet's column P; for the cluster's block we
    // show each tagged variable's value. Mirrors fetchBlockOther: fetch once per
    // block, cache, re-render the open cluster when it resolves.
    async function fetchBlockConvergence(blockName) {
        try {
            var r = await fetch('/api/blocks/' + encodeURIComponent(blockName) + '/convergence');
            var s = await r.json();
            if (local.blockName !== blockName) return;   // user moved on
            local.blockConvergence = (s && typeof s === 'object') ? s : {};
        } catch (e) {
            if (local.blockName === blockName) local.blockConvergence = {};
        }
        if (local.selectedId) {
            var c = local.clusters.find(function (x) {
                return String(x.cluster_id) === String(local.selectedId);
            });
            if (c) renderClusterCards(c);
        }
    }

    // Build a convergence card body (kind = 'biophysical' | 'infrastructure')
    // from the cached tags. No tags / not fetched -> graceful empty line.
    function convergenceBody(kind) {
        var conv = local.blockConvergence;
        var items = (conv && Array.isArray(conv[kind])) ? conv[kind] : [];
        if (!items.length) {
            return '<p class="no-filters">No ' + kind + ' variables tagged for this block yet.</p>';
        }
        return items.map(function (it) {
            var v = (it.value === null || it.value === undefined || it.value === '')
                ? '—'
                : (typeof it.value === 'number' ? it.value.toLocaleString() : esc(String(it.value)));
            return row(esc(it.label || it.code || ''), v);
        }).join('');
    }

    // ----- public hooks --------------------------------------------------------

    // Called from updateBlockClusterDropdown() whenever the block, intervention
    // or sub-category changes. Resolves which state we're in and renders it.
    async function clusterViewSync(blockName) {
        var commodity = activeCommodity();

        // State 1: no specific activity -> tear the overlay down, hide dropdown,
        // and make sure the block view (ribbon + cards) is restored.
        if (!commodity || !blockName) {
            clusterViewReset();
            return;
        }

        // Block-level "other activities" feed the MMUA card (Card 3). It's the
        // same for every cluster in this block, so fetch/cache it once per block
        // here rather than per cluster selection. Refetch only when the block
        // changes; a failed/missing fetch leaves blockOther null -> card shows
        // the graceful empty line.
        if (local.blockName !== blockName) {
            local.blockName = blockName;
            local.blockOther = null;
            local.blockConvergence = null;
            fetchBlockOther(blockName);
            fetchBlockConvergence(blockName);
        }

        // Fetch clusters for this block+commodity (smart auto-refresh built in).
        var clusters = [];
        if (typeof setDetailLoader === 'function') setDetailLoader(true);
        try {
            var r = await fetch('/api/clusters?block=' + encodeURIComponent(blockName) +
                '&commodity=' + encodeURIComponent(commodity));
            var data = await r.json();
            clusters = Array.isArray(data) ? data : [];
        } catch (e) {
            clusters = [];
        } finally {
            if (typeof setDetailLoader === 'function') setDetailLoader(false);
        }
        local.clusters = clusters;
        local.selectedId = null;

        // No clusters for this block+commodity -> behave like state 1.
        if (!clusters.length) {
            clusterViewReset();
            return;
        }

        // State 2: populate + enable the dropdown (default "All clusters") and
        // switch the map to the clusters overlay. Ribbon + cards stay as the
        // block view — we explicitly do NOT touch them here.
        populateDropdown(clusters);
        showOverlay();
        restoreBlockInfoPanels();   // ensure stat tiles / cluster cards are hidden
    }

    // Called on overview / leaving the block view. Full teardown.
    function clusterViewReset() {
        // Tear down the Leaflet overlay if it is still attached. removeOverlay()
        // also clears clusterLayer/overlayActive/ringById.
        removeOverlay();
        local.clusters = [];
        local.selectedId = null;
        local.blockName = null;
        local.blockOther = null;
        local.blockConvergence = null;

        // Clear the cross-cutting cluster selection so downstream consumers
        // (e.g. Download Summary in app.reports.js, which branches on
        // state.currentViewLevel === 'cluster' && state.currentCluster) don't see
        // a stale cluster after the intervention / sub-category / block changes
        // out from under us (cluster_view_spec.md reset rule).
        state.currentCluster = null;
        if (state.currentViewLevel === 'cluster') state.currentViewLevel = 'block';

        var grp = document.getElementById('cluster-filter-group');
        if (grp) grp.style.display = 'none';
        var sel = getDropdown();
        if (sel) {
            sel.disabled = true;
            sel.value = '';
            sel.innerHTML = '<option value="">All clusters</option>';
        }
        restoreBlockInfoPanels();
    }

    // ----- dropdown ------------------------------------------------------------

    function populateDropdown(clusters) {
        var grp = document.getElementById('cluster-filter-group');
        var sel = getDropdown();
        if (!sel) return;
        sel.innerHTML = '';
        var all = document.createElement('option');
        all.value = '';
        all.textContent = 'All clusters (' + clusters.length + ')';
        sel.appendChild(all);
        clusters.forEach(function (c) {
            var o = document.createElement('option');
            o.value = c.cluster_id;
            o.textContent = clusterDisplay(c) + ' · ' +
                (c.total_members || 0) + ' members';
            sel.appendChild(o);
        });
        sel.disabled = false;
        sel.value = local.selectedId || '';
        if (grp) grp.style.display = '';
    }

    // Dropdown change handler: '' -> All clusters (state 2); an id -> state 3.
    function handleDropdownChange() {
        var sel = getDropdown();
        if (!sel) return;
        var id = sel.value;
        if (!id) {
            selectCluster(null);
        } else {
            var c = local.clusters.find(function (x) {
                return String(x.cluster_id) === String(id);
            });
            selectCluster(c || null);
        }
    }

    // ----- selection (state 2 <-> state 3) ------------------------------------

    // Select a cluster (state 3) or clear back to All clusters (state 2). Keeps
    // the dropdown + the map highlight + the info panels in sync.
    function selectCluster(cluster) {
        // Clicking the already-selected cluster again returns to All clusters.
        if (cluster && local.selectedId && String(cluster.cluster_id) === String(local.selectedId)) {
            cluster = null;
        }
        local.selectedId = cluster ? cluster.cluster_id : null;
        state.currentCluster = cluster || null;

        var sel = getDropdown();
        if (sel) sel.value = local.selectedId || '';

        highlightRing(local.selectedId);

        if (cluster) {
            state.currentViewLevel = 'cluster';
            renderStatTiles(cluster);
            renderClusterCards(cluster);
        } else {
            // Back to state 2: restore the block ribbon + variable cards.
            state.currentViewLevel = 'block';
            restoreBlockInfoPanels();
        }
    }

    // ----- info panels (ribbon + cards) ---------------------------------------

    // Restore the normal block ribbon + variable cards; hide the cluster tiles
    // and cluster cards. Used in states 1 and 2.
    function restoreBlockInfoPanels() {
        var ribbon = document.getElementById('block-ribbon-row');
        if (ribbon) ribbon.style.display = '';
        var tiles = document.getElementById('cluster-stat-tiles');
        if (tiles) { tiles.style.display = 'none'; tiles.innerHTML = ''; }
        var cards = document.getElementById('clusterview-cards');
        if (cards) { cards.style.display = 'none'; cards.innerHTML = ''; }
        // Show the variable category cards again (setClusterMode(false) toggles
        // the .detail-right > .detail-card group used by the block view).
        if (typeof setClusterMode === 'function') setClusterMode(false);
    }

    // State 3 ribbon: 4 stat tiles from the cluster record. No AI insights.
    function renderStatTiles(c) {
        var ribbon = document.getElementById('block-ribbon-row');
        var tiles = document.getElementById('cluster-stat-tiles');
        if (!tiles) return;
        var villages = c.villages || [];
        // Distinct, non-empty GP names from the member villages.
        var gpNames = [];
        villages.forEach(function (v) {
            var g = (v.gp_name || '').trim();
            if (g && gpNames.indexOf(g) === -1) gpNames.push(g);
        });
        // Match the mock's 1-decimal "8.2 km" (stored value carries up to 3dp).
        var span = (c.max_span_km != null)
            ? (Number(c.max_span_km).toFixed(1) + ' km') : '—';

        // 07-Jun: no "← All clusters" back link - the Cluster dropdown in the
        // filter bar is the way back (pick "All clusters" there).
        tiles.innerHTML =
            // 07-Jun feedback: surface the cluster's ID (cluster_code) in the
            // ribbon when a cluster is selected.
            '<span class="cluster-id-ribbon" data-tooltip="Cluster ID">' +
                '<i class="bi bi-diagram-3"></i> ' + esc(String(clusterDisplay(c))) + '</span>' +
            tile(villages.length, 'Villages') +
            gpTile(gpNames) +
            tile(Number(c.total_members || 0).toLocaleString(), 'Members') +
            tile(esc(span), 'Max span');

        if (ribbon) ribbon.style.display = 'none';
        tiles.style.display = '';
    }

    function tile(value, label) {
        return '<div class="cluster-stat-tile">' +
            '<div class="cluster-stat-value">' + value + '</div>' +
            '<div class="cluster-stat-label">' + label + '</div>' +
            '</div>';
    }

    // 07-Jun feedback: long multi-GP names as the tile's big value blew the
    // ribbon apart. The GP tile is now numeric like its siblings, with the
    // names on one ellipsized sub-line and the full list in a hover tooltip.
    function gpTile(gpNames) {
        var count = gpNames.length;
        var namesText = count ? gpNames.join(', ') : '—';
        return '<div class="cluster-stat-tile" data-tooltip="' + esc(namesText) + '"' +
            ' data-tooltip-wrap data-tooltip-below>' +
            '<div class="cluster-stat-value">' + (count || '—') + '</div>' +
            '<div class="cluster-stat-label">' +
                (count === 1 ? 'Gram Panchayat' : 'Gram Panchayats') + '</div>' +
            '<div class="cluster-stat-sub">' + esc(namesText) + '</div>' +
            '</div>';
    }

    // State 3 cards: the 6 new cluster cards (spec page 4). Replaces the
    // variable category cards.
    function renderClusterCards(c) {
        var cards = document.getElementById('clusterview-cards');
        if (!cards) return;
        var villages = c.villages || [];

        // Card 1 — Village names.
        var villageRows = villages.length
            ? villages.map(function (v) {
                return row(esc(v.vill_name || 'Village'),
                    Number(v.members || 0).toLocaleString() + ' members');
            }).join('')
            : '<p class="no-filters">No villages.</p>';
        var card1 = card('bi-pin-map', 'Village names', villageRows);

        // Card 2 — Contact Persons. DC = district_coordinator, BC =
        // block_coordinator, PS = pashu_sakhi, aggregated (distinct non-empty)
        // from the cluster record. Each shows an em-dash when unset.
        var dcSet = distinctFrom(c, villages, 'district_coordinator');
        var bcSet = distinctFrom(c, villages, 'block_coordinator');
        var psSet = distinctFrom(c, villages, 'pashu_sakhi');
        var contactRows =
            row('DC <small>(District Coordinator)</small>', dcSet.length ? esc(dcSet.join(', ')) : '—') +
            row('BC <small>(Block Coordinator)</small>', bcSet.length ? esc(bcSet.join(', ')) : '—') +
            row('PS <small>(Pashu Sakhi)</small>', psSet.length ? esc(psSet.join(', ')) : '—');
        var card2 = card('bi-person-badge', 'Contact Persons', contactRows);

        // Card 3 — MMUA Supporting activities. Shows the block-level "other
        // activities" counts (Fodder cultivation / Feed manufacturing /
        // Livestock transport / Meat shop) from the SHG summary; same for every
        // cluster in the block. Empty for June-2 fallback blocks -> empty-state
        // line. The worksheet link stays in the header.
        var card3 = linkedCard('bi-shop', 'MMUA Supporting activities',
            mmuaBody(),
            getCardLink(c, 'mmua'));

        // Card 4 — Biophysical. Block values for the variables the client tagged
        // 'Biophysical' in the dss_input sheet's column P (07-Jun feedback).
        var card4 = card('bi-tree', 'Biophysical',
            convergenceBody('biophysical'));

        // Card 5 — Infrastructure / convergence. Block values for the variables
        // tagged 'Infrastructure' in column P; worksheet link kept in the header.
        var card5 = linkedCard('bi-hospital', 'Infrastructure (convergence)',
            convergenceBody('infrastructure'),
            getCardLink(c, 'infrastructure'));

        // Card 6 — Members (linked, pending ASRLM; login gating deferred).
        var card6 = linkedCard('bi-people', 'Members',
            '<div class="metric-row"><span class="metric-label">Total members</span>' +
            '<span class="metric-value">' + Number(c.total_members || 0).toLocaleString() + '</span></div>' +
            '<p class="no-filters">Member detail to be populated by ASRLM.</p>',
            getCardLink(c, 'members'));

        cards.innerHTML = card1 + card2 + card3 + card4 + card5 + card6;
        cards.style.display = '';
        // Hide the variable category cards (block view) while cluster cards show.
        if (typeof setClusterMode === 'function') setClusterMode(true);
        // setClusterMode toggles #cluster-cards too; make sure the LEAF-53
        // container stays hidden so only our 6 cards show.
        var legacyCards = document.getElementById('cluster-cards');
        if (legacyCards) legacyCards.style.display = 'none';
    }

    // Distinct non-empty values for a field, checking both the cluster record
    // and each village (BC/PS may live at either level depending on payload).
    function distinctFrom(cluster, villages, field) {
        var out = [];
        var push = function (val) {
            var s = (val == null ? '' : String(val)).trim();
            if (s && out.indexOf(s) === -1) out.push(s);
        };
        push(cluster[field]);
        (villages || []).forEach(function (v) { push(v[field]); });
        return out;
    }

    function row(label, value) {
        return '<div class="metric-row"><span class="metric-label">' + label +
            '</span><span class="metric-value">' + value + '</span></div>';
    }

    function card(icon, title, bodyHtml) {
        return '<div class="detail-card">' +
            '<div class="detail-card-header"><span><i class="bi ' + icon + '"></i> ' +
                esc(title) + '</span></div>' +
            '<div class="detail-card-body"><div class="metrics-scroll-wrapper">' +
                bodyHtml + '</div></div>' +
            '</div>';
    }

    // A card whose header carries an external-worksheet link. When no URL is
    // configured the link renders disabled with "Link pending (ASRLM)".
    function linkedCard(icon, title, bodyHtml, url) {
        var linkHtml = url
            ? '<a class="cluster-card-link" href="' + esc(url) + '" target="_blank" ' +
                'rel="noopener" data-tooltip="Open the linked worksheet">' +
                '<i class="bi bi-box-arrow-up-right"></i> Worksheet</a>'
            : '<span class="cluster-card-link disabled" data-tooltip="Worksheet link not configured yet">' +
                '<i class="bi bi-box-arrow-up-right"></i> Link pending (ASRLM)</span>';
        return '<div class="detail-card">' +
            '<div class="detail-card-header"><span><i class="bi ' + icon + '"></i> ' +
                esc(title) + '</span>' + linkHtml + '</div>' +
            '<div class="detail-card-body"><div class="metrics-scroll-wrapper">' +
                bodyHtml + '</div></div>' +
            '</div>';
    }

    // ----- map overlay ---------------------------------------------------------

    // Switch the block mini-map to the clusters overlay: village bubbles sized
    // by members + a radius circle per cluster, drawn over the block boundary.
    // Clicking a ring or bubble selects that cluster (state 3).
    function showOverlay() {
        if (!state.blockMiniMap) {
            // Mini-map not ready yet (renderBlockDetail builds it right after);
            // retry shortly so the overlay lands once the map exists.
            setTimeout(function () {
                if (state.blockMiniMap && activeCommodity() && local.clusters.length) showOverlay();
            }, 200);
            return;
        }
        removeOverlay();

        var layers = [];
        var pts = [];
        local.ringById = {};

        local.clusters.forEach(function (c) {
            var ring = clusterRing(c);
            if (ring) {
                ring.on('click', function () { selectCluster(c); });
                ring.bindTooltip(ringTooltip(c), { direction: 'top' });
                layers.push(ring);
                local.ringById[c.cluster_id] = ring;
            }
            (c.villages || []).forEach(function (v) {
                var lat = Number(v.lat), lng = Number(v.long);
                if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
                pts.push([lat, lng]);
                var dot = L.circleMarker([lat, lng], {
                    // 07-Jun feedback: smaller dots (2-5px, mirrors clusters.js)
                    // so the cluster rings clearly dominate the map.
                    radius: Math.max(2, Math.min(5, 2 + Math.sqrt(Number(v.members) || 0) * 0.5)),
                    color: '#243240', weight: 1,
                    fillColor: COMMODITY_COLOR[c.commodity] || '#0297A6',
                    fillOpacity: 0.85,
                });
                dot.on('click', function () { selectCluster(c); });
                dot.bindTooltip(
                    esc(v.vill_name || 'Village') + ' · ' + Number(v.members || 0) +
                    ' members · ' + esc(String(clusterDisplay(c))),
                    { direction: 'top' });
                layers.push(dot);
            });
        });

        local.clusterLayer = L.featureGroup(layers).addTo(state.blockMiniMap);
        local.overlayActive = true;
        highlightRing(local.selectedId);

        var fit = function () {
            try {
                if (pts.length > 1) {
                    state.blockMiniMap.fitBounds(L.latLngBounds(pts), { padding: [30, 30] });
                } else if (pts.length === 1) {
                    state.blockMiniMap.setView(pts[0], 13);
                }
            } catch (e) {}
        };
        fit();
        setTimeout(function () {
            if (state.blockMiniMap) { state.blockMiniMap.invalidateSize(); fit(); }
        }, 200);
    }

    function removeOverlay() {
        if (local.clusterLayer && state.blockMiniMap) {
            try { state.blockMiniMap.removeLayer(local.clusterLayer); } catch (e) {}
        }
        local.clusterLayer = null;
        local.overlayActive = false;
        local.ringById = {};
    }

    // A radius circle for a cluster (mirrors clusters.js clusterShape): centroid
    // + farthest-village radius with padding; amber dashed for provisional.
    function clusterRing(c) {
        var villages = (c.villages || []).filter(function (v) {
            return Number.isFinite(Number(v.lat)) && Number.isFinite(Number(v.long));
        });
        if (!villages.length) return null;
        var pts = villages.map(function (v) { return [Number(v.lat), Number(v.long)]; });
        var lat = Number(c.centroid_lat), lon = Number(c.centroid_lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || (lat === 0 && lon === 0)) {
            lat = pts.reduce(function (s, p) { return s + p[0]; }, 0) / pts.length;
            lon = pts.reduce(function (s, p) { return s + p[1]; }, 0) / pts.length;
        }
        var center = L.latLng(lat, lon);
        var radiusM = 0;
        pts.forEach(function (p) {
            var d = L.latLng(p[0], p[1]).distanceTo(center);
            if (d > radiusM) radiusM = d;
        });
        radiusM = radiusM > 0 ? radiusM * 1.18 + 60 : 220;
        if (c.provisional) {
            return L.circle(center, {
                radius: radiusM, color: PROVISIONAL_STROKE, weight: 2,
                opacity: 0.9, dashArray: '5,5',
                fillColor: PROVISIONAL_STROKE, fillOpacity: 0.06,
            });
        }
        return L.circle(center, {
            radius: radiusM, color: CLUSTER_STROKE, weight: 2.5,
            opacity: 0.95, fillColor: CLUSTER_STROKE, fillOpacity: 0.10,
        });
    }

    function ringTooltip(c) {
        return '<b>' + esc(String(clusterDisplay(c))) + '</b><br>' +
            (c.total_members || 0) + ' members · ' + (c.villages || []).length +
            ' villages · ' + (c.max_span_km != null ? c.max_span_km + ' km' : '—');
    }

    // Apply the selection highlight: reset every ring, then darken/thicken the
    // selected one and bring it to front.
    function highlightRing(selectedId) {
        Object.keys(local.ringById).forEach(function (id) {
            var ring = local.ringById[id];
            if (!ring) return;
            var c = local.clusters.find(function (x) { return String(x.cluster_id) === String(id); }) || {};
            var base = c.provisional ? PROVISIONAL_STROKE : CLUSTER_STROKE;
            ring.setStyle({ color: base, weight: c.provisional ? 2 : 2.5, fillOpacity: 0.10 });
        });
        if (selectedId && local.ringById[selectedId]) {
            var sel = local.ringById[selectedId];
            sel.setStyle({ color: SELECTED_STROKE, weight: 4, fillOpacity: 0.30 });
            try { sel.bringToFront(); } catch (e) {}
        }
    }

    // ----- wire-up -------------------------------------------------------------

    document.addEventListener('DOMContentLoaded', function () {
        var sel = getDropdown();
        if (sel) sel.addEventListener('change', handleDropdownChange);
    });

    // Expose the hooks consumed by app.blocks.js / app.views.js.
    window.clusterViewSync = clusterViewSync;
    window.clusterViewReset = clusterViewReset;
})();
