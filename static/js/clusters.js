/**
 * LEAF DSS - Cluster Planning modal.
 *
 * Independent of the block detail mini-map. Shows a "Cluster Planning" button
 * in the block header when the block has village-level data; clicking opens a
 * full-screen modal with its own Leaflet map, commodity selector, cluster
 * overlays, and CSV download/upload/regenerate controls.
 */
(function () {
    'use strict';

    // Demo guardrail (2026-05-05): hide Finalise & Publish surfaces during the
    // stakeholder demo so the conversation stays on data + clusters. Flip back
    // to true after the demo to restore the production-tool publication path.
    const SHOW_FINALIZE = false;

    // Admin-only surfaces (2026-05-09 call): Regenerate wipes user edits and
    // confused Faiz in the demo, so it's hidden from regular users. Devs can
    // still get to it via /?admin=1 or by setting localStorage.leaf_admin=1.
    // The API itself also rejects non-admin POSTs, so this isn't just cosmetic.
    const IS_ADMIN = (() => {
        try {
            const qs = new URLSearchParams(window.location.search);
            if (qs.get('admin') === '1') return true;
            if (window.localStorage && window.localStorage.getItem('leaf_admin') === '1') return true;
        } catch (e) {}
        return false;
    })();

    const COMMODITY_LABEL = {
        Dairy: 'Dairy',
        Goatery: 'Goatery',
        Piggery: 'Piggery',
        Backyard_Poultry: 'Backyard Poultry',
        Duckery: 'Duckery',
        Fishery_Activity: 'Fishery',
    };
    const PALETTE = ['#E86933', '#22AD7A', '#5088C6', '#0297A6', '#DD9103', '#46BBD4', '#a259ff', '#ff5c8a'];

    // Workflow help - explains the whole workspace, not just finalisation.
    const WORKFLOW_HELP = {
        en: { label: 'EN', sections: [
            ['About this workspace',
                'Cluster Planning is where you turn the village-level ODK survey into formal SHG livestock clusters. Each cluster is a small group of nearby villages whose interested members in one commodity (dairy, goatery, piggery, poultry, duckery or fishery) jointly meet the government funding band. The same village can sit in multiple clusters - one per commodity it has interest in.'],
            ['Step 1 - Pick a block',
                'Use the district + block dropdowns top-right. Only blocks with village data ingested are listed; if the district has just one such block, the dropdown collapses to a static label. Today only Khowang (Dibrugarh) has data; more arrive as ODK collection rolls out. The URL reflects your selection: /<district>/<block>/clustering - bookmark or share it.'],
            ['Step 2 - See the villages',
                'Coloured dots are villages plotted at their GPS point. Hover any dot for the village name, GP and per-commodity member counts. The dark blue outline is the block boundary - clusters never cross it (a hard rule per the IWMI requirements call). When you pick a commodity, dot sizes scale with members interested in that commodity.'],
            ['Step 3 - Pick a commodity',
                'The Commodity dropdown switches the cluster overlay. The greedy algorithm runs once at ingest and keeps results in Postgres; picking a commodity just reads them. Each polygon is a proposed cluster of 2-4 nearby villages whose total interested members fall in 30-50 (government band, tunable). Polygon colours are arbitrary - they only help you tell adjacent clusters apart.'],
            ['Step 4 - Review a cluster',
                'Click any polygon to open its popup: cluster ID, total members, max pairwise span (km), the list of villages, and its status (Proposed or Finalised). A green ✓ at the cluster centre means it is finalised; absence of the ✓ means it is still proposed. The "?" inside the popup opens this same workflow help.'],
            ['Step 5 - Edit clusters via CSV',
                'No in-map editor - the same backend-CSV pattern as the rest of LEAF. Download CSV gives you one row per (cluster, village). In Excel you can: split a cluster, merge two by sharing a cluster_id, drop a village by deleting its row, or fill in pashu_sakhi / block_coordinator. Upload CSV replaces the clusters in the current scope (block + commodity). Re-upload as many times as you need. Re-running Regenerate wipes your edits and starts fresh from the algorithm.'],
            ['Step 6 - Why some commodities have 0 clusters',
                'Dairy is currently empty in Khowang because no village has ≥30 dairy-interested members at default thresholds - the floor cannot be met. Either accept that the algorithm has nothing to propose, or relax the thresholds via the regenerate API (e.g. min_cluster_members=20). A UI for these knobs is on the backlog.'],
            ['Step 7 - Finalise & publish',
                'When you are satisfied, click a polygon → "Finalise & publish". The cluster is locked and starts appearing in /api/production-tool/clusters - the outbound feed the partner production tool consumes. From that point Pashu Sakhis in the field use the production tool for day-to-day operations. You can Unfinalise to reopen for editing if needed; the production tool will simply drop the cluster from its catalogue on next refresh.'],
            ['Step 8 - Aggregated metrics flow back',
                'Once the production tool is running, it POSTs aggregated metrics per cluster (e.g. duckery cluster: eggs produced, meat output) to /api/production-tool/dashboard/<cluster_id>. LEAF DSS stores the JSON as-is and surfaces it on the cluster\'s report card. Per the requirements call we only exchange aggregates - user-level data stays inside the production tool.'],
        ]},
        hi: { label: 'हिं', sections: [
            ['चरण 1 - ब्लॉक चुनें', 'ऊपर-दाएँ ड्रॉपडाउन से ज़िला और ब्लॉक चुनें। केवल वही ब्लॉक दिखेंगे जिनका गाँव डेटा अपलोड हो चुका है। फिलहाल डिब्रूगढ़ का खोवांग ब्लॉक उपलब्ध है; ODK डेटा आते ही और जुड़ेंगे।'],
            ['चरण 2 - गाँव देखें', 'रंगीन बिंदु गाँव हैं उनके GPS निर्देशांकों पर। माउस होवर करने पर हर गाँव की कमोडिटी-वार सदस्य संख्या दिखती है। गहरी नीली रेखा ब्लॉक की सीमा है।'],
            ['चरण 3 - कमोडिटी चुनें', 'बकरी, सूअर आदि चुनने पर रंगीन बहुभुज दिखेंगे - हर एक 2-4 पास के गाँवों का प्रस्तावित क्लस्टर जिसमें कुल इच्छुक सदस्य सरकारी सीमा (30-50) में हों।'],
            ['चरण 4 - समीक्षा', 'किसी भी बहुभुज पर क्लिक करके विवरण देखें: क्लस्टर ID, सदस्य संख्या, अधिकतम दूरी, गाँवों की सूची, स्थिति। बहुभुज के बीच का सफ़ेद वृत्त क्लस्टर का केंद्र है; फ़ाइनल होने पर यह हरा ✓ बन जाता है।'],
            ['चरण 5 - आवश्यक हो तो संपादन करें', 'CSV डाउनलोड करें → Excel में संपादित करें (गाँवों को क्लस्टरों के बीच इधर-उधर करें, पशु सखी का नाम भरें) → CSV अपलोड करें। या डिफ़ॉल्ट थ्रेशोल्ड के साथ अल्गोरिथम फिर चलाने के लिए Regenerate दबाएँ।'],
            ['चरण 6 - फ़ाइनलाइज़ करें', 'किसी बहुभुज पर क्लिक करके "Finalise & publish" दबाएँ - क्लस्टर लॉक होगा और प्रोडक्शन टूल पर भेज दिया जाएगा, जहाँ ज़मीनी पशु सखियाँ इसका उपयोग करती हैं।'],
        ]},
        as: { label: 'অস', sections: [
            [`পদক্ষেপ ১ - ব্লক বাছনি কৰক`, `ওপৰ-সোঁফালে ড্ৰপডাউনৰ পৰা জিলা আৰু ব্লক বাছনি কৰক। কেৱল সেই ব্লকসমূহহে দেখা যাব যাৰ গাঁৱৰ তথ্য আপলোড হৈছে; বৰ্তমান ডিব্ৰুগড়ৰ খোৱাং উপলব্ধ।`],
            [`পদক্ষেপ ২ - গাঁৱসমূহ চাওক`, `ৰঙীন বিন্দুসমূহ হৈছে গাঁৱসমূহ, ইয়াৰ GPS অৱস্থানৰ লগত। হোভাৰ কৰি প্ৰতিটো কমডিটিৰ সদস্য সংখ্যা চাব পাৰি। গাঢ় নীলা ৰেখাটো ব্লক সীমা।`],
            [`পদক্ষেপ ৩ - কমডিটি বাছনি কৰক`, `ছাগলী, গাহৰি আদি বাছনি কৰিলে ৰঙীন বহুভুজ দেখা যাব - প্ৰতিটো ২-৪ ওচৰৰ গাঁৱৰ প্ৰস্তাৱিত ক্লাষ্টাৰ যাৰ মুঠ আগ্ৰহী সদস্য চৰকাৰী সীমা (৩০-৫০)ৰ ভিতৰত।`],
            [`পদক্ষেপ ৪ - পৰ্যালোচনা`, `যিকোনো বহুভুজত ক্লিক কৰি বিৱৰণ চাওক: ক্লাষ্টাৰ ID, সদস্য, বিস্তাৰ, গাঁৱৰ তালিকা, স্থিতি। বহুভুজৰ ভিতৰৰ বগা বৃত্তটো কেন্দ্ৰ; চূড়ান্ত হলে সেইটো সেউজীয়া ✓ হৈ যায়।`],
            [`পদক্ষেপ ৫ - প্ৰয়োজন হলে সম্পাদনা`, `CSV ডাউনলোড → Excel ত সম্পাদনা (গাঁৱসমূহ ক্লাষ্টাৰৰ মাজত সলনি, পশু সখীৰ নাম লিখনি) → CSV আপলোড। বা ডিফল্ট প্ৰাচীনৰে এলগৰিথম পুনৰ চলাবলৈ Regenerate ক্লিক কৰক।`],
            [`পদক্ষেপ ৬ - চূড়ান্ত কৰক`, `কোনো এটা বহুভুজত ক্লিক কৰি "Finalise & publish" টিপক - ক্লাষ্টাৰটো লক হৈ প্ৰডাকচন টুললৈ পঠোৱা হব, যত ভূমিস্তৰৰ পশু সখীয়ে ইয়াক ব্যৱহাৰ কৰে।`],
        ]},
    };

    // Help copy in three languages. AI-drafted; have a native speaker review before final rollout.
    const HELP_TEXT = {
        en: {
            label: 'EN',
            q1: 'What does Finalise do?',
            a1: 'When you finalise a cluster, it is published to the production tool - the partner system that Pashu Sakhis use on the ground for day-to-day operations (member enrolment, livestock activities, output tracking).',
            q2: 'When should I finalise?',
            a2: 'After you have reviewed the proposed clusters and made any edits via the CSV download/upload cycle. A finalised cluster is the locked-in version that ASRLM / GIZ / the production tool will work from.',
            q3: 'Can I undo it?',
            a3: 'Yes. Click Unfinalise to remove the cluster from the production-tool feed so you can edit it again.',
            q4: 'What does the production tool see?',
            a4: 'Only finalised clusters appear in the outbound API. Proposed clusters stay private to LEAF DSS.',
        },
        hi: {
            label: 'हिं',
            q1: 'फ़ाइनलाइज़ करने पर क्या होता है?',
            a1: 'क्लस्टर को फ़ाइनलाइज़ करने पर यह प्रोडक्शन टूल पर भेज दिया जाता है - वही पार्टनर सिस्टम जिसे ज़मीनी स्तर पर पशु सखियाँ रोज़मर्रा के काम (सदस्य पंजीकरण, पशुधन गतिविधियाँ, उत्पादन रिकॉर्ड) के लिए इस्तेमाल करती हैं।',
            q2: 'मुझे कब फ़ाइनलाइज़ करना चाहिए?',
            a2: 'जब आप प्रस्तावित क्लस्टरों की समीक्षा कर लें और CSV डाउनलोड/अपलोड के ज़रिए ज़रूरी बदलाव कर लें। फ़ाइनल क्लस्टर वही संस्करण है जिस पर ASRLM, GIZ और प्रोडक्शन टूल काम करेंगे।',
            q3: 'क्या मैं इसे पलट सकता हूँ?',
            a3: 'हाँ। "अनफ़ाइनलाइज़" पर क्लिक करके क्लस्टर को प्रोडक्शन टूल फ़ीड से हटाया जा सकता है, फिर से एडिट किया जा सकता है।',
            q4: 'प्रोडक्शन टूल को क्या दिखता है?',
            a4: 'केवल फ़ाइनल क्लस्टर ही बाहरी API में आते हैं। प्रस्तावित क्लस्टर LEAF DSS तक ही सीमित रहते हैं।',
        },
        as: {
            label: 'অস',
            q1: 'চূড়ান্ত কৰিলে কি হয়?',
            a1: 'এটা ক্লাষ্টাৰ চূড়ান্ত কৰিলে এইটো প্ৰডাকচন টুলত প্ৰকাশ কৰা হয় - যিটো সঁজুলি ভূমিস্তৰৰ পশু সখীসকলে দৈনন্দিন কামৰ বাবে (সদস্য পঞ্জীয়ন, পশুধন কাৰ্যকলাপ, উৎপাদন ট্ৰেকিং) ব্যৱহাৰ কৰে।',
            q2: 'কেতিয়া চূড়ান্ত কৰিব লাগে?',
            a2: 'যেতিয়া আপুনি প্ৰস্তাৱিত ক্লাষ্টাৰসমূহ পৰীক্ষা কৰি CSV ডাউনলোড/আপলোডৰ দ্বাৰা সম্পাদনা কৰি লৈছে। চূড়ান্ত ক্লাষ্টাৰ হৈছে সেই লক হোৱা সংস্কৰণ যিটোৰ ভিত্তিত ASRLM / GIZ / প্ৰডাকচন টুলে কাম কৰিব।',
            q3: 'ইয়াক উভতাব পাৰিম নেকি?',
            a3: 'হয়। "অচূড়ান্ত (Unfinalise)" ক্লিক কৰি ক্লাষ্টাৰটো প্ৰডাকচন টুল ফীডৰ পৰা আঁতৰাব পাৰি যাতে পুনৰ সম্পাদনা কৰিব পাৰে।',
            q4: 'প্ৰডাকচন টুলে কি দেখা পায়?',
            a4: 'কেৱল চূড়ান্ত ক্লাষ্টাৰসমূহহে বহিৰাগত API ত দেখা যায়। প্ৰস্তাৱিত ক্লাষ্টাৰসমূহ LEAF DSS-ৰ ভিতৰতে থাকে।',
        },
    };

    function helpPanelHTML() {
        const tabs = Object.keys(HELP_TEXT).map((code, i) =>
            `<button class="cluster-help-tab" data-lang="${code}" type="button"
                style="padding: 3px 9px; font-size: 11px; cursor: pointer; border-radius: 3px;
                       border: 1px solid #5088C6;
                       background: ${i === 0 ? '#5088C6' : '#fff'};
                       color: ${i === 0 ? '#fff' : '#28537D'};">${HELP_TEXT[code].label}</button>`
        ).join('');
        const sections = Object.keys(HELP_TEXT).map((code, i) => {
            const h = HELP_TEXT[code];
            return `<div class="cluster-help-lang" data-lang="${code}" style="display: ${i === 0 ? 'block' : 'none'};">
                <b style="color: #28537D;">${h.q1}</b><br>${h.a1}<br><br>
                <b style="color: #28537D;">${h.q2}</b><br>${h.a2}<br><br>
                <b style="color: #28537D;">${h.q3}</b><br>${h.a3}<br><br>
                <b style="color: #28537D;">${h.q4}</b><br>${h.a4}
            </div>`;
        }).join('');
        return `<div class="cluster-help-tabs" style="display: flex; gap: 4px; margin-bottom: 8px;">${tabs}</div>${sections}`;
    }

    const local = {
        blocksByUpper: null,         // Map<UPPER, canonicalBlockName> - village-data blocks only
        blocksRich: null,            // Array<{block_name, district_name, village_count}>
        blocksGeojson: null,         // cached /api/blocks GeoJSON
        allLocations: null,          // Full district+block list from /api/locations
        currentBlock: null,
        currentDistrict: null,
        currentCommodity: '',
        modalMap: null,
        boundaryLayer: null,
        boundaryBounds: null,
        villageLayer: null,
        clusterLayer: null,
        villageFeatures: null,
    };

    const $ = (id) => document.getElementById(id);
    const appState = () => { try { return state; } catch (e) { return null; } };

    function colorFor(seed) {
        let h = 0;
        for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
        return PALETTE[h % PALETTE.length];
    }

    // Categorical palette for GP coloring on the village layer. Picked for
    // adjacency contrast — Tableau 10 + 6 extras to comfortably cover the
    // 13–25 GPs typically found in one block.
    const GP_PALETTE = [
        '#4E79A7', '#F28E2B', '#59A14F', '#E15759', '#76B7B2', '#EDC948',
        '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC', '#1F77B4', '#FF7F0E',
        '#2CA02C', '#D62728', '#9467BD', '#8C564B',
    ];
    function colorForGp(gpName) {
        const seed = (gpName || '').toString().toUpperCase();
        let h = 5381;
        for (let i = 0; i < seed.length; i++) h = ((h << 5) + h + seed.charCodeAt(i)) >>> 0;
        return GP_PALETTE[h % GP_PALETTE.length];
    }

    async function ensureBlocksWithVillages() {
        if (local.blocksByUpper) return local.blocksByUpper;
        try {
            const r = await fetch('/api/villages/blocks');
            const data = await r.json();
            local.blocksByUpper = new Map();
            local.blocksRich = data || [];
            (data || []).forEach(d => {
                if (d.block_name) local.blocksByUpper.set(d.block_name.toUpperCase(), d.block_name);
            });
        } catch (e) {
            console.warn('Failed to load villages/blocks:', e);
            local.blocksByUpper = new Map();
            local.blocksRich = [];
        }
        return local.blocksByUpper;
    }

    async function ensureAllLocations() {
        if (local.allLocations) return local.allLocations;
        try {
            const r = await fetch('/api/locations');
            const data = await r.json();
            // Use the flat blocks array - { block_name, district }.
            const blocks = (data && data.blocks) || [];
            const grouped = new Map();
            blocks.forEach(b => {
                if (!b.district || !b.block_name) return;
                if (!grouped.has(b.district)) grouped.set(b.district, new Set());
                grouped.get(b.district).add(b.block_name);
            });
            local.allLocations = grouped;
        } catch (e) {
            console.warn('Failed to load /api/locations:', e);
            local.allLocations = new Map();
        }
        return local.allLocations;
    }

    async function ensureBlocksGeojson() {
        if (local.blocksGeojson) return local.blocksGeojson;
        try {
            const r = await fetch('/api/blocks/geojson');
            local.blocksGeojson = await r.json();
        } catch (e) {
            console.warn('Failed to load /api/blocks:', e);
            local.blocksGeojson = { type: 'FeatureCollection', features: [] };
        }
        return local.blocksGeojson;
    }

    async function findBlockFeature(canonicalBlockName) {
        const fc = await ensureBlocksGeojson();
        if (!fc || !Array.isArray(fc.features)) return null;
        const target = String(canonicalBlockName).toUpperCase();
        return fc.features.find(f =>
            ((f.properties && f.properties.Block_name) || '').toUpperCase() === target
        ) || null;
    }

    function districtForBlock(canonicalBlockName) {
        const upper = String(canonicalBlockName).toUpperCase();
        const rec = (local.blocksRich || []).find(d => (d.block_name || '').toUpperCase() === upper);
        return rec ? rec.district_name : null;
    }

    /**
     * Show only districts that have at least one block with village data.
     * If only one district qualifies, hide the dropdown and show its name as
     * a plain label - the dropdown adds no value with a single option.
     */
    function populateModalDropdowns() {
        const districtSel = $('modal-district-select');
        const districtLabel = $('modal-district-label');
        if (!districtSel) return;

        // Districts in MMUA (uppercase) reconciled to display case via /api/locations.
        const districtsWithDataUpper = new Set(
            (local.blocksRich || []).map(d => (d.district_name || '').toUpperCase())
        );
        const allDistricts = Array.from((local.allLocations || new Map()).keys());
        const eligible = allDistricts.filter(d => districtsWithDataUpper.has(d.toUpperCase())).sort();
        const display = eligible.length ? eligible : allDistricts.sort();

        districtSel.innerHTML = display.map(d =>
            `<option value="${d}">${d}</option>`
        ).join('');

        const wantUpper = (local.currentDistrict || '').toUpperCase();
        const matchExact = display.find(d => d.toUpperCase() === wantUpper) || display[0] || '';
        districtSel.value = matchExact;
        local.currentDistrict = districtSel.value || null;

        // Collapse the dropdown to a static label when only one district is available.
        if (display.length <= 1) {
            districtSel.style.display = 'none';
            if (districtLabel) {
                districtLabel.textContent = matchExact;
                districtLabel.style.display = 'inline-flex';
            }
        } else {
            districtSel.style.display = '';
            if (districtLabel) districtLabel.style.display = 'none';
        }

        repopulateBlockDropdown();
    }

    /**
     * Block dropdown shows every block in the selected district. Blocks without
     * village data are tagged "(no village data)" and disabled - selecting them
     * would have nothing to plot.
     */
    /**
     * Show only blocks in this district that have village data ingested.
     * If just one qualifies, hide the dropdown and show its name as a label.
     */
    function repopulateBlockDropdown() {
        const blockSel = $('modal-block-select');
        const blockLabel = $('modal-block-label');
        if (!blockSel) return;

        const want = (local.currentDistrict || '').toUpperCase();
        const blocksWithData = (local.blocksRich || [])
            .filter(d => (d.district_name || '').toUpperCase() === want)
            .map(d => ({ name: d.block_name, count: d.village_count || 0 }));

        // Reconcile to /api/locations display case where possible so the value
        // we POST back to the API matches MMUA's casing exactly.
        let displayBlocks = blocksWithData;
        if (local.allLocations) {
            const locBlocks = Array.from(
                (Array.from(local.allLocations.entries()).find(([d]) => d.toUpperCase() === want) || [null, new Set()])[1]
            );
            displayBlocks = blocksWithData.map(b => ({
                name: locBlocks.find(lb => lb.toUpperCase() === b.name.toUpperCase()) || b.name,
                count: b.count,
            }));
        }
        displayBlocks.sort((a, b) => a.name.localeCompare(b.name));

        blockSel.innerHTML = displayBlocks.map(b =>
            `<option value="${b.name}">${b.name} (${b.count} villages)</option>`
        ).join('');

        const upper = local.currentBlock ? local.currentBlock.toUpperCase() : '';
        const match = displayBlocks.find(b => b.name.toUpperCase() === upper);
        const chosen = match ? match.name : (displayBlocks[0] ? displayBlocks[0].name : '');
        blockSel.value = chosen;

        if (displayBlocks.length <= 1) {
            blockSel.style.display = 'none';
            if (blockLabel) {
                blockLabel.textContent = chosen
                    ? `${chosen} (${(displayBlocks[0] && displayBlocks[0].count) || 0} villages)`
                    : '';
                blockLabel.style.display = chosen ? 'inline-flex' : 'none';
            }
        } else {
            blockSel.style.display = '';
            if (blockLabel) blockLabel.style.display = 'none';
        }
    }

    function activeBlockName() {
        const s = appState();
        if (!s || !s.blockFeature) return '';
        return (s.blockFeature.properties && s.blockFeature.properties.Block_name) || '';
    }

    async function blockHasVillages(rawBlockName) {
        if (!rawBlockName) return null;
        const blocks = await ensureBlocksWithVillages();
        return blocks.get(String(rawBlockName).toUpperCase()) || null;
    }

    async function refreshOpenButton() {
        const btn = $('open-cluster-planner');
        if (!btn) return;
        const raw = activeBlockName();
        const canonical = await blockHasVillages(raw);
        if (!canonical) {
            btn.style.display = 'none';
            return;
        }
        // Build the nested URL /<district>/<block>/clustering using the same
        // case-sensitive segments the outer block detail view uses.
        const s = appState();
        const props = (s && s.blockFeature && s.blockFeature.properties) || {};
        const districtSeg = props.Dist_Name || '';
        const blockSeg = props.Block_name || canonical;
        if (districtSeg && blockSeg) {
            btn.setAttribute(
                'href',
                `/${encodeURIComponent(districtSeg)}/${encodeURIComponent(blockSeg)}/clustering`
            );
        }
        btn.style.display = 'inline-flex';
    }

    // ---- Modal map lifecycle ----

    function teardownMap() {
        if (local.modalMap) {
            local.modalMap.remove();
            local.modalMap = null;
        }
        local.boundaryLayer = null;
        local.villageLayer = null;
        local.clusterLayer = null;
    }

    function buildMap() {
        teardownMap();
        // Default view = rough centre of Assam, in case fitBounds never fires
        // (no block feature found). Without an initial view, Leaflet won't load
        // tiles or render layers at all.
        local.modalMap = L.map('cluster-modal-map', {
            zoomControl: true,
            attributionControl: false,
            center: [26.2, 92.9],
            zoom: 8,
        });
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            maxZoom: 18,
        }).addTo(local.modalMap);

        // Bind popup buttons as soon as a popup opens - Leaflet stops click propagation
        // past popups, so modal-level event delegation doesn't see them.
        local.modalMap.on('popupopen', (ev) => {
            const root = ev.popup && ev.popup.getElement();
            if (!root) return;

            const finalizeBtn = root.querySelector('.cluster-finalize-btn');
            if (finalizeBtn) finalizeBtn.onclick = (e) => handleFinalizeClick(e, finalizeBtn);

            // The popup "?" opens the top-level workflow help overlay (which sits
            // above everything at z-index 10000) - keeping the popup itself compact.
            const helpBtn = root.querySelector('.cluster-help-btn');
            if (helpBtn) helpBtn.onclick = openWorkflowHelp;
        });
    }

    /**
     * Resolve the block geometry to draw on the modal map. Prefers the cached
     * outer-app feature when available; falls back to /api/blocks lookup so the
     * modal works even after switching to a different block via the dropdown.
     */
    async function blockFeatureFor(canonicalBlockName) {
        const s = appState();
        if (s && s.blockFeature) {
            const props = s.blockFeature.properties || {};
            if ((props.Block_name || '').toUpperCase() === String(canonicalBlockName).toUpperCase()) {
                return s.blockFeature;
            }
        }
        return await findBlockFeature(canonicalBlockName);
    }

    /**
     * Add the block boundary polygon and (when available) the GP polygons inside.
     */
    async function renderBoundaries() {
        if (!local.modalMap) return;
        const blockFeature = await blockFeatureFor(local.currentBlock);
        if (!blockFeature) return;
        const s = appState();

        const layers = [];

        const blockLayer = L.geoJSON(blockFeature, {
            style: {
                color: '#28537D',
                weight: 2.5,
                fillColor: '#0297A6',
                fillOpacity: 0.08,
                interactive: false,
            },
        });
        layers.push(blockLayer);

        // GP polygons inside the block (Tinsukia today; safe no-op elsewhere).
        const districtName = (blockFeature.properties && blockFeature.properties.Dist_Name) || '';
        const gpDistricts = (s && s.gpDistricts) || [];
        if (s && s.gpAvailable && gpDistricts.includes(districtName)) {
            try {
                const r = await fetch('/api/gp/geojson');
                const gp = await r.json();
                if (gp && Array.isArray(gp.features)) {
                    const blockGPs = {
                        type: 'FeatureCollection',
                        features: gp.features.filter(f =>
                            (f.properties && f.properties.Block_Name) === blockFeature.properties.Block_name),
                    };
                    if (blockGPs.features.length) {
                        const gpLayer = L.geoJSON(blockGPs, {
                            style: {
                                color: '#1b5e20',
                                weight: 1.2,
                                fillColor: '#a5d6a7',
                                fillOpacity: 0.15,
                                interactive: false,
                            },
                        });
                        layers.push(gpLayer);
                    }
                }
            } catch (e) {
                console.warn('GP polygon fetch failed in cluster modal:', e);
            }
        }

        local.boundaryLayer = L.layerGroup(layers).addTo(local.modalMap);
        try {
            local.boundaryBounds = blockLayer.getBounds();
            local.modalMap.fitBounds(local.boundaryBounds, { padding: [40, 40] });
            local.modalMap.__fitted = true;
        } catch (e) {}
    }

    function memberKeyForCurrent(props) {
        return local.currentCommodity ? Number(props[local.currentCommodity] || 0) : 0;
    }

    function renderVillageLayer() {
        if (!local.modalMap || !local.villageFeatures) return;
        if (local.villageLayer) local.modalMap.removeLayer(local.villageLayer);

        local.villageLayer = L.geoJSON(local.villageFeatures, {
            pointToLayer: (feat, latlng) => {
                const p = feat.properties || {};
                const members = memberKeyForCurrent(p);
                const radius = local.currentCommodity
                    ? Math.max(4, Math.min(14, 4 + Math.sqrt(members) * 1.2))
                    : 5;
                const gpColor = colorForGp(p.gp_name);
                // In commodity-mode, dim villages with no interest so the
                // active commodity stands out; GP color still readable.
                const noInterest = local.currentCommodity && members === 0;
                return L.circleMarker(latlng, {
                    radius,
                    color: '#243240',
                    weight: 1,
                    fillColor: noInterest ? '#cfd6dc' : gpColor,
                    fillOpacity: noInterest ? 0.55 : 0.85,
                });
            },
            onEachFeature: (feat, layer) => {
                const p = feat.properties || {};
                const swatch = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colorForGp(p.gp_name)};margin-right:5px;vertical-align:middle"></span>`;
                let total = 0;
                const rows = COMMODITY_PANEL_ORDER.map(k => {
                    const v = Number(p[k] || 0);
                    total += v;
                    const dim = v === 0 ? 'opacity:0.5;' : '';
                    return `<tr style="${dim}"><td style="padding-right:8px;color:#4a5868">${escapeHtml(COMMODITY_LABEL[k] || k)}</td>` +
                           `<td style="text-align:right;font-weight:${v > 0 ? '600' : '400'}">${v ? v.toLocaleString() : '—'}</td></tr>`;
                }).join('');
                const html = `
                    <div style="font-size:13px;min-width:190px">
                        <div style="font-weight:600;font-size:15px">${escapeHtml(p.vill_name || 'Village')}</div>
                        <div style="color:#607080;margin-bottom:4px">${swatch}${escapeHtml(p.gp_name || '')}</div>
                        <table style="width:100%;border-collapse:collapse;font-size:12px">${rows}
                            <tr style="border-top:1px solid #e3e7eb">
                                <td style="padding-top:3px;color:#4a5868">Total</td>
                                <td style="text-align:right;padding-top:3px;font-weight:700">${total.toLocaleString()}</td>
                            </tr>
                        </table>
                    </div>`;
                layer.bindTooltip(html, { className: 'custom-tooltip', direction: 'top' });
            },
        }).addTo(local.modalMap);

        // Block boundary already drove fitBounds via renderBoundaries(); skip
        // re-fitting to villages so the user keeps the block-extent context.
    }

    // Cluster shape (post-2026-05-09 redesign per Faiz):
    //   - One neutral colour for every cluster - the multi-colour palette was
    //     confusing and didn't encode anything meaningful. Village dots still
    //     carry GP colour; cluster size is read from the dot sizes inside.
    //   - Draw a containment CIRCLE around the cluster (instead of polygons /
    //     connector lines), so the shape reads as "this group" without
    //     implying a polygonal boundary. Overlaps between clusters are
    //     expected and fine.
    const CLUSTER_STROKE = '#28537D';
    const CLUSTER_FILL = '#28537D';

    function clusterShape(cluster) {
        const villages = (cluster.villages || []).filter(v =>
            Number.isFinite(Number(v.lat)) && Number.isFinite(Number(v.long)));
        if (villages.length === 0) return null;

        const pts = villages.map(v => [Number(v.lat), Number(v.long)]);
        // Centroid: prefer the persisted one (algorithm output) so the circle
        // sits exactly where the centroid marker would; fall back to mean.
        let centerLat = Number(cluster.centroid_lat);
        let centerLon = Number(cluster.centroid_lon);
        if (!Number.isFinite(centerLat) || !Number.isFinite(centerLon)
            || (centerLat === 0 && centerLon === 0)) {
            centerLat = pts.reduce((s, p) => s + p[0], 0) / pts.length;
            centerLon = pts.reduce((s, p) => s + p[1], 0) / pts.length;
        }

        // Radius: farthest village from centroid, plus a small padding so the
        // outermost dot sits visibly inside the ring, not on it. For single-
        // village clusters (new in #18) fall back to a fixed visible radius.
        const center = L.latLng(centerLat, centerLon);
        let radiusM = 0;
        pts.forEach(p => {
            const d = L.latLng(p[0], p[1]).distanceTo(center);
            if (d > radiusM) radiusM = d;
        });
        radiusM = radiusM > 0 ? radiusM * 1.18 + 60 : 220;

        return L.circle(center, {
            radius: radiusM,
            color: CLUSTER_STROKE,
            weight: 2.5,
            opacity: 0.95,
            fillColor: CLUSTER_FILL,
            fillOpacity: 0.10,
        });
    }

    function clusterHoverHTML(c) {
        // Brief, non-interactive hover hint. cluster_num is the user-friendly
        // sequential label (per Faiz, 2026-05-09); cluster_id stays as a faint
        // subtitle so devs/CSV editors can still cross-reference.
        const label = c.cluster_num != null ? `Cluster ${c.cluster_num}` : c.cluster_id;
        return `<div style="font-size: 13px">
            <b>${label}</b>
            ${c.cluster_num != null ? `<small style="color:#888"> · ${c.cluster_id}</small>` : ''}<br>
            ${c.total_members} members · ${(c.villages || []).length} villages · ${c.max_span_km} km
            <br><small>Click for details</small>
        </div>`;
    }

    function clusterPopupHTML(c) {
        const villages = (c.villages || []).map(v =>
            `<li>${v.vill_name} <small>(${v.members} members)</small></li>`).join('');
        const status = c.finalized
            ? '<span style="color:#22AD7A; font-weight: 600">✓ Finalised - published to production tool</span>'
            : '<span style="color:#888">Proposed - not yet published</span>';
        const label = c.cluster_num != null ? `Cluster ${c.cluster_num}` : c.cluster_id;
        return `<div class="cluster-popup" style="min-width: 260px; max-width: 360px; font-size: 14px;">
            <div style="font-weight: 600; font-size: 15px;">${label}${c.cluster_num != null ? `<small style="color:#888;font-weight:400"> · ${c.cluster_id}</small>` : ''}</div>
            <small style="color: #666;">${COMMODITY_LABEL[c.commodity] || c.commodity} · ${c.block_name} · ${c.district_name || ''}</small>
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #eee">
            <div><b>${c.total_members}</b> members across <b>${(c.villages || []).length}</b> villages, <b>${c.max_span_km}</b> km max span</div>
            <div style="margin-top: 4px;">${status}</div>
            ${(c.pashu_sakhi || c.block_coordinator) ? `<div style="margin-top: 4px; font-size: 12px; color: #555;">
                ${c.pashu_sakhi ? 'Pashu Sakhi: <b>' + c.pashu_sakhi + '</b>' : ''}
                ${c.block_coordinator ? '<br>Block coord: <b>' + c.block_coordinator + '</b>' : ''}
            </div>` : ''}
            <ul style="margin: 8px 0 0 18px; padding: 0;">${villages}</ul>
            ${SHOW_FINALIZE ? `
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #eee">
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <button class="cluster-finalize-btn" data-cluster-id="${c.cluster_id}" data-finalized="${c.finalized}"
                    data-tooltip-wrap data-tooltip="${c.finalized ? 'Reopen this cluster for editing - removes it from the production-tool feed' : 'Lock this cluster and publish it to the production-tool feed'}"
                    style="padding: 6px 14px; font-size: 12px; cursor: pointer;
                           background: ${c.finalized ? '#fff' : '#22AD7A'}; color: ${c.finalized ? '#28537D' : '#fff'};
                           border: 1px solid #22AD7A; border-radius: 4px; font-weight: 600;">
                    ${c.finalized ? 'Unfinalise' : 'Finalise & publish'}
                </button>
                <button class="cluster-help-btn" type="button" aria-label="How does Finalise work?"
                    data-tooltip-wrap data-tooltip="Open the workflow help (also available from the ? in the header)"
                    style="width: 24px; height: 24px; border-radius: 50%; border: 1px solid #cfd6dc;
                           background: #fff; color: #28537D; font-weight: 700; cursor: pointer;
                           font-size: 13px; line-height: 1;">?</button>
            </div>
            ` : ''}
        </div>`;
    }

    function statusMarker(cluster) {
        // Only finalised clusters get a centroid badge - proposed is the default state
        // and putting a marker on every cluster is visual noise.
        if (!cluster.finalized) return null;
        const lat = Number(cluster.centroid_lat);
        const lon = Number(cluster.centroid_lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
        const html = `<div class="cluster-status-marker finalised">✓</div>`;
        const icon = L.divIcon({
            className: '',
            html,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
        });
        return L.marker([lat, lon], { icon, interactive: false, keyboard: false });
    }

    function showLegend() {
        const legend = $('cluster-legend');
        if (legend) legend.style.display = 'flex';
    }

    /** Set the toolbar's summary line to a busy state with spinner. */
    function setBusy(msg) {
        const summary = $('cluster-summary');
        if (!summary) return;
        summary.innerHTML =
            `<span class="cluster-status-msg"><span class="cluster-spinner"></span>${msg}</span>`;
    }

    /** Disable an action button while a request is in flight. */
    function setButtonBusy(btn, label) {
        if (!btn) return () => {};
        const orig = btn.innerHTML;
        const wasDisabled = btn.disabled;
        btn.innerHTML = `<span class="cluster-spinner"></span>${label}`;
        btn.disabled = true;
        return () => {
            btn.innerHTML = orig;
            btn.disabled = wasDisabled;
        };
    }

    /** Show a full-modal loading overlay while heavyweight async work runs. */
    function showPageLoader(msg) {
        const el = $('cluster-page-loader');
        const msgEl = $('cluster-page-loader-msg');
        if (msgEl) msgEl.textContent = msg || 'Loading…';
        if (el) el.style.display = 'flex';
    }
    function hidePageLoader() {
        const el = $('cluster-page-loader');
        if (el) el.style.display = 'none';
    }

    async function renderClusterLayer() {
        if (!local.modalMap) return;
        if (local.clusterLayer) {
            local.modalMap.removeLayer(local.clusterLayer);
            local.clusterLayer = null;
        }
        if (!local.currentBlock || !local.currentCommodity) {
            updateSummary(0);
            setSearchVisible(false);
            return;
        }
        setBusy(`Loading ${COMMODITY_LABEL[local.currentCommodity] || local.currentCommodity} clusters…`);
        let clusters = [];
        try {
            const r = await fetch(`/api/clusters?block=${encodeURIComponent(local.currentBlock)}` +
                                  `&commodity=${encodeURIComponent(local.currentCommodity)}`);
            clusters = await r.json();
        } catch (e) {
            console.warn('Cluster fetch failed:', e);
        }
        if (!Array.isArray(clusters) || clusters.length === 0) {
            updateSummary(0);
            setSearchVisible(false);
            return;
        }
        const layers = [];
        // Registry for the search box: keyed by both numeric cluster_num and
        // (lower-cased) cluster_id so users can type either.
        local.clusterRegistry = {};
        clusters.forEach(c => {
            const shape = clusterShape(c);
            if (shape) {
                shape.bindTooltip(clusterHoverHTML(c), {
                    className: 'custom-tooltip',
                    direction: 'auto',  // Leaflet flips to keep tooltip visible.
                    sticky: true,
                });
                shape.bindPopup(clusterPopupHTML(c), {
                    minWidth: 240,
                    maxWidth: 340,
                    closeButton: true,
                    autoPanPadding: [40, 40],
                });
                shape.on('click', () => renderClusterSummaryPanel(c));
                layers.push(shape);
                if (c.cluster_num != null) local.clusterRegistry[String(c.cluster_num)] = { cluster: c, shape };
                if (c.cluster_id) local.clusterRegistry[String(c.cluster_id).toLowerCase()] = { cluster: c, shape };
            }
            const m = statusMarker(c);
            if (m) layers.push(m);
        });
        if (!layers.length) {
            updateSummary(0);
            setSearchVisible(false);
            return;
        }
        local.clusterLayer = L.featureGroup(layers).addTo(local.modalMap);
        updateSummary(clusters.length, clusters);
        setSearchVisible(true);
    }

    // ---- Cluster search ----

    function setSearchVisible(show) {
        const wrap = $('cluster-search-wrap');
        if (!wrap) return;
        wrap.style.display = show ? '' : 'none';
        if (!show) {
            const input = $('cluster-search');
            if (input) input.value = '';
            wrap.classList.remove('found', 'not-found');
        }
    }

    function findCluster(query) {
        if (!query || !local.clusterRegistry) return null;
        const key = String(query).trim().toLowerCase();
        return local.clusterRegistry[key] || null;
    }

    function highlightCluster(hit) {
        if (!hit || !hit.shape || !local.modalMap) return;
        const shape = hit.shape;
        try {
            const bounds = shape.getBounds ? shape.getBounds() : null;
            if (bounds && bounds.isValid()) {
                local.modalMap.fitBounds(bounds, { padding: [60, 60], maxZoom: 14 });
            } else if (shape.getLatLngs) {
                const pts = shape.getLatLngs();
                if (pts && pts.length) local.modalMap.panTo(pts[0]);
            }
            shape.openPopup();
            const path = shape._path;
            if (path) {
                path.classList.remove('cluster-search-flash');
                // Reflow to restart the animation if the user searches repeatedly.
                void path.getBoundingClientRect();
                path.classList.add('cluster-search-flash');
            }
        } catch (e) {
            console.warn('Highlight failed:', e);
        }
    }

    function handleSearchInput(ev) {
        const wrap = $('cluster-search-wrap');
        const value = ev.target.value;
        if (!wrap) return;
        wrap.classList.remove('found', 'not-found');
        if (!value.trim()) return;
        // On Enter, commit and highlight. On plain typing, just hint match/no-match.
        const hit = findCluster(value);
        if (ev.key === 'Escape') {
            ev.target.value = '';
            return;
        }
        if (ev.key === 'Enter') {
            if (hit) {
                wrap.classList.add('found');
                highlightCluster(hit);
            } else {
                wrap.classList.add('not-found');
            }
            return;
        }
        // Live feedback as the user types.
        wrap.classList.add(hit ? 'found' : 'not-found');
    }

    function updateSummary(count, clusters) {
        const summary = $('cluster-summary');
        if (!summary) return;
        if (!local.currentCommodity) {
            const n = local.villageFeatures ? (local.villageFeatures.features || []).length : 0;
            summary.textContent = `${n} villages - pick a commodity to see clusters.`;
            return;
        }
        if (!count) {
            summary.textContent = `No ${COMMODITY_LABEL[local.currentCommodity]} clusters formed at default thresholds. ` +
                                  'Try Regenerate with relaxed parameters via the API.';
            return;
        }
        const total = (clusters || []).reduce((s, c) => s + (c.total_members || 0), 0);
        const finalised = (clusters || []).filter(c => c.finalized).length;
        summary.textContent =
            `${count} ${COMMODITY_LABEL[local.currentCommodity]} cluster${count === 1 ? '' : 's'} · ` +
            `${total} members · ${finalised} finalised`;
    }

    function updateDownloadHref() {
        const a = $('cluster-download');
        if (!a) return;
        const params = new URLSearchParams();
        if (local.currentBlock) params.set('block', local.currentBlock);
        if (local.currentCommodity) params.set('commodity', local.currentCommodity);
        a.href = '/api/clusters/export.csv?' + params.toString();
        a.classList.toggle('disabled', !local.currentCommodity);
    }

    // ---- Right-side summary panel ----

    const COMMODITY_PANEL_ORDER = [
        'Dairy', 'Goatery', 'Piggery', 'Backyard_Poultry', 'Duckery', 'Fishery_Activity',
    ];

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function renderSidePanelEmpty(msg) {
        const el = $('cluster-side-panel');
        if (el) el.innerHTML = `<div class="cluster-side-empty">${escapeHtml(msg || 'Select a block.')}</div>`;
    }

    function renderBlockSummaryPanel(s) {
        const el = $('cluster-side-panel');
        if (!el) return;
        if (!s || !s.available) {
            renderSidePanelEmpty(`No SHG form data for ${s && s.block_name ? s.block_name : 'this block'} yet.`);
            return;
        }
        local.lastBlockSummary = s;
        const row = (label, value, muted) =>
            `<div class="cluster-side-row${muted ? ' muted' : ''}">
                <span class="label">${escapeHtml(label)}</span>
                <span class="value">${escapeHtml(value)}</span>
            </div>`;
        const commodityRows = COMMODITY_PANEL_ORDER.map(k => {
            const label = COMMODITY_LABEL[k] || k.replace(/_/g, ' ');
            const v = (s.commodities && s.commodities[k]) || 0;
            return row(label, v.toLocaleString(), v === 0);
        }).join('');
        const otherTotal = Object.values(s.other || {}).reduce((a, b) => a + b, 0);
        const otherRows = Object.entries(s.other || {}).map(([k, v]) =>
            row(k, v.toLocaleString(), v === 0)).join('');
        const gpItems = (s.gps || []).map(gp =>
            `<span class="gp-chip" title="${escapeHtml(gp)}">
                <span class="gp-swatch" style="background:${colorForGp(gp)}"></span>${escapeHtml(gp)}
            </span>`).join('');
        el.innerHTML = `
            <h3><i class="bi bi-bar-chart-line"></i> ${escapeHtml(s.block_name)}</h3>
            <div class="cluster-side-sub">${escapeHtml(s.district_name || '')} district</div>
            <div class="cluster-side-section">Coverage</div>
            ${row('Villages mapped', s.villages_total.toLocaleString())}
            ${row('Gram Panchayats', s.gp_count.toLocaleString())}
            <div class="cluster-side-section">SHG members by commodity</div>
            ${commodityRows}
            <details class="cluster-side-other"${otherTotal ? ' open' : ''}>
                <summary>Other activities (${otherTotal.toLocaleString()})</summary>
                ${otherRows || '<div class="cluster-side-empty">No data.</div>'}
            </details>
            <div class="cluster-side-section">Total members</div>
            ${row('Across all activities', s.members_total.toLocaleString())}
            <div class="cluster-side-section" title="Map dots are coloured by GP">Gram Panchayats — dot colours</div>
            <div class="gp-chip-list">${gpItems || '<div class="cluster-side-empty">No GPs.</div>'}</div>
        `;
    }

    // Defaults mirror clustering.py DEFAULT_PARAMS. Kept here so the side
    // panel can explain *why* a group qualified as a cluster without making
    // an extra round-trip on every click. If thresholds change server-side,
    // update both. Also tunable per-block via the params API, but the demo
    // flow uses defaults.
    const CLUSTER_RULES = {
        min_members_per_village: 1,
        min_cluster_members: 30,
        max_cluster_members: 50,
        min_villages_per_cluster: 2,
        max_villages_per_cluster: 4,
        max_radius_km: 5.0,
    };

    function otherCommoditiesFor(cluster) {
        // Aggregate non-focal commodity counts across the cluster's villages
        // by looking them up in the village features already loaded for the
        // current block. Returns [{commodity, total, perVillage:[{name, n}]}].
        if (!local.villageFeatures || !local.villageFeatures.features) return [];
        const want = new Set((cluster.villages || []).map(v =>
            String(v.vill_name || '').trim().toLowerCase()));
        if (!want.size) return [];
        const matches = local.villageFeatures.features.filter(f =>
            want.has(String(((f.properties || {}).vill_name) || '').trim().toLowerCase()));
        if (!matches.length) return [];
        const focal = cluster.commodity;
        return COMMODITY_PANEL_ORDER
            .filter(k => k !== focal)
            .map(k => {
                let total = 0;
                const perVillage = [];
                matches.forEach(f => {
                    const n = Number((f.properties || {})[k] || 0);
                    if (n > 0) {
                        total += n;
                        perVillage.push({ name: f.properties.vill_name, n });
                    }
                });
                return { commodity: k, total, perVillage };
            })
            .filter(r => r.total > 0)
            .sort((a, b) => b.total - a.total);
    }

    function ruleExplanation(cluster) {
        // Restate the rules in terms of THIS cluster's numbers so users can
        // see *which* checks the group satisfied. Each row is a fact + tick.
        const villageCount = (cluster.villages || []).length;
        const members = Number(cluster.total_members || 0);
        const span = Number(cluster.max_span_km || 0);
        const minPerVill = Math.min(...((cluster.villages || []).map(v => Number(v.members || 0))));
        const tick = ok => ok
            ? '<span style="color:#22AD7A;font-weight:600">&#10003;</span>'
            : '<span style="color:#c0392b;font-weight:600">!</span>';
        const rules = [
            {
                ok: members >= CLUSTER_RULES.min_cluster_members
                    && members <= CLUSTER_RULES.max_cluster_members,
                text: `Total members <b>${members.toLocaleString()}</b> sits in the funding band ` +
                      `[${CLUSTER_RULES.min_cluster_members}-${CLUSTER_RULES.max_cluster_members}]`,
            },
            {
                ok: villageCount >= CLUSTER_RULES.min_villages_per_cluster
                    && villageCount <= CLUSTER_RULES.max_villages_per_cluster,
                text: `Village count <b>${villageCount}</b> sits in ` +
                      `[${CLUSTER_RULES.min_villages_per_cluster}-${CLUSTER_RULES.max_villages_per_cluster}]`,
            },
            {
                ok: span <= CLUSTER_RULES.max_radius_km,
                text: `Max pairwise span <b>${span} km</b> is within the ${CLUSTER_RULES.max_radius_km} km radius cap`,
            },
            {
                ok: minPerVill >= CLUSTER_RULES.min_members_per_village,
                text: `Every village has at least ${CLUSTER_RULES.min_members_per_village} interested member ` +
                      `(smallest here: <b>${isFinite(minPerVill) ? minPerVill : 0}</b>)`,
            },
        ];
        return rules.map(r =>
            `<li style="margin: 3px 0;">${tick(r.ok)} ${r.text}</li>`).join('');
    }

    function renderClusterSummaryPanel(c) {
        const el = $('cluster-side-panel');
        if (!el) return;
        local.activeClusterId = c && c.cluster_id;
        const villages = (c.villages || []).map(v =>
            `<li>${escapeHtml(v.vill_name)} <small>(${(v.members || 0).toLocaleString()} members)</small></li>`).join('');
        const status = c.finalized
            ? '<span style="color:#22AD7A; font-weight: 600">Finalised</span>'
            : '<span style="color:#888">Proposed</span>';
        const row = (label, value) =>
            `<div class="cluster-side-row"><span class="label">${escapeHtml(label)}</span><span class="value">${value}</span></div>`;

        const others = otherCommoditiesFor(c);
        const othersHtml = others.length ? `
            <details class="cluster-side-other" open>
                <summary>Other commodities in these villages (${others.reduce((s, r) => s + r.total, 0).toLocaleString()})</summary>
                <div style="font-size: 12px; margin-top: 6px;">
                    ${others.map(r =>
                        `<div class="cluster-side-row">
                            <span class="label">${escapeHtml(COMMODITY_LABEL[r.commodity] || r.commodity)}</span>
                            <span class="value">${r.total.toLocaleString()}</span>
                        </div>`).join('')}
                </div>
            </details>` : `<div class="cluster-side-empty" style="font-size:12px">No other commodities in these villages.</div>`;

        el.innerHTML = `
            <button type="button" class="cluster-side-back" id="cluster-side-back-btn">
                <i class="bi bi-arrow-left"></i> Back to block summary
            </button>
            <h3><i class="bi bi-diagram-3"></i> ${c.cluster_num != null ? `Cluster ${c.cluster_num}` : escapeHtml(c.cluster_id)}</h3>
            <div class="cluster-side-sub">${escapeHtml(COMMODITY_LABEL[c.commodity] || c.commodity)} · ${escapeHtml(c.block_name)}${c.cluster_num != null ? ` · <span style="color:#888">${escapeHtml(c.cluster_id)}</span>` : ''}</div>
            <div class="cluster-side-section">Cluster</div>
            ${row('Members', (c.total_members || 0).toLocaleString())}
            ${row('Villages', (c.villages || []).length.toLocaleString())}
            ${row('Max span', `${c.max_span_km} km`)}
            ${row('Status', status)}
            ${(c.pashu_sakhi || c.block_coordinator) ? `
                <div class="cluster-side-section">Assigned</div>
                ${c.pashu_sakhi ? row('Pashu Sakhi', escapeHtml(c.pashu_sakhi)) : ''}
                ${c.block_coordinator ? row('Block coord', escapeHtml(c.block_coordinator)) : ''}
            ` : ''}
            <div class="cluster-side-section">Villages in this cluster</div>
            <ul style="margin: 4px 0 0 18px; padding: 0; font-size: 13px;">${villages || '<li><i>(none)</i></li>'}</ul>
            <div class="cluster-side-section">Other commodities in these villages</div>
            ${othersHtml}
            <div class="cluster-side-section">Why this is a cluster</div>
            <ul style="margin: 4px 0 0 18px; padding: 0; font-size: 12px; list-style: none;">
                ${ruleExplanation(c)}
            </ul>
        `;
        const back = $('cluster-side-back-btn');
        if (back) back.addEventListener('click', () => {
            local.activeClusterId = null;
            renderBlockSummaryPanel(local.lastBlockSummary);
        });
    }

    async function loadBlockSummary(blockName) {
        if (!blockName) { renderSidePanelEmpty(); return; }
        try {
            const r = await fetch(`/api/blocks/${encodeURIComponent(blockName)}/shg-summary`);
            const s = await r.json();
            renderBlockSummaryPanel(s);
        } catch (e) {
            console.warn('block summary fetch failed:', e);
            renderSidePanelEmpty('Could not load summary.');
        }
    }

    async function loadVillagesForBlock(canonical) {
        setBusy(`Loading villages for ${canonical}…`);
        try {
            const r = await fetch(`/api/villages/geojson?block=${encodeURIComponent(canonical)}`);
            local.villageFeatures = await r.json();
        } catch (e) {
            console.warn('Village geojson fetch failed:', e);
            local.villageFeatures = null;
        }
    }

    // ---- Modal open/close ----

    /**
     * Load villages, boundaries, clusters for `canonical` block and render them.
     * Pulled out so the dropdown can re-init without closing/reopening the modal.
     */
    async function loadBlockIntoModal(canonical) {
        showPageLoader(`Loading ${canonical}…`);
        try {
            local.currentBlock = canonical;
            local.currentDistrict = districtForBlock(canonical) || local.currentDistrict;
            local.currentCommodity = '';

            const blockLabel = $('cluster-modal-block');
            if (blockLabel) blockLabel.textContent = canonical;
            const commoditySel = $('block-commodity-select');
            if (commoditySel) commoditySel.value = '';

            // Modal flips display:none -> flex on open; layout has not settled
            // yet, so the map container has zero dimensions until the next paint.
            await new Promise(r => requestAnimationFrame(r));
            await new Promise(r => requestAnimationFrame(r));

            buildMap();
            local.modalMap.invalidateSize();

            await renderBoundaries();
            await loadVillagesForBlock(canonical);
            renderVillageLayer();
            loadBlockSummary(canonical);

            setTimeout(() => {
                if (!local.modalMap) return;
                local.modalMap.invalidateSize();
                if (local.boundaryBounds && local.boundaryBounds.isValid()) {
                    local.modalMap.fitBounds(local.boundaryBounds, { padding: [40, 40] });
                }
            }, 150);

            showLegend();
            updateSummary(0);
            updateDownloadHref();
        } finally {
            hidePageLoader();
        }
    }

    async function openModal() {
        const modal = $('cluster-modal');
        if (!modal) return;
        modal.style.display = 'flex';

        await Promise.all([
            ensureBlocksWithVillages(),
            ensureBlocksGeojson(),
            ensureAllLocations(),
        ]);

        const raw = activeBlockName();
        const canonical = (await blockHasVillages(raw))
            // Outer block has no village data: fall back to the first block that does.
            || (local.blocksRich && local.blocksRich[0] && local.blocksRich[0].block_name);
        if (!canonical) return;

        local.currentBlock = canonical;
        local.currentDistrict = districtForBlock(canonical);
        populateModalDropdowns();
        await loadBlockIntoModal(canonical);
    }

    function closeModal() {
        const modal = $('cluster-modal');
        if (modal) modal.style.display = 'none';
        teardownMap();
        local.currentBlock = null;
        local.currentCommodity = '';
        local.villageFeatures = null;
        local.lastBlockSummary = null;
        local.activeClusterId = null;
        renderSidePanelEmpty();
    }

    // ---- Event handlers ----

    async function handleCommodityChange() {
        const sel = $('block-commodity-select');
        local.currentCommodity = (sel && sel.value) || '';
        renderVillageLayer();
        await renderClusterLayer();
        updateDownloadHref();
    }

    async function handleUpload(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file || !local.currentBlock) return;
        showPageLoader(`Uploading ${file.name}…`);
        const text = await file.text();
        const params = new URLSearchParams({ block: local.currentBlock });
        if (local.currentCommodity) params.set('commodity', local.currentCommodity);
        try {
            const r = await fetch('/api/clusters/import?' + params.toString(), {
                method: 'POST',
                headers: { 'Content-Type': 'text/csv' },
                body: text,
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.error || 'Upload failed');
            ev.target.value = '';
            await renderClusterLayer();
            alert(`Imported ${data.imported} cluster${data.imported === 1 ? '' : 's'}.`);
        } catch (e) {
            alert('Upload failed: ' + e.message);
        } finally {
            hidePageLoader();
        }
    }

    async function handleRegenerate() {
        if (!local.currentBlock) return;
        const scopeLabel = local.currentCommodity
            ? `${local.currentBlock} (${COMMODITY_LABEL[local.currentCommodity]})`
            : `${local.currentBlock} (all commodities)`;
        if (!confirm(`Regenerate clusters for ${scopeLabel}? This replaces stored clusters in scope.`)) return;
        const btn = $('cluster-regenerate');
        const restoreBtn = setButtonBusy(btn, 'Regenerating…');
        showPageLoader(`Regenerating clusters for ${scopeLabel}…`);
        try {
            const body = { block: local.currentBlock };
            if (local.currentCommodity) body.commodity = local.currentCommodity;
            const r = await fetch('/api/clusters/regenerate?admin=1', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Admin': '1' },
                body: JSON.stringify(body),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.error || 'Regenerate failed');
            await renderClusterLayer();
        } catch (e) {
            alert('Regenerate failed: ' + e.message);
        } finally {
            restoreBtn();
            hidePageLoader();
        }
    }

    async function handleFinalizeClick(ev, btnArg) {
        const btn = btnArg || (ev && ev.target && ev.target.closest && ev.target.closest('.cluster-finalize-btn'));
        if (!btn) return;
        const id = btn.dataset.clusterId;
        const wasFinalized = btn.dataset.finalized === 'true';
        const restoreBtn = setButtonBusy(btn, wasFinalized ? 'Unfinalising…' : 'Finalising…');
        try {
            const r = await fetch(`/api/clusters/${encodeURIComponent(id)}/finalize`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ finalized: !wasFinalized }),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.error || 'Finalize failed');
            await renderClusterLayer();
        } catch (e) {
            alert('Finalize failed: ' + e.message);
        } finally {
            // Button is inside the cluster popup; renderClusterLayer recreated the
            // popup so the original button is detached. Restore best-effort if still
            // in the DOM, otherwise no-op.
            try { restoreBtn(); } catch (e) {}
        }
    }

    async function handleDistrictChange() {
        const sel = $('modal-district-select');
        if (!sel) return;
        local.currentDistrict = sel.value || null;
        repopulateBlockDropdown();
        const blockSel = $('modal-block-select');
        if (blockSel && blockSel.value) {
            await loadBlockIntoModal(blockSel.value);
        }
    }

    async function handleModalBlockChange() {
        const sel = $('modal-block-select');
        if (!sel || !sel.value) return;
        // Map dropdown's display case to the canonical name MMUA uses.
        const canonical = (local.blocksByUpper && local.blocksByUpper.get(sel.value.toUpperCase())) || sel.value;
        await loadBlockIntoModal(canonical);
    }

    function renderWorkflowHelp(lang) {
        const overlay = $('workflow-help-overlay');
        if (!overlay) return;
        const tabsEl = overlay.querySelector('.workflow-help-tabs');
        const bodyEl = overlay.querySelector('.workflow-help-body');
        if (!tabsEl || !bodyEl) return;

        const codes = Object.keys(WORKFLOW_HELP);
        const active = lang || codes[0];
        tabsEl.innerHTML = codes.map(code =>
            `<button data-lang="${code}" class="${code === active ? 'active' : ''}">${WORKFLOW_HELP[code].label}</button>`
        ).join('');
        const sections = WORKFLOW_HELP[active].sections.map(([title, body]) =>
            `<h4>${title}</h4><p>${body}</p>`
        ).join('');
        bodyEl.innerHTML = sections;

        tabsEl.querySelectorAll('button').forEach(b => {
            b.onclick = () => renderWorkflowHelp(b.dataset.lang);
        });
    }

    function openWorkflowHelp() {
        renderWorkflowHelp();
        const overlay = $('workflow-help-overlay');
        if (overlay) overlay.style.display = 'flex';
    }
    function closeWorkflowHelp() {
        const overlay = $('workflow-help-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    function openUploadDialog() {
        const overlay = $('upload-dialog-overlay');
        if (!overlay) return;
        // Refresh template href + filename label in case scope changed.
        const link = $('upload-dialog-template');
        if (link) {
            const params = new URLSearchParams();
            if (local.currentBlock) params.set('block', local.currentBlock);
            if (local.currentCommodity) params.set('commodity', local.currentCommodity);
            link.href = '/api/clusters/export.csv?' + params.toString();
        }
        const fname = $('upload-dialog-filename');
        if (fname) fname.textContent = '';
        overlay.style.display = 'flex';
    }
    function closeUploadDialog() {
        const overlay = $('upload-dialog-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    function isPageMode() {
        return document.body && document.body.dataset && document.body.dataset.mode === 'page';
    }

    async function autoMountPageMode() {
        // The page already shows the modal-inner content full-viewport; just load data.
        await Promise.all([
            ensureBlocksWithVillages(),
            ensureBlocksGeojson(),
            ensureAllLocations(),
        ]);
        const requested = (document.body.dataset.initialBlock || '').toUpperCase();
        let canonical = null;
        if (requested && local.blocksByUpper.has(requested)) {
            canonical = local.blocksByUpper.get(requested);
        } else if (local.blocksRich && local.blocksRich.length) {
            canonical = local.blocksRich[0].block_name;
        }
        if (!canonical) return;
        local.currentBlock = canonical;
        local.currentDistrict = districtForBlock(canonical);
        populateModalDropdowns();
        await loadBlockIntoModal(canonical);

        // Honour ?commodity=... in the URL.
        const initialCommodity = document.body.dataset.initialCommodity || '';
        if (initialCommodity) {
            const sel = $('block-commodity-select');
            if (sel) {
                sel.value = initialCommodity;
                await handleCommodityChange();
            }
        }
    }

    function init() {
        const openBtn = $('open-cluster-planner');
        const closeBtn = $('close-cluster-planner');
        const sel = $('block-commodity-select');
        const upload = $('cluster-upload');
        const regen = $('cluster-regenerate');
        const modal = $('cluster-modal');
        const districtSel = $('modal-district-select');
        const blockSel = $('modal-block-select');
        const workflowOpen = $('open-workflow-help');
        const workflowClose = $('close-workflow-help');
        const workflowOverlay = $('workflow-help-overlay');

        // The "Cluster Planning" link is now an <a href> that navigates to
        // /<district>/<block>/clustering - no JS click handler needed. The
        // close button only exists in modal mode (the partial omits it in page mode).
        if (closeBtn) closeBtn.addEventListener('click', closeModal);
        if (sel) sel.addEventListener('change', handleCommodityChange);
        if (upload) upload.addEventListener('change', handleUpload);
        if (regen) {
            regen.addEventListener('click', handleRegenerate);
            if (IS_ADMIN) regen.style.display = '';
        }
        const searchInput = $('cluster-search');
        if (searchInput) {
            searchInput.addEventListener('input', handleSearchInput);
            searchInput.addEventListener('keydown', handleSearchInput);
        }
        if (districtSel) districtSel.addEventListener('change', handleDistrictChange);
        if (blockSel) blockSel.addEventListener('change', handleModalBlockChange);
        if (workflowOpen) workflowOpen.addEventListener('click', openWorkflowHelp);
        if (workflowClose) workflowClose.addEventListener('click', closeWorkflowHelp);
        if (workflowOverlay) workflowOverlay.addEventListener('click', (ev) => {
            if (ev.target === workflowOverlay) closeWorkflowHelp();
        });

        const uploadDialogOpen = $('open-upload-dialog');
        const uploadDialogClose = $('close-upload-dialog');
        const uploadDialogOverlay = $('upload-dialog-overlay');
        const uploadDialogPick = $('upload-dialog-pick');
        if (uploadDialogOpen) uploadDialogOpen.addEventListener('click', openUploadDialog);
        if (uploadDialogClose) uploadDialogClose.addEventListener('click', closeUploadDialog);
        if (uploadDialogOverlay) uploadDialogOverlay.addEventListener('click', (ev) => {
            if (ev.target === uploadDialogOverlay) closeUploadDialog();
        });
        if (uploadDialogPick && upload) {
            // The "Choose file & upload" button in the dialog triggers the hidden
            // file input. The existing handleUpload listener picks it up from there.
            uploadDialogPick.addEventListener('click', () => upload.click());
        }
        if (upload) {
            upload.addEventListener('change', (ev) => {
                const fname = $('upload-dialog-filename');
                if (fname && ev.target.files && ev.target.files[0]) {
                    fname.textContent = `Uploading: ${ev.target.files[0].name}`;
                }
                // Close the dialog once the file is chosen — handleUpload runs the request.
                setTimeout(closeUploadDialog, 200);
            });
        }
        if (modal) {
            modal.addEventListener('click', (ev) => {
                if (ev.target === modal) closeModal();
            });
            // Click delegation for the Finalise button rendered inside cluster tooltips.
            modal.addEventListener('click', handleFinalizeClick);
        }
        document.addEventListener('keydown', (ev) => {
            if (ev.key !== 'Escape') return;
            // Layered overlays: close the topmost one first, fall through.
            const upload = $('upload-dialog-overlay');
            if (upload && upload.style.display !== 'none') return closeUploadDialog();
            const help = $('workflow-help-overlay');
            if (help && help.style.display !== 'none') return closeWorkflowHelp();
            const m = $('cluster-modal');
            if (m && m.style.display !== 'none' && !isPageMode()) closeModal();
        });

        // Show/hide the open button as the user navigates between blocks.
        const target = $('block-mini-map');
        if (target) {
            const observer = new MutationObserver(() => refreshOpenButton());
            observer.observe(target, { childList: true, subtree: true });
        }
        if (isPageMode()) {
            // Standalone /clustering page - bypass the open-button flow entirely.
            autoMountPageMode();
        } else {
            refreshOpenButton();
            let tries = 0;
            const poll = setInterval(() => {
                refreshOpenButton();
                if (++tries > 30) clearInterval(poll);
            }, 250);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
