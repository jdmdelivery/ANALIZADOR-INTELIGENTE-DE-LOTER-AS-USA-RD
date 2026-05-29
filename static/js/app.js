(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);

    const selectCountry = $('selectCountry');
    const selectState = $('selectState');
    const selectLottery = $('selectLottery');
    const stateGroup = $('stateGroup');
    const mainSplit = $('mainSplit');
    const recentResults = $('recentResults');
    const drawButtons = $('drawButtons');
    const selectDraw = $('selectDraw');
    const drawSelectRow = $('drawSelectRow');
    const loadingOverlay = $('loadingOverlay');
    const liveIndicator = $('liveIndicator');
    const latestDateBadge = $('latestDateBadge');
    const toggleResultsMode = $('toggleResultsMode');
    const btnRefreshResultsNow = $('btnRefreshResultsNow');
    const refreshResultsStatus = $('refreshResultsStatus');
    const leidsaSection = $('leidsaSection');
    const leidsaBoard = $('leidsaBoard');
    const leidsaRefreshStatus = $('leidsaRefreshStatus');
    const btnRefreshLeidsa = $('btnRefreshLeidsa');
    const btnRefreshLeidsaHistory = $('btnRefreshLeidsaHistory');
    const btnRefreshRdAll = $('btnRefreshRdAll');
    const btnRefreshRdHistoryFull = $('btnRefreshRdHistoryFull');
    const historyDaysFilters = $('historyDaysFilters');

    if (!selectCountry || !selectLottery) return;

    let currentLotteryId = null;
    let currentLotteryName = '';
    let currentCountry = '';
    let resultsViewMode = 'latest';
    let historyDays = 90;
    let refreshTimer = null;
    let activeDrawBtn = null;
    let currentDrawButtons = [];
    let currentDrawName = '';
    let lastResultsError = '';
    let refreshResultsInProgress = false;

    const TANDA_CSS = {
        'mañana': 'rc-manana',
        'tarde': 'rc-tarde',
        'tardía': 'rc-tardia',
        'noche': 'rc-noche',
        'Midday': 'rc-midday',
        'Evening': 'rc-evening',
        'Powerball draw': 'rc-default',
        'Mega Millions draw': 'rc-default',
    };

    initSidebar();
    initNavShortcuts();
    initNavActive();

    selectCountry.addEventListener('change', onCountryChange);
    selectState.addEventListener('change', loadLotteries);
    selectLottery.addEventListener('change', onLotteryChange);
    if (toggleResultsMode) {
        toggleResultsMode.addEventListener('click', () => {
            resultsViewMode = resultsViewMode === 'latest' ? 'all' : 'latest';
            toggleResultsMode.textContent = resultsViewMode === 'latest' ? 'Ver historial' : 'Solo fecha actual';
            loadRecentResults();
        });
    }
    if (btnRefreshResultsNow) {
        btnRefreshResultsNow.addEventListener('click', refreshResultsNow);
    }
    if (btnRefreshLeidsa) {
        btnRefreshLeidsa.addEventListener('click', refreshLeidsaNow);
    }
    if (btnRefreshRdAll) {
        btnRefreshRdAll.addEventListener('click', refreshRdAllNow);
    }
    if (btnRefreshRdHistoryFull) {
        btnRefreshRdHistoryFull.addEventListener('click', refreshRdHistoryFullNow);
    }
    if (btnRefreshLeidsaHistory) {
        btnRefreshLeidsaHistory.addEventListener('click', refreshLeidsaHistoryNow);
    }
    if (historyDaysFilters) {
        historyDaysFilters.querySelectorAll('.history-days-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                historyDaysFilters.querySelectorAll('.history-days-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                historyDays = parseInt(btn.dataset.days, 10) || 90;
                if (resultsViewMode === 'all') loadRecentResults();
            });
        });
    }

    function initSidebar() {
        const sidebar = $('sidebar');
        const overlay = $('sidebarOverlay');
        const toggle = $('sidebarToggle');
        if (!toggle) return;
        toggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
            overlay.classList.toggle('open');
        });
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('open');
        });
    }

    function initNavShortcuts() {
        document.querySelectorAll('.nav-link[data-nav="usa"]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                selectCountry.value = 'USA';
                onCountryChange();
                scrollToEl('filtros');
            });
        });
        document.querySelectorAll('.nav-link[data-nav="rd"]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                selectCountry.value = 'RD';
                onCountryChange();
                scrollToEl('filtros');
            });
        });
    }

    function initNavActive() {
        const links = document.querySelectorAll('.sidebar-nav .nav-link[href^="/#"]');
        links.forEach(link => {
            link.addEventListener('click', () => {
                document.querySelectorAll('.sidebar-nav .nav-link.active').forEach(el => {
                    if (el.dataset.nav !== 'inicio') el.classList.remove('active');
                });
                link.classList.add('active');
                $('sidebar')?.classList.remove('open');
                $('sidebarOverlay')?.classList.remove('open');
            });
        });
    }

    function scrollToEl(id) {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
    }

    function onCountryChange() {
        const country = selectCountry.value;
        currentCountry = country;
        resultsViewMode = 'latest';
        resetLotterySelect();
        hideMain();

        if (country === 'USA') {
            if (leidsaSection) leidsaSection.style.display = 'none';
            loadUsaFilters();
        } else if (country === 'RD') {
            stateGroup.style.display = 'none';
            if (leidsaSection) leidsaSection.style.display = 'block';
            loadLotteries();
            loadLeidsaBoard();
        } else {
            stateGroup.style.display = 'none';
            if (leidsaSection) leidsaSection.style.display = 'none';
        }
    }

    async function loadStates(country) {
        if (!selectState) return;
        selectState.innerHTML = '<option value="">— Seleccionar estado —</option>';
        try {
            const res = await fetch(`/api/states?country=${country}`);
            const data = await res.json();
            (data.states || []).forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = s;
                selectState.appendChild(opt);
            });
            return data.states || [];
        } catch (e) {
            console.error(e);
            return [];
        }
    }

    async function loadUsaFilters() {
        if (!stateGroup) {
            await loadLotteries();
            return;
        }
        const states = await loadStates('USA');
        const hasMultiple = states.length > 1;
        stateGroup.style.display = hasMultiple ? '' : 'none';
        if (states.length === 1) {
            selectState.value = states[0];
        }
        await loadLotteries();
    }

    async function loadLotteries() {
        const country = selectCountry.value;
        if (!country) return;

        let url = `/api/lotteries?country=${country}`;
        if (country === 'USA' && selectState.value) {
            url += `&state=${encodeURIComponent(selectState.value)}`;
        }

        resetLotterySelect();
        try {
            const res = await fetch(url);
            const data = await res.json();
            const list = data.lotteries || [];
            list.forEach(lot => {
                const opt = document.createElement('option');
                opt.value = lot.id;
                opt.textContent = lot.name;
                opt.dataset.name = lot.name;
                selectLottery.appendChild(opt);
            });
            selectLottery.disabled = list.length === 0;
            if (list.length === 0) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = '— Sin loterías para este filtro —';
                selectLottery.appendChild(opt);
            }
        } catch (e) {
            console.error(e);
            selectLottery.disabled = false;
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '— Error al cargar loterías —';
            selectLottery.appendChild(opt);
        }
    }

    function resetLotterySelect() {
        selectLottery.innerHTML = '<option value="">— Seleccionar lotería —</option>';
        selectLottery.disabled = true;
        currentLotteryId = null;
        stopAutoRefresh();
    }

    function hideMain() {
        if (mainSplit) mainSplit.style.display = 'none';
        if (liveIndicator) liveIndicator.style.display = 'none';
        resetAnalysisPanel();
        setRefreshButtonVisible(false);
    }

    function setRefreshButtonVisible(show) {
        if (!btnRefreshResultsNow) return;
        btnRefreshResultsNow.style.display = show ? 'inline-block' : 'none';
        btnRefreshResultsNow.disabled = !show;
    }

    function setRefreshStatus(text, kind) {
        if (!refreshResultsStatus) return;
        refreshResultsStatus.textContent = text || '';
        refreshResultsStatus.className = 'refresh-status-msg' + (kind ? ` is-${kind}` : '');
    }

    async function refreshResultsNow() {
        if (!currentLotteryId || !btnRefreshResultsNow || refreshResultsInProgress) return;

        refreshResultsInProgress = true;
        const prevLabel = btnRefreshResultsNow.textContent;
        btnRefreshResultsNow.disabled = true;
        btnRefreshResultsNow.classList.add('is-busy');
        btnRefreshResultsNow.textContent = '⏳ Actualizando...';
        setRefreshStatus('🔄 Actualizando resultados...', 'loading');
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        const isUsa = selectCountry.value === 'USA';
        const body = {
            pais: selectCountry.value,
            country: selectCountry.value,
            state: selectState.value || '',
            loteria: currentLotteryName,
            lottery: currentLotteryName,
            days: 30,
            refresh_all_usa: isUsa,
        };

        try {
            const res = await fetch('/api/resultados/actualizar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();

            if (data.hub_url || data.status_code != null) {
                console.info('[Illinois Hub]', {
                    url: data.hub_url,
                    status_code: data.status_code,
                    from_cache: data.from_cache,
                    used_db_fallback: data.used_db_fallback,
                    saved_count: data.saved_count,
                });
            }

            await loadRecentResults(true);

            if (data.fuente === 'lotteryusa' && data.warning) {
                setRefreshStatus(
                    data.mensaje || data.message || '⚠️ Se usó fuente alternativa (LotteryUSA).',
                    'muted'
                );
                lastResultsError = '';
                return;
            }

            if (data.warning || data.used_db_fallback || data.status === 'cached_fallback' || data.cache) {
                const warnMsg = data.mensaje || data.message
                    || '⚠️ No se pudo actualizar ahora; se muestran resultados guardados.';
                setRefreshStatus(warnMsg, 'muted');
                lastResultsError = '';
                return;
            }

            if (!data.ok || data.status === 'error') {
                const hasSaved = (data.saved_count || 0) > 0;
                const errMsg = hasSaved
                    ? (data.mensaje || data.message || '⚠️ No se pudo actualizar ahora, pero se muestran resultados guardados.')
                    : (data.error || data.mensaje || data.message || '⚠️ Illinois Results Hub no respondió. Mostrando últimos resultados guardados.');
                setRefreshStatus(
                    errMsg.startsWith('⚠') ? errMsg : `⚠️ ${errMsg}`,
                    hasSaved ? 'muted' : 'error'
                );
                lastResultsError = hasSaved ? '' : errMsg;
                return;
            }

            lastResultsError = '';
            if (data.from_cache) {
                setRefreshStatus(
                    data.message || '⚠️ Illinois Results Hub no respondió. Datos desde caché local.',
                    'muted'
                );
            } else if (data.status === 'no_new') {
                setRefreshStatus(data.message || '⚪ Sin resultados nuevos en el rango', 'muted');
            } else if (data.partial) {
                setRefreshStatus(
                    data.message || '✅ Actualizado con advertencias en algunos juegos',
                    'muted'
                );
            } else {
                const okMsg = data.mensaje || data.message
                    || (data.fuente === 'illinoislottery'
                        ? '✅ Actualizado correctamente'
                        : '✅ Resultados actualizados correctamente');
                setRefreshStatus(
                    okMsg.startsWith('✅') ? okMsg : `✅ ${okMsg}`,
                    'ok'
                );
            }
        } catch (e) {
            console.error('[Illinois Hub] fetch error', e);
            setRefreshStatus(
                '⚠️ No se pudo actualizar ahora. Se mantienen los últimos resultados guardados.',
                'muted'
            );
            lastResultsError = e.message || String(e);
            await loadRecentResults(true);
        } finally {
            refreshResultsInProgress = false;
            btnRefreshResultsNow.disabled = false;
            btnRefreshResultsNow.classList.remove('is-busy');
            btnRefreshResultsNow.textContent = prevLabel;
            if (loadingOverlay) loadingOverlay.style.display = 'none';
        }
    }

    function stopAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
    }

    function startAutoRefresh() {
        stopAutoRefresh();
        liveIndicator.style.display = 'flex';
        refreshTimer = setInterval(() => {
            if (currentLotteryId) loadRecentResults(true);
        }, 60000);
    }

    async function onLotteryChange() {
        currentLotteryId = selectLottery.value;
        const opt = selectLottery.options[selectLottery.selectedIndex];
        currentLotteryName = opt?.dataset?.name || opt?.textContent || '';
        currentCountry = selectCountry.value;
        resultsViewMode = 'all';
        historyDays = 30;
        hideMain();

        if (!currentLotteryId) return;

        mainSplit.style.display = 'grid';
        resetAnalysisPanel();
        setRefreshButtonVisible(true);
        setRefreshStatus('', '');
        await Promise.all([loadRecentResults(), loadDrawButtons()]);
        startAutoRefresh();
        scrollToEl('resultados');
    }

    function tandaClass(drawName) {
        return TANDA_CSS[drawName] || 'rc-default';
    }

    function renderBallSet(main, bonus, sizeClass = 'mini') {
        const mainHtml = (main || []).map((n, i) =>
            `<span class="ball-hd ${sizeClass}" style="animation-delay:${i * 0.08}s">${escapeHtml(n)}</span>`
        ).join('');
        if (!bonus?.length) return mainHtml;
        const bonusHtml = bonus.map((n, i) =>
            `<span class="ball-hd ${sizeClass} ball-bonus" style="animation-delay:${(main.length + i + 1) * 0.08}s">${escapeHtml(n)}</span>`
        ).join('');
        return `${mainHtml}<span class="ball-plus">+</span>${bonusHtml}`;
    }

    function renderResultCard(r, showDate = true) {
        const timePart = r.time_display || r.draw_time || '';
        const tandaLine = timePart || r.draw_name || '';
        const dateLine = showDate
            ? `${escapeHtml(r.draw_date)}${tandaLine ? ' · ' + escapeHtml(tandaLine) : ''}`
            : (tandaLine ? escapeHtml(tandaLine) : '');
        return `
            <div class="result-card-hd ${tandaClass(r.draw_name)} animate-fade-in">
                <div class="rc-tanda">${escapeHtml(tandaLine)}</div>
                ${dateLine ? `<div class="rc-date">${dateLine}</div>` : ''}
                <div class="rc-balls">
                    ${renderBallSet(r.main_numbers || r.numbers, r.bonus_numbers)}
                </div>
            </div>
        `;
    }

    function renderEmptyResultsMessage(data) {
        const lotName = data?.lottery_name || currentLotteryName || 'esta lotería';
        const tanda = currentDrawName ? ` / tanda «${currentDrawName}»` : '';
        if (lastResultsError) {
            return `<p class="empty-msg empty-msg-error">Error: ${escapeHtml(lastResultsError)}</p>`;
        }
        if (data?.total_in_db > 0 && currentDrawName) {
            return `<p class="empty-msg">No hay resultados para ${escapeHtml(lotName)}${escapeHtml(tanda)} en el rango seleccionado. Prueba «Ver todos» o otra tanda.</p>`;
        }
        return `<p class="empty-msg">No hay resultados guardados para ${escapeHtml(lotName)}${escapeHtml(tanda)}. Presiona «Actualizar resultados ahora» o «Actualizar resultados RD ahora» (admin) para cargar desde Conectate.</p>`;
    }

    async function loadRecentResults(silent) {
        if (!silent) {
            recentResults.innerHTML = '<p class="empty-msg">Cargando resultados...</p>';
        }
        try {
            const isRD = currentCountry === 'RD' || selectCountry.value === 'RD';
            let url = `/api/results?lottery_id=${currentLotteryId}&limit=30`;
            if (isRD) {
                url += `&mode=${resultsViewMode}`;
                if (resultsViewMode === 'all') url += `&days=${historyDays}`;
            }
            if (currentDrawName) {
                url += `&draw_name=${encodeURIComponent(currentDrawName)}`;
            }

            const res = await fetch(url);
            const data = await res.json();
            if (!data.ok) {
                lastResultsError = data.message || 'Error al cargar resultados';
                recentResults.innerHTML = renderEmptyResultsMessage(data);
                return;
            }
            lastResultsError = '';

            if (toggleResultsMode) {
                toggleResultsMode.style.display = isRD ? 'inline-block' : 'none';
                toggleResultsMode.textContent = resultsViewMode === 'latest' ? 'Ver historial' : 'Solo fecha actual';
            }
            if (historyDaysFilters) {
                historyDaysFilters.style.display = (isRD && resultsViewMode === 'all') ? 'flex' : 'none';
            }
            if (latestDateBadge) {
                if (isRD && data.latest_date && resultsViewMode === 'latest') {
                    latestDateBadge.style.display = 'inline-flex';
                    latestDateBadge.textContent = `Fecha: ${data.latest_date}`;
                } else {
                    latestDateBadge.style.display = 'none';
                }
            }

            if (isRD && resultsViewMode === 'all' && data.groups?.length) {
                recentResults.innerHTML = data.groups.map(g => `
                    <div class="date-group">
                        <div class="date-group-header">${escapeHtml(g.draw_date)}</div>
                        <div class="results-grid-inner">
                            ${g.results.map(r => renderResultCard(r, false)).join('')}
                        </div>
                    </div>
                `).join('');
                return;
            }

            const list = data.results || [];
            if (!list.length && !(data.groups && data.groups.length)) {
                recentResults.innerHTML = renderEmptyResultsMessage(data);
                return;
            }

            recentResults.innerHTML = list.map(r => renderResultCard(r, true)).join('');
        } catch (e) {
            lastResultsError = e.message || String(e);
            if (!silent) recentResults.innerHTML = `<p class="empty-msg empty-msg-error">Error al cargar resultados: ${escapeHtml(lastResultsError)}</p>`;
        }
    }

    function clearDrawScheduleUi() {
        drawButtons.innerHTML = '';
        currentDrawButtons = [];
        if (selectDraw) {
            selectDraw.innerHTML = '<option value="">— Horario del sorteo —</option>';
            selectDraw.value = '';
        }
        if (drawSelectRow) drawSelectRow.style.display = 'none';
    }

    function selectDrawSchedule(btn, buttonEl) {
        if (activeDrawBtn) activeDrawBtn.classList.remove('active');
        if (buttonEl) {
            buttonEl.classList.add('active');
            activeDrawBtn = buttonEl;
        }
        if (selectDraw && btn.draw_name) {
            selectDraw.value = btn.draw_name;
        }
        currentDrawName = btn.draw_name || '';
        loadRecentResults(true);
        getPrediction(btn);
    }

    function renderDrawScheduleButtons(buttons) {
        clearDrawScheduleUi();
        if (!buttons.length) {
            drawButtons.innerHTML = '<p class="empty-msg">No hay horarios configurados para esta lotería.</p>';
            return;
        }

        currentDrawButtons = buttons;
        if (drawSelectRow) drawSelectRow.style.display = 'flex';

        buttons.forEach(btn => {
            const timeLine = btn.time_display || btn.time || '';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `btn-tanda ${btn.css || 'tanda-default'}`;
            button.innerHTML = `
                <span class="tanda-emoji">${btn.emoji || '🎱'}</span>
                <span class="tanda-label tanda-label-time">${escapeHtml(timeLine)}</span>
            `;
            button.dataset.drawName = btn.draw_name;
            button.title = btn.schedule_label || timeLine || btn.draw_name;
            button.addEventListener('click', () => selectDrawSchedule(btn, button));
            drawButtons.appendChild(button);

            if (selectDraw) {
                const opt = document.createElement('option');
                opt.value = btn.draw_name;
                opt.textContent = timeLine;
                opt.dataset.time = timeLine;
                selectDraw.appendChild(opt);
            }
        });

        if (selectDraw && !selectDraw.dataset.bound) {
            selectDraw.dataset.bound = '1';
            selectDraw.addEventListener('change', () => {
                const drawName = selectDraw.value;
                if (!drawName) return;
                const btn = currentDrawButtons.find(b => b.draw_name === drawName);
                if (!btn) return;
                const buttonEl = drawButtons.querySelector(`[data-draw-name="${CSS.escape(drawName)}"]`);
                selectDrawSchedule(btn, buttonEl);
            });
        }
    }

    async function loadDrawButtons() {
        clearDrawScheduleUi();
        try {
            const res = await fetch(`/api/draw-times?lottery_id=${currentLotteryId}`);
            const data = await res.json();
            renderDrawScheduleButtons(data.buttons || []);
        } catch (e) {
            console.error(e);
        }
    }

    function resetAnalysisPanel() {
        $('analysisPlaceholder').style.display = 'block';
        $('analysisContent').style.display = 'none';
        $('analysisError').style.display = 'none';
        if (activeDrawBtn) {
            activeDrawBtn.classList.remove('active');
            activeDrawBtn = null;
        }
        if (selectDraw) selectDraw.value = '';
        currentDrawName = '';
    }

    function showLoading(show) {
        if (!loadingOverlay) return;
        loadingOverlay.style.display = show ? 'flex' : 'none';
    }

    function renderStatNumbers(containerId, numbers) {
        const el = $(containerId);
        if (!el) return;
        if (!numbers?.length) {
            el.innerHTML = '<span class="stat-chip">—</span>';
            return;
        }
        el.innerHTML = numbers.map(n => `<span class="stat-chip">${escapeHtml(n)}</span>`).join('');
    }

    function renderStatDetails(containerId, items, typeClass) {
        const el = $(containerId);
        if (!el) return;
        if (!items?.length) {
            el.innerHTML = '<span class="stat-chip">—</span>';
            return;
        }
        el.innerHTML = items.map(item => {
            const trend = item.trend_icon
                ? `<span class="stat-trend-badge" title="${escapeHtml(item.trend_label || '')}">${item.trend_icon}</span>`
                : '';
            const lastSeen = item.last_seen_text
                ? `<span class="stat-detail-sub">${escapeHtml(item.last_seen_text)}</span>`
                : '';
            return `
                <div class="stat-detail-card ${typeClass}">
                    <div class="stat-detail-head">
                        <span class="stat-detail-num">${escapeHtml(item.number)}</span>
                        ${trend}
                    </div>
                    <p class="stat-detail-text">${escapeHtml(item.summary || '')}</p>
                    <div class="stat-detail-meta">
                        <span>${escapeHtml(String(item.count ?? 0))} veces</span>
                        <span>${escapeHtml(String(item.percentage ?? 0))}%</span>
                        <span>freq. ${escapeHtml(String(item.frequency ?? item.count ?? 0))}</span>
                    </div>
                    ${lastSeen}
                </div>
            `;
        }).join('');
    }

    function setStatWindowHint(windowSize) {
        const hint = windowSize ? `(últimos ${windowSize} sorteos)` : '';
        ['statHotWindow', 'statColdWindow', 'statOverdueWindow'].forEach(id => {
            const el = $(id);
            if (el) el.textContent = hint;
        });
    }

    async function getPrediction(btn) {
        showLoading(true);
        $('analysisPlaceholder').style.display = 'none';
        $('analysisContent').style.display = 'none';
        $('analysisError').style.display = 'none';

        const isUsa = selectCountry.value === 'USA';
        const controller = isUsa ? new AbortController() : null;
        let timeoutId = null;
        if (controller) {
            timeoutId = setTimeout(() => controller.abort(), 15000);
        }

        try {
            const fetchOpts = controller ? { signal: controller.signal } : {};
            const res = await fetch(
                `/api/prediction?lottery_id=${currentLotteryId}&draw_name=${encodeURIComponent(btn.draw_name)}`,
                fetchOpts
            );
            let data;
            try {
                data = await res.json();
            } catch (parseErr) {
                throw new Error('Respuesta inválida del servidor');
            }

            if (!res.ok && !data?.ok) {
                $('analysisError').style.display = 'block';
                $('analysisErrorMsg').textContent = data?.message || '⚠️ No se pudo completar el análisis.';
                return;
            }

            if (!data.ok) {
                $('analysisError').style.display = 'block';
                $('analysisErrorMsg').textContent = data.message || 'No hay suficientes datos históricos.';
                return;
            }

            const drawLabel = (data.draw_display || btn.label || btn.draw_name);
            const recCount = data.recommend_count || (data.generated_numbers || []).length;
            const lotName = data.lottery || currentLotteryName;
            const titleEl = $('predictionTitle');
            if (titleEl) {
                titleEl.textContent = `Recomendación ${lotName} — ${recCount} números`;
            }
            const drawSub = $('predictionDraw');
            if (drawSub) {
                drawSub.textContent = drawLabel;
            }

            const warnEl = $('predictionWarning');
            if (warnEl) {
                const dup = (data.duplicates_found || []).length;
                let warnText = data.warning || '';
                if (dup > 0) {
                    warnText = `Nota: combinación con repetición limitada (${dup}). ${warnText}`.trim();
                }
                if (warnText) {
                    warnEl.textContent = warnText;
                    warnEl.style.display = 'block';
                } else {
                    warnEl.style.display = 'none';
                }
            }

            const scheduleEl = $('predictionSchedule');
            if (data.schedule_label) {
                scheduleEl.innerHTML = `
                    <span class="schedule-prefix">📌 Recomendado para:</span>
                    <span class="schedule-value">${escapeHtml(data.schedule_label)}</span>
                `;
            } else {
                const slotEmoji = data.schedule_emoji || '🎱';
                scheduleEl.textContent = `${slotEmoji} ${currentLotteryName} — ${drawLabel}`;
            }

            const basisEl = $('predictionBasis');
            if (basisEl) {
                basisEl.textContent = data.analysis_basis || 'Basado en análisis histórico y tendencias recientes';
            }

            const bonus = data.bonus_numbers || (data.generated_bonus ? [data.generated_bonus] : []);
            $('predictionBalls').innerHTML = renderBallSet(data.generated_numbers, bonus, 'large');

            $('predictionReason').textContent = data.analysis_text || '';

            const confEl = $('predictionConfidence');
            const confLabel = data.confidence_label
                || ({ alto: 'Alto', medio: 'Medio', bajo: 'Bajo' }[data.confidence_level] || 'Bajo');
            confEl.textContent = `Nivel: ${confLabel}`;
            confEl.className = `confidence-badge confidence-${data.confidence_level || 'bajo'}`;

            $('predictionScore').textContent = data.score ?? '—';
            $('predictionHistoric').textContent = data.total_results ? `${data.total_results} sorteos` : '—';
            $('predictionDate').textContent = data.created_at ? `Generado: ${data.created_at}` : '';

            const windowSize = data.analysis_window || 25;
            setStatWindowHint(windowSize);

            if (data.hot_numbers_detail?.length) {
                renderStatDetails('statHot', data.hot_numbers_detail, 'stat-hot');
            } else {
                renderStatNumbers('statHot', data.hot_numbers);
            }
            if (data.cold_numbers_detail?.length) {
                renderStatDetails('statCold', data.cold_numbers_detail, 'stat-cold');
            } else {
                renderStatNumbers('statCold', data.cold_numbers);
            }
            if (data.overdue_numbers_detail?.length) {
                renderStatDetails('statOverdue', data.overdue_numbers_detail, 'stat-overdue');
            } else {
                renderStatNumbers('statOverdue', data.overdue_numbers);
            }

            $('analysisContent').style.display = 'block';
            scrollToEl('analisis');
        } catch (e) {
            $('analysisError').style.display = 'block';
            const timedOut = e && (e.name === 'AbortError' || String(e.message || '').includes('aborted'));
            $('analysisErrorMsg').textContent = timedOut
                ? '⚠️ No se pudo completar el análisis.'
                : (e.message || '⚠️ No se pudo completar el análisis.');
            console.error(e);
        } finally {
            if (timeoutId) clearTimeout(timeoutId);
            showLoading(false);
        }
    }

    function setLeidsaStatus(text, kind) {
        if (!leidsaRefreshStatus) return;
        leidsaRefreshStatus.textContent = text || '';
        leidsaRefreshStatus.className = 'refresh-status-msg' + (kind ? ` is-${kind}` : '');
    }

    function renderLeidsaDebugPanel(debug, liveOk, usingCache) {
        if (!debug) return '';
        const statusLine = debug.status_label || (debug.status_code ? `STATUS ${debug.status_code}` : 'STATUS ERROR');
        const errBlock = debug.error
            ? `<div class="leidsa-debug-err">❌ Error: ${escapeHtml(String(debug.error))}</div>`
            : '';
        const cacheNote = usingCache ? '<div class="leidsa-debug-cache">📦 Mostrando últimos resultados guardados (caché)</div>' : '';
        return `
            <div class="leidsa-debug-panel" role="status" aria-live="polite">
                <div class="leidsa-debug-line">${escapeHtml(statusLine)}</div>
                <div class="leidsa-debug-line">🔍 Parser: ${escapeHtml(String(debug.parser || '—'))}</div>
                <div class="leidsa-debug-line">⚙️ Método: ${escapeHtml(String(debug.method || '—'))}</div>
                <div class="leidsa-debug-line">📊 Resultados encontrados: ${Number(debug.results_found || 0)}</div>
                <div class="leidsa-debug-line">🕒 Último intento: ${escapeHtml(String(debug.last_attempt || '—'))}</div>
                ${errBlock}
                ${cacheNote}
            </div>
        `;
    }

    function renderLeidsaUnavailablePanel(debug, warning) {
        const d = debug || {};
        return `
            <div class="leidsa-unavailable-panel">
                <p class="leidsa-unavailable-title">⚠️ LEIDSA temporalmente no disponible</p>
                ${warning ? `<p class="leidsa-warning">${escapeHtml(warning)}</p>` : ''}
                <div class="leidsa-tech-grid">
                    <div><span class="leidsa-tech-label">STATUS:</span> ${escapeHtml(String(d.status_code ?? 'ERROR'))}</div>
                    <div><span class="leidsa-tech-label">MÉTODO:</span> ${escapeHtml(String(d.method || '—'))}</div>
                    <div><span class="leidsa-tech-label">PARSER:</span> ${escapeHtml(String(d.parser || '—'))}</div>
                    <div><span class="leidsa-tech-label">RESULTADOS:</span> ${Number(d.results_found || 0)}</div>
                </div>
                ${d.error ? `<p class="leidsa-debug-err">❌ ${escapeHtml(String(d.error))}</p>` : ''}
            </div>
        `;
    }

    async function loadLeidsaBoard() {
        if (!leidsaBoard) return;
        leidsaBoard.innerHTML = '<p class="empty-msg">Cargando LEIDSA...</p>';
        try {
            const res = await fetch('/api/resultados/leidsa');
            if (res.status === 401) {
                leidsaBoard.innerHTML = '<p class="empty-msg">Inicia sesión para ver LEIDSA.</p>';
                return;
            }
            const data = await res.json();
            const board = data.board || [];
            const historial = data.historial || [];
            const debug = data.debug || {};
            let html = '';

            html += renderLeidsaDebugPanel(debug, data.live_ok, data.using_cache);

            const sinDatos = data.show_unavailable === true
                || (data.has_saved === false && !board.length && !historial.length);
            if (sinDatos && data.warning) {
                html += renderLeidsaUnavailablePanel(debug, data.warning);
            } else if (data.warning) {
                html += `<p class="leidsa-warning">${escapeHtml(data.warning)}</p>`;
            }

            if (board.length) {
                html += '<div class="leidsa-board-grid">' + board.map((item) => {
                    const nums = (item.numeros || []).join(' · ');
                    const cacheTag = item.cached ? ' <span class="leidsa-cache-tag">(caché)</span>' : '';
                    return `
                        <div class="leidsa-game-card estado-verde">
                            <div class="leidsa-game-title">🟢 ${escapeHtml(item.lottery_name)}${cacheTag}</div>
                            <div class="leidsa-game-time">${escapeHtml(item.time || '')} · ${escapeHtml(item.draw || '')}</div>
                            <div class="leidsa-game-status">Publicado</div>
                            <div class="leidsa-game-nums">${escapeHtml(nums)}</div>
                        </div>
                    `;
                }).join('') + '</div>';
            } else if (!data.warning) {
                html += '<p class="empty-msg">Sin resultados LEIDSA guardados. Use «Actualizar LEIDSA ahora» (admin).</p>';
            }

            if (historial.length) {
                html += '<h3 class="leidsa-historial-title">📋 Historial reciente LEIDSA</h3>';
                html += '<div class="leidsa-historial-list">' + historial.slice(0, 24).map((h) => {
                    const nums = (h.numeros_list || []).join(' · ');
                    const time = h.draw_time || h.time_display || '';
                    return `
                        <div class="leidsa-hist-row">
                            <span class="leidsa-hist-name">${escapeHtml(h.lottery_display || '')}</span>
                            <span class="leidsa-hist-meta">${escapeHtml(h.draw_date || '')} ${time ? '· ' + escapeHtml(time) : ''} · ${escapeHtml(h.draw_name || '')}</span>
                            <span class="leidsa-hist-nums">${escapeHtml(nums || '—')}</span>
                        </div>
                    `;
                }).join('') + '</div>';
            } else if (!data.warning) {
                html += '<p class="empty-msg">Aún no hay historial LEIDSA guardado. Use «Actualizar LEIDSA ahora».</p>';
            }

            leidsaBoard.innerHTML = html;
        } catch (e) {
            console.error(e);
            leidsaBoard.innerHTML = renderLeidsaUnavailablePanel(
                { status_code: 'ERROR', method: '—', results_found: 0, error: String(e.message || e) },
                '⚠️ LEIDSA temporalmente no disponible'
            );
        }
    }

    async function refreshLeidsaHistoryNow() {
        if (!btnRefreshLeidsaHistory) return;
        btnRefreshLeidsaHistory.disabled = true;
        const prevLabel = btnRefreshLeidsaHistory.textContent;
        btnRefreshLeidsaHistory.textContent = '⏳ Descargando historial...';
        setLeidsaStatus('📚 Recorriendo dropdowns LEIDSA (puede tardar 1-2 min)...', 'loading');
        try {
            const res = await fetch('/api/resultados/leidsa/actualizar-historial', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days: historyDays }),
            });
            const data = await res.json();
            if (!data.ok) {
                setLeidsaStatus(data.message || data.error || 'Error al actualizar historial', 'error');
            } else {
                setLeidsaStatus(
                    `📚 ${data.message || 'OK'} · ${data.results_found || 0} sorteos · ${data.inserted || 0} nuevos`,
                    'ok'
                );
            }
            await loadLeidsaBoard();
            if (currentLotteryId && currentCountry === 'RD') {
                await loadRecentResults(true);
            }
        } catch (e) {
            setLeidsaStatus(`Error historial: ${e.message || e}`, 'error');
        } finally {
            btnRefreshLeidsaHistory.disabled = false;
            btnRefreshLeidsaHistory.textContent = prevLabel;
        }
    }

    async function refreshLeidsaNow() {
        if (!btnRefreshLeidsa) return;
        btnRefreshLeidsa.disabled = true;
        const prevLabel = btnRefreshLeidsa.textContent;
        btnRefreshLeidsa.textContent = '⏳ Actualizando...';
        setLeidsaStatus('🔄 Conectando con leidsa.com...', 'loading');
        try {
            const res = await fetch('/api/resultados/leidsa/actualizar', { method: 'POST' });
            const data = await res.json();
            if (!data.ok) {
                let detail = data.message || 'Leidsa no respondió, intenta de nuevo';
                if (data.status_code) detail += ` · HTTP ${data.status_code}`;
                if (data.parser) detail += ` · ${data.parser}`;
                if (data.error) detail += ` · ${data.error}`;
                if (data.blocking_type) detail += ` · ${data.blocking_type}`;
                setLeidsaStatus(detail, 'error');
                await loadLeidsaBoard();
                return;
            }
            setLeidsaStatus(
                `✅ ${data.message || 'LEIDSA actualizada'} (${data.inserted || 0} nuevos, ${data.updated || 0} act.)`,
                'ok'
            );
            await loadLeidsaBoard();
            if (currentLotteryId && currentCountry === 'RD') {
                await loadRecentResults(true);
            }
        } catch (e) {
            setLeidsaStatus(`Leidsa no respondió: ${e.message || e}`, 'error');
        } finally {
            btnRefreshLeidsa.disabled = false;
            btnRefreshLeidsa.textContent = prevLabel;
        }
    }

    async function refreshRdHistoryFullNow() {
        if (!btnRefreshRdHistoryFull) return;
        btnRefreshRdHistoryFull.disabled = true;
        const prev = btnRefreshRdHistoryFull.textContent;
        btnRefreshRdHistoryFull.textContent = '⏳ Historial 90 días...';
        setLeidsaStatus('📚 Descargando historial completo RD (90 días)...', 'loading');
        try {
            const res = await fetch('/api/resultados/rd/actualizar-historial-completo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days: 90 }),
            });
            const data = await res.json();
            if (!data.ok) {
                const err = (data.errors && data.errors.length)
                    ? data.errors.slice(0, 3).join(' · ')
                    : (data.message || 'Error al actualizar historial');
                setLeidsaStatus(err, 'error');
                lastResultsError = err;
            } else {
                lastResultsError = '';
                setLeidsaStatus(
                    data.message || 'Historial actualizado: 90 días revisados.',
                    'ok'
                );
            }
            await loadLeidsaBoard();
            if (currentLotteryId) await loadRecentResults(true);
        } catch (e) {
            setLeidsaStatus(`Error: ${e.message || e}`, 'error');
        } finally {
            btnRefreshRdHistoryFull.disabled = false;
            btnRefreshRdHistoryFull.textContent = prev;
        }
    }

    async function refreshRdAllNow() {
        if (!btnRefreshRdAll) return;
        btnRefreshRdAll.disabled = true;
        setLeidsaStatus('🔄 Actualizando historial RD (30 días)...', 'loading');
        try {
            const res = await fetch('/api/resultados/actualizar-ahora', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ country: 'RD', refresh_all_rd: true, days: 30 }),
            });
            const data = await res.json();
            if (!data.ok && !data.leidsa_ok && !(data.imported + data.updated)) {
                const err = (data.errors && data.errors.length)
                    ? data.errors.slice(0, 3).join(' · ')
                    : (data.message || 'Error al actualizar RD');
                setLeidsaStatus(err, 'error');
                lastResultsError = err;
                await loadLeidsaBoard();
                if (currentLotteryId) await loadRecentResults(true);
                return;
            }
            lastResultsError = '';
            let msg = data.message || '✅ Historial RD actualizado (30 días)';
            if (data.leidsa_ok === false && data.leidsa_error) {
                msg += ` · LEIDSA: ${data.leidsa_error}`;
            }
            if (data.errors?.length) {
                msg += ` · ${data.errors.slice(0, 2).join(' · ')}`;
            }
            setLeidsaStatus(msg, data.leidsa_ok === false ? 'muted' : 'ok');
            await loadLeidsaBoard();
            if (currentLotteryId) await loadRecentResults(true);
        } catch (e) {
            setLeidsaStatus('Error al actualizar resultados RD', 'error');
        } finally {
            btnRefreshRdAll.disabled = false;
        }
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
})();
