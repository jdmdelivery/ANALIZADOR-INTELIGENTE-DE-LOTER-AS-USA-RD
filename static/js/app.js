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
    const analysisDaysFilters = $('analysisDaysFilters');

    if (!selectCountry || !selectLottery) return;

    let currentLotteryId = null;
    let currentLotteryName = '';
    let currentCountry = '';
    let resultsViewMode = 'latest';
    let historyDays = 90;
    let analysisDays = 90;
    let refreshTimer = null;
    let activeDrawBtn = null;
    let currentDrawButtons = [];
    let currentDrawName = '';
    let lastResultsError = '';
    let refreshResultsInProgress = false;
    let lastPredictionData = null;
    let lastPredictionDrawBtn = null;
    let predictionAbortController = null;
    let predictionRequestSeq = 0;

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
    const btnCopyPlay = $('btnCopyPlay');
    const btnShowExplain = $('btnShowExplain');
    const btnAnalyzePaste = $('btnAnalyzePaste');
    const btnRecalcRecommendation = $('btnRecalcRecommendation');
    if (btnCopyPlay) btnCopyPlay.addEventListener('click', copyCurrentPlay);
    if (btnShowExplain) btnShowExplain.addEventListener('click', toggleExplainPanel);
    if (btnAnalyzePaste) btnAnalyzePaste.addEventListener('click', analyzePastedNumbers);
    if (btnRecalcRecommendation) {
        btnRecalcRecommendation.addEventListener('click', () => {
            if (!currentLotteryId || !currentDrawName) return;
            const btn = lastPredictionDrawBtn
                || currentDrawButtons.find((b) => b.draw_name === currentDrawName);
            if (btn) getPrediction(btn, { force: true });
        });
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
                syncAnalysisDaysButtons(historyDays);
                if (resultsViewMode === 'all') loadRecentResults();
                recalcPredictionIfNeeded(true);
            });
        });
    }
    if (analysisDaysFilters) {
        analysisDaysFilters.querySelectorAll('.analysis-days-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                analysisDaysFilters.querySelectorAll('.analysis-days-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                analysisDays = parseInt(btn.dataset.days, 10) || 90;
                syncHistoryDaysButtons(analysisDays);
                if (resultsViewMode === 'all') loadRecentResults();
                recalcPredictionIfNeeded(true);
            });
        });
    }

    function syncAnalysisDaysButtons(days) {
        analysisDays = days;
        if (!analysisDaysFilters) return;
        analysisDaysFilters.querySelectorAll('.analysis-days-btn').forEach((b) => {
            b.classList.toggle('active', parseInt(b.dataset.days, 10) === days);
        });
    }

    function syncHistoryDaysButtons(days) {
        historyDays = days;
        if (!historyDaysFilters) return;
        historyDaysFilters.querySelectorAll('.history-days-btn').forEach((b) => {
            b.classList.toggle('active', parseInt(b.dataset.days, 10) === days);
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

    function formatRdUpdateStatus(data) {
        const fuente = data.fuente_usada || data.fuente_label || data.fuente || 'RD';
        const tiempo = data.tiempo ?? data.elapsed_total ?? data.elapsed;
        const tiempoTxt = tiempo != null ? `${tiempo}s` : '—';
        const imported = data.imported ?? 0;
        const updated = data.updated ?? 0;
        const ultima = data.ultima_fecha || data.latest_date || '—';

        if (data.used_db_fallback || data.status === 'cached_fallback' || (data.cache && data.live_failed)) {
            const srcErr = formatSourcesTriedErrors(data.sources_tried);
            let msg = `⚠️ Caché BD (última fecha: ${ultima}). Todas las fuentes en vivo fallaron.`;
            if (srcErr) msg += ` ${srcErr}`;
            return { text: msg, kind: 'error' };
        }

        if (!data.ok || data.status === 'error') {
            const failed = (data.sources_tried || []).find((s) => !s.ok && s.error);
            const next = (data.sources_tried || []).find((s) => s.ok);
            let msg = `❌ Fuente: ${failed?.fuente_label || fuente}`;
            if (failed?.status_code) msg += ` HTTP ${failed.status_code}`;
            if (failed?.error) msg += ` — ${failed.error}`;
            if (next) msg += ` · Probando ${next.fuente_label}…`;
            return { text: msg, kind: 'error' };
        }

        if (data.warning && imported + updated > 0) {
            return {
                text: `✅ Fuente: ${fuente} · Tiempo: ${tiempoTxt} · Nuevos: ${imported} · Actualizados: ${updated} · Última fecha: ${ultima} (fuente alternativa)`,
                kind: 'muted',
            };
        }

        if (imported + updated > 0 || data.status === 'updated') {
            return {
                text: `✅ Fuente: ${fuente} · Tiempo: ${tiempoTxt} · Nuevos: ${imported} · Actualizados: ${updated} · Última fecha: ${ultima}`,
                kind: 'ok',
            };
        }

        return {
            text: data.mensaje || data.message || `⚪ Sin resultados nuevos · Última fecha: ${ultima}`,
            kind: 'muted',
        };
    }

    function formatSourcesTriedErrors(sources) {
        if (!sources?.length) return '';
        return sources
            .filter((s) => !s.ok || s.error)
            .map((s) => `${s.fuente_label || s.fuente}: ${s.error || 'sin filas'}`)
            .slice(0, 5)
            .join(' · ');
    }

    function formatUpdateError(data, res, err) {
        const parts = [];
        if (err) {
            if (err.name === 'SyntaxError') {
                parts.push(`JSON inválido: ${err.message}`);
            } else if (err.message?.includes('Failed to fetch') || err.message?.includes('NetworkError')) {
                parts.push(`Error de red / timeout: ${err.message}`);
            } else {
                parts.push(err.message || String(err));
            }
        }
        if (res && !res.ok) {
            parts.push(`HTTP ${res.status} ${res.statusText || ''}`.trim());
        }
        if (data?.error_detail) parts.push(data.error_detail);
        if (data?.error) parts.push(data.error);
        if (data?.traceback) {
            console.error('[RD UPDATE] traceback', data.traceback);
            parts.push(`Exception: ${(data.traceback.split('\n').slice(-2).join(' ')).trim()}`);
        }
        if (data?.errors?.length) {
            parts.push(data.errors.slice(0, 5).join(' · '));
        }
        const srcErr = formatSourcesTriedErrors(data?.sources_tried);
        if (srcErr) parts.push(srcErr);
        return parts.filter(Boolean).join(' · ') || 'Error desconocido al actualizar';
    }

    async function parseJsonResponse(res) {
        const text = await res.text();
        try {
            return JSON.parse(text);
        } catch (parseErr) {
            const snippet = text.replace(/\s+/g, ' ').slice(0, 240);
            throw new Error(
                `JSON inválido (HTTP ${res.status}): ${parseErr.message}. Respuesta: ${snippet}`
            );
        }
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
            refresh_all_usa: isUsa && !currentLotteryName,
        };

        try {
            const res = await fetch('/api/resultados/actualizar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await parseJsonResponse(res);
            const isRd = selectCountry.value === 'RD' || data.pais === 'DO';

            if (data.hub_url || data.status_code != null) {
                console.info('[Illinois Hub]', {
                    url: data.hub_url,
                    status_code: data.status_code,
                    from_cache: data.from_cache,
                    used_db_fallback: data.used_db_fallback,
                    saved_count: data.saved_count,
                });
            }
            if (isRd && (data.sources_tried || data.parser)) {
                console.info('[RD UPDATE]', {
                    parser: data.parser,
                    fuente: data.fuente_usada || data.fuente,
                    sources_tried: data.sources_tried,
                    live_failed: data.live_failed,
                });
            }

            await loadRecentResults(true);
            recalcPredictionIfNeeded(true);

            if (data.fuente === 'lotteryusa' && data.warning) {
                setRefreshStatus(
                    data.mensaje || data.message || '⚠️ Se usó fuente alternativa (LotteryUSA).',
                    'muted'
                );
                lastResultsError = '';
                return;
            }

            if (data.fuente === 'lotterypost' && data.warning) {
                setRefreshStatus(
                    data.mensaje || data.message || '⚠️ Se usó fuente alternativa (LotteryPost).',
                    'muted'
                );
                lastResultsError = '';
                return;
            }

            if (data.warning || data.used_db_fallback || data.status === 'cached_fallback' || data.cache) {
                if (isRd) {
                    const rd = formatRdUpdateStatus(data);
                    setRefreshStatus(rd.text, rd.kind);
                    lastResultsError = data.live_failed ? formatUpdateError(data, res) : '';
                    return;
                }
                let warnMsg = data.mensaje || data.message
                    || '⚠️ Mostrando resultados guardados.';
                if (isRd && (data.live_failed || data.errors?.length)) {
                    const detail = formatUpdateError(data, res);
                    if (detail && !warnMsg.includes(detail)) {
                        warnMsg = `${warnMsg} ${detail}`;
                    }
                }
                setRefreshStatus(warnMsg, data.live_failed ? 'error' : 'muted');
                lastResultsError = data.live_failed ? formatUpdateError(data, res) : '';
                return;
            }

            if (!data.ok || data.status === 'error') {
                if (isRd) {
                    const rd = formatRdUpdateStatus(data);
                    setRefreshStatus(rd.text, rd.kind);
                    lastResultsError = formatUpdateError(data, res);
                    return;
                }
                const hasSaved = (data.saved_count || 0) > 0;
                const detail = formatUpdateError(data, res);
                const errMsg = hasSaved && !isRd
                    ? (data.mensaje || data.message || '⚠️ No se pudo actualizar ahora, pero se muestran resultados guardados.')
                    : (detail || data.error || data.mensaje || data.message || 'Error al actualizar resultados.');
                setRefreshStatus(
                    errMsg.startsWith('⚠') || errMsg.startsWith('Error') ? errMsg : `⚠️ ${errMsg}`,
                    hasSaved && !isRd ? 'muted' : 'error'
                );
                lastResultsError = errMsg;
                return;
            }

            lastResultsError = '';
            if (isRd && (data.fuente_usada || data.sources_tried)) {
                const rd = formatRdUpdateStatus(data);
                setRefreshStatus(rd.text, rd.kind);
                return;
            }
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
            console.error('[Actualizar resultados] fetch error', e);
            const errMsg = formatUpdateError(null, null, e);
            setRefreshStatus(`⚠️ ${errMsg}`, 'error');
            lastResultsError = errMsg;
            await loadRecentResults(true);
        } finally {
            refreshResultsInProgress = false;
            btnRefreshResultsNow.disabled = false;
            btnRefreshResultsNow.classList.remove('is-busy');
            btnRefreshResultsNow.textContent = prevLabel;
            if (loadingOverlay) loadingOverlay.style.display = 'none';
        }
    }

    function recalcPredictionIfNeeded(force = true) {
        if (!currentLotteryId || !currentDrawName) return;
        const btn = lastPredictionDrawBtn
            || currentDrawButtons.find((b) => b.draw_name === currentDrawName);
        if (btn) getPrediction(btn, { force });
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
            let url = `/api/results?lottery_id=${currentLotteryId}&limit=30&t=${Date.now()}`;
            if (isRD) {
                url += `&mode=${resultsViewMode}`;
                if (resultsViewMode === 'all') url += `&days=${historyDays}`;
                // En «últimos resultados» mostrar todas las tandas del día; tanda solo en historial
                if (resultsViewMode === 'all' && currentDrawName) {
                    url += `&draw_name=${encodeURIComponent(currentDrawName)}`;
                }
            } else if (currentDrawName) {
                url += `&draw_name=${encodeURIComponent(currentDrawName)}`;
            }

            const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
            const data = await parseJsonResponse(res);

            if (res.status === 401) {
                lastResultsError = data.message || data.error || 'Sesión expirada. Vuelve a iniciar sesión.';
                recentResults.innerHTML = `<p class="empty-msg empty-msg-error">${escapeHtml(lastResultsError)}</p>`;
                return;
            }
            if (res.status === 403) {
                lastResultsError = data.message || data.error || 'Acceso denegado.';
                recentResults.innerHTML = `<p class="empty-msg empty-msg-error">${escapeHtml(lastResultsError)}</p>`;
                return;
            }
            if (!data.ok) {
                lastResultsError = data.message || data.error || 'Error al cargar resultados';
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
            if (analysisDaysFilters) {
                analysisDaysFilters.style.display = isRD ? 'flex' : 'none';
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
        getPrediction(btn, { force: true });
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
            const res = await fetch(
                `/api/draw-times?lottery_id=${currentLotteryId}&t=${Date.now()}`,
                { cache: 'no-store' }
            );
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
        lastPredictionData = null;
        lastPredictionDrawBtn = null;
        const diag = $('predictionDiag');
        if (diag) diag.style.display = 'none';
        if (activeDrawBtn) {
            activeDrawBtn.classList.remove('active');
            activeDrawBtn = null;
        }
        if (selectDraw) selectDraw.value = '';
        currentDrawName = '';
    }

    function renderPredictionDiagnostic(data) {
        const panel = $('predictionDiag');
        if (!panel || !data?.ok) return;
        const diag = data.analyzer_diagnostic || {};
        const fecha = data.fecha_usada || diag.last_result_date || '';
        const hora = data.hora_usada || diag.last_result_time || '';
        const sorteo = data.sorteo_usado || data.draw_name || '';
        const lastUsed = diag.last_result_used
            || (fecha && hora ? `${fecha} ${hora}` : data.latest_result_date)
            || '—';
        const draws = data.total_resultados_usados
            ?? data.cantidad_resultados_analizados
            ?? diag.total_resultados_usados
            ?? diag.draws_analyzed
            ?? data.total_results
            ?? data.history_count
            ?? '—';
        const avail = data.total_resultados_disponibles ?? diag.total_resultados_disponibles ?? '—';
        const rango = data.rango_usado ?? diag.rango_usado ?? `${analysisDays}_dias`;
        const hash = data.hash_datos_usados ?? diag.hash_datos_usados ?? '—';
        const recalcAt = diag.recalculated_at || data.created_at || '—';
        let source = data.fuente || diag.source || diag.data_source || data.data_source || 'BASE DE DATOS';
        const cacheFlag = data.cache_usada || (data.from_cache ? 'SI' : 'NO');
        if (cacheFlag === 'SI' || data.from_cache) {
            source = 'CACHÉ (no debe usarse)';
        }
        const lastEl = $('diagLastResult');
        const countEl = $('diagDrawCount');
        const atEl = $('diagRecalcAt');
        const srcEl = $('diagDataSource');
        if (lastEl) {
            lastEl.textContent = sorteo ? `${lastUsed} (${sorteo})` : lastUsed;
        }
        if (countEl) countEl.textContent = String(draws);
        const availEl = $('diagTotalAvail');
        const rangoEl = $('diagRango');
        const hashEl = $('diagHash');
        if (availEl) availEl.textContent = String(avail);
        if (rangoEl) rangoEl.textContent = String(rango);
        if (hashEl) hashEl.textContent = String(hash);
        if (atEl) atEl.textContent = recalcAt;
        if (srcEl) srcEl.textContent = `${source} · caché: ${cacheFlag}`;

        const isRd = selectCountry && selectCountry.value === 'RD';
        const rdRows = [
            'diagRdLoteriaRow', 'diagRdHorarioRow', 'diagRdConfRow', 'diagRdAntiRepRow',
            'diagRdAlgoRow', 'diagRdFuentesRow', 'diagRdUltActRow',
        ];
        rdRows.forEach((id) => {
            const el = $(id);
            if (el) el.style.display = isRd ? '' : 'none';
        });
        if (isRd) {
            const lotEl = $('diagRdLoteria');
            const horEl = $('diagRdHorario');
            const confEl = $('diagRdConfianza');
            const antiEl = $('diagRdAntiRep');
            const algoEl = $('diagRdAlgo');
            const fuentesEl = $('diagRdFuentes');
            const ultEl = $('diagRdUltAct');
            if (lotEl) lotEl.textContent = diag.loteria_exacta || data.lottery || '—';
            if (horEl) horEl.textContent = diag.horario_exacto || hora || '—';
            if (confEl) {
                confEl.textContent = diag.confianza_label
                    || data.confidence_label
                    || String(diag.confianza ?? data.score ?? '—');
            }
            if (antiEl) antiEl.textContent = diag.anti_repeticion || 'No se repite con recomendaciones recientes';
            if (algoEl) algoEl.textContent = diag.algoritmo_version || data.algoritmo_version || '—';
            if (fuentesEl) {
                const ok = diag.fuentes_disponibles;
                const fail = (diag.fuentes_fallidas || []).length;
                fuentesEl.textContent = ok != null ? `${ok} OK · ${fail} fallidas` : (diag.fuente_datos || '—');
            }
            if (ultEl) ultEl.textContent = diag.ultima_actualizacion_rd || '—';
            const warnDatos = $('diagRdDatosWarn');
            if (warnDatos) {
                const msg = diag.datos_insuficientes || data.low_confidence_warning || '';
                if (msg) {
                    warnDatos.textContent = msg;
                    warnDatos.style.display = 'block';
                } else {
                    warnDatos.style.display = 'none';
                }
            }
        }
        panel.style.display = 'block';
    }

    function clearPredictionDisplay() {
        lastPredictionData = null;
        $('analysisContent').style.display = 'none';
        $('analysisError').style.display = 'none';
        const balls = $('predictionBalls');
        if (balls) balls.innerHTML = '<p class="empty-msg">Calculando…</p>';
        const reason = $('predictionReason');
        if (reason) reason.textContent = '';
        const diag = $('predictionDiag');
        if (diag) diag.style.display = 'none';
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
            const summary = item.summary || item.reason || '';
            const lastSeen = item.draws_since != null
                ? `<span class="stat-detail-sub">${item.draws_since} sorteos sin salir</span>`
                : (item.last_seen_text
                    ? `<span class="stat-detail-sub">${escapeHtml(item.last_seen_text)}</span>`
                    : '');
            return `
                <div class="stat-detail-card ${typeClass}">
                    <div class="stat-detail-head">
                        <span class="stat-detail-num">${escapeHtml(item.number)}</span>
                        ${item.score != null ? `<span class="rec-combo-score ${scoreClass(item.score)}">${item.score}</span>` : ''}
                        ${trend}
                    </div>
                    <p class="stat-detail-text">${escapeHtml(summary)}</p>
                    <div class="stat-detail-meta">
                        <span>${escapeHtml(String(item.count ?? 0))} veces</span>
                        <span>${escapeHtml(String(item.percentage ?? 0))}%</span>
                        ${item.count_100 != null ? `<span>en 100: ${item.count_100}</span>` : ''}
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

    function scoreClass(score) {
        const s = Number(score) || 0;
        if (s >= 80) return 'rec-score-high';
        if (s >= 60) return 'rec-score-med';
        return 'rec-score-low';
    }

    function renderTopSection(data) {
        const el = $('recTopSection');
        if (!el) return;
        const parts = [];
        const renderComboList = (list, title, maxShow) => {
            if (!list?.length) return;
            parts.push(`<h4 class="rec-section-title">${escapeHtml(title)}</h4>`);
            list.slice(0, maxShow || list.length).forEach((c) => {
                const conf = c.confidence_label ? ` · ${c.confidence_label}` : '';
                parts.push(`<div class="rec-combo-card"><span class="rec-combo-nums">${escapeHtml((c.numbers || []).join(' '))}</span><span class="rec-combo-score ${scoreClass(c.score)}">Score ${c.score}${escapeHtml(conf)}</span></div>`);
            });
        };
        const tops = data.top_combinations || {};
        renderComboList(tops.top_5, 'Top 5 combinaciones', 5);
        renderComboList(tops.top_10, 'Top 10 combinaciones', 10);
        renderComboList(tops.top_20, 'Top 20 combinaciones', 10);

        if (data.position_picks?.length) {
            parts.push('<h4 class="rec-section-title">Análisis por posición</h4>');
            data.position_picks.forEach((pos) => {
                const best = pos.best || (pos.top_5 && pos.top_5[0]);
                const topLine = (pos.top_5 || []).map((x) => `${x.number}(${x.score})`).join(' · ');
                parts.push(`<p class="rec-paste-item"><strong>${escapeHtml(pos.label || '')}:</strong> mejor ${escapeHtml(best?.number || '—')} (score ${best?.score ?? '—'})<br><span class="rec-pos-top">${escapeHtml(topLine)}</span></p>`);
            });
        }

        const tn = data.top_numbers;
        if (tn?.top_10?.length) {
            parts.push('<h4 class="rec-section-title">Top números RD</h4>');
            ['top_10', 'top_20', 'top_50'].forEach((key) => {
                const list = tn[key];
                if (!list?.length) return;
                const label = key.replace('top_', 'Top ');
                const nums = list.slice(0, key === 'top_50' ? 20 : 10).map((x) => `${x.number}(${x.score})`).join(' · ');
                parts.push(`<p class="rec-paste-item"><strong>${label}:</strong> ${escapeHtml(nums)}</p>`);
            });
        }
        if (data.fireball?.number) {
            parts.push(`<p class="rec-paste-item"><strong>${escapeHtml(data.bonus_label || 'Fireball')}:</strong> ${escapeHtml(data.fireball.number)} (score ${data.fireball.score})</p>`);
            (data.fireball_alternatives || []).forEach((fb, i) => {
                parts.push(`<p class="rec-paste-item">Alt. Fireball ${i + 1}: ${escapeHtml(fb.number)} (${fb.score})</p>`);
            });
        }
        if (data.special_ball?.number) {
            parts.push(`<p class="rec-paste-item"><strong>${escapeHtml(data.bonus_label || 'Especial')}:</strong> ${escapeHtml(data.special_ball.number)} — score principal ${data.main_score}, especial ${data.special_ball_score}</p>`);
        }
        if (parts.length) {
            el.innerHTML = parts.join('');
            el.style.display = 'block';
        } else {
            el.style.display = 'none';
        }
    }

    async function loadBacktestSummary() {
        const panel = $('recBacktestPanel');
        const content = $('recBacktestContent');
        if (!panel || !content) return;
        try {
            const res = await fetch('/api/recommendations/backtest?days=30');
            const data = await res.json();
            const total = data.kpis?.total_evaluated ?? data.total ?? 0;
            if (!data.ok || !total) {
                panel.style.display = 'none';
                return;
            }
            const exec = data.executive || {};
            let html = `<p class="rec-paste-item">Evaluaciones: <strong>${total}</strong> · Mejor: ${escapeHtml(data.kpis?.best_lottery || data.best_lottery || '—')}</p>`;
            html += `<p class="rec-paste-item">Precisión 7d: ${exec.precision_7d ?? '—'}% · 30d: ${exec.precision_30d ?? '—'}%</p>`;
            html += `<p class="rec-paste-item"><a href="/precision">Ver dashboard completo →</a></p>`;
            content.innerHTML = html;
            panel.style.display = 'block';
        } catch (_) {
            panel.style.display = 'none';
        }
    }

    function buildExplainHtml(data) {
        const bits = [];
        bits.push(`<p><strong>Tipo:</strong> ${escapeHtml(data.game_type || '—')} · <strong>País:</strong> ${escapeHtml(data.country || '—')}</p>`);
        bits.push(`<p><strong>Último resultado usado:</strong> ${escapeHtml(data.latest_result_date || '—')} · <strong>Histórico:</strong> ${data.history_count || data.total_results || 0} sorteos</p>`);
        if (data.digit_scores?.length) {
            bits.push('<p><strong>Por dígito/número:</strong></p><ul>');
            data.digit_scores.forEach((d) => {
                bits.push(`<li>${escapeHtml(d.number)} — score ${d.score}: ${escapeHtml(d.reason || d.score_breakdown || '')}</li>`);
            });
            bits.push('</ul>');
        }
        bits.push(`<p>${escapeHtml(data.analysis_text || '')}</p>`);
        if (data.is_strong_recommendation === false) {
            bits.push('<p class="prediction-warning">⚠️ Confianza baja — no es recomendación fuerte.</p>');
        }
        bits.push(`<p class="rec-disclaimer">${escapeHtml(data.disclaimer || '')}</p>`);
        return bits.join('');
    }

    function toggleExplainPanel() {
        const panel = $('recExplainPanel');
        if (!panel || !lastPredictionData) return;
        if (panel.style.display === 'block') {
            panel.style.display = 'none';
            return;
        }
        panel.innerHTML = buildExplainHtml(lastPredictionData);
        panel.style.display = 'block';
    }

    function copyCurrentPlay() {
        if (!lastPredictionData) return;
        const nums = (lastPredictionData.generated_numbers || []).join(' ');
        const bonus = lastPredictionData.generated_bonus || (lastPredictionData.bonus_numbers || [])[0];
        let text = `${lastPredictionData.lottery || ''} ${lastPredictionData.draw_name || ''}: ${nums}`;
        if (bonus) text += ` + ${lastPredictionData.bonus_label || 'Bonus'} ${bonus}`;
        navigator.clipboard.writeText(text.trim()).catch(() => {});
    }

    async function analyzePastedNumbers() {
        const input = $('pasteNumbersInput');
        const out = $('pasteAnalysisResult');
        if (!input || !out || !currentLotteryId || !currentDrawName) return;
        out.style.display = 'block';
        out.textContent = 'Analizando...';
        try {
            const res = await fetch('/api/recommendations/analyze-paste', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lottery_id: currentLotteryId,
                    draw_name: currentDrawName,
                    pasted: input.value,
                }),
            });
            const data = await res.json();
            if (!data.ok) {
                out.textContent = data.message || 'Error al analizar';
                return;
            }
            const lines = (data.analysis || []).map((a) =>
                `${a.number}: score ${a.score} — ${a.category_label} — ${a.reason}`
            );
            if (data.best_score) {
                lines.unshift(`Mejor score: ${data.best_score.number} (${data.best_score.score})`);
            }
            if (data.avoid?.length) {
                lines.push(`Evitar: ${data.avoid.map((a) => a.number).join(', ')}`);
            }
            if (data.compare?.match_percent != null) {
                lines.push(`Coincidencia último sorteo: ${data.compare.match_percent}%`);
            }
            out.innerHTML = lines.map((l) => `<div class="rec-paste-item">${escapeHtml(l)}</div>`).join('')
                + `<button type="button" class="btn-rec-action" style="margin-top:0.5rem" onclick="navigator.clipboard.writeText(${JSON.stringify(data.copy_text || '')})">Copiar análisis</button>`;
        } catch (e) {
            out.textContent = e.message || 'Error';
        }
    }

    async function getPrediction(btn, opts = {}) {
        const force = Boolean(opts.force);
        const reqId = ++predictionRequestSeq;
        lastPredictionDrawBtn = btn;
        if (predictionAbortController) {
            predictionAbortController.abort();
        }
        predictionAbortController = new AbortController();

        showLoading(true);
        $('analysisPlaceholder').style.display = 'none';
        clearPredictionDisplay();

        const isUsa = selectCountry.value === 'USA';
        let timeoutId = null;
        const controller = predictionAbortController;
        if (isUsa) {
            timeoutId = setTimeout(() => controller.abort(), 15000);
        }

        const sorteoTime = encodeURIComponent(btn.time_display || btn.time || btn.draw_name || '');
        const sorteoName = encodeURIComponent(btn.draw_name || '');

        try {
            const fetchOpts = {
                cache: 'no-store',
                signal: controller.signal,
                credentials: 'same-origin',
            };
            const forceQs = force ? '&force=1&recalc=1' : '';
            const bustQs = `&t=${Date.now()}`;
            const res = await fetch(
                `/api/prediction?lottery_id=${currentLotteryId}`
                + `&draw_name=${sorteoName}`
                + `&sorteo=${sorteoTime}`
                + `&fecha=latest`
                + `&days=${analysisDays}`
                + `&rango=${analysisDays}`
                + `${forceQs}${bustQs}`,
                fetchOpts
            );
            if (reqId !== predictionRequestSeq) return;

            let data;
            try {
                data = await res.json();
            } catch (parseErr) {
                throw new Error('Respuesta inválida del servidor');
            }

            if (reqId !== predictionRequestSeq) return;

            if (!res.ok && !data?.ok) {
                $('analysisError').style.display = 'block';
                $('analysisErrorMsg').textContent = data?.message || '⚠️ No se pudo completar el análisis.';
                return;
            }

            if (!data.ok) {
                $('analysisError').style.display = 'block';
                $('analysisErrorMsg').textContent = data.message || 'No hay resultados suficientes para esta tanda';
                return;
            }

            lastPredictionData = data;
            if (data.from_cache) {
                console.warn('[ANALIZADOR] Respuesta marcada como caché — ignorada');
            }
            renderPredictionDiagnostic(data);
            const explainPanel = $('recExplainPanel');
            if (explainPanel) explainPanel.style.display = 'none';

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
                let warnText = data.warning || data.low_confidence_warning || '';
                if (data.rd_inteligente && data.confidence_level === 'bajo') {
                    warnText = warnText || 'Confianza baja: usar como referencia, no jugada fuerte.';
                }
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
                || ({ alto: 'Alta', medio: 'Media', bajo: 'Baja' }[data.confidence_level] || 'Baja');
            confEl.textContent = confLabel;
            confEl.className = `confidence-badge confidence-${data.confidence_level || 'bajo'}`;

            if (data.is_strong_recommendation === false && warnEl) {
                warnEl.textContent = (warnEl.textContent ? warnEl.textContent + ' ' : '')
                    + 'Confianza baja — riesgo alto.';
                warnEl.style.display = 'block';
            }

            $('predictionScore').textContent = data.score ?? '—';
            $('predictionHistoric').textContent = data.total_results ? `${data.total_results} sorteos` : '—';
            $('predictionDate').textContent = data.created_at ? `Generado: ${data.created_at}` : '';

            const discEl = $('predictionDisclaimer');
            if (discEl && data.disclaimer) {
                discEl.textContent = data.disclaimer;
            }

            renderTopSection(data);
            loadBacktestSummary();

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
            if (e && (e.name === 'AbortError' || String(e.message || '').includes('aborted'))) {
                return;
            }
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

    function formatLeidsaHistoryError(data, res) {
        const parts = [];
        if (res && !res.ok) parts.push(`HTTP ${res.status}`);
        if (data?.error) parts.push(data.error);
        if (data?.detalle && data.detalle !== data.error) parts.push(data.detalle);
        if (data?.games?.length) {
            const failed = data.games
                .filter((g) => !g.ok || g.error)
                .map((g) => `${g.name}: ${g.error || 'sin filas'}${g.status_code ? ` (HTTP ${g.status_code})` : ''}`)
                .slice(0, 6);
            if (failed.length) parts.push(failed.join(' · '));
        }
        return parts.filter(Boolean).join(' · ') || data?.message || 'Error al actualizar historial LEIDSA';
    }

    async function refreshLeidsaHistoryNow() {
        if (!btnRefreshLeidsaHistory) return;
        btnRefreshLeidsaHistory.disabled = true;
        const prevLabel = btnRefreshLeidsaHistory.textContent;
        btnRefreshLeidsaHistory.textContent = '⏳ Descargando historial...';
        setLeidsaStatus('📚 Recorriendo historial LEIDSA (6 juegos, puede tardar 1-2 min)...', 'loading');
        try {
            const res = await fetch('/api/resultados/leidsa/actualizar-historial', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days: historyDays }),
            });
            const data = await parseJsonResponse(res);
            if (!data.ok) {
                const detail = formatLeidsaHistoryError(data, res);
                setLeidsaStatus(`❌ ${detail}`, 'error');
                console.error('[LEIDSA HISTORIAL]', data);
            } else if (data.partial || data.warning) {
                setLeidsaStatus(
                    `⚠️ ${data.message || 'Parcial'} · ${data.results_found || 0} sorteos · `
                    + `${data.inserted || 0} nuevos · ${data.updated || 0} actualizados`,
                    'muted'
                );
            } else {
                setLeidsaStatus(
                    `📚 ${data.message || 'OK'} · ${data.results_found || 0} sorteos · `
                    + `${data.inserted || 0} nuevos · ${data.updated || 0} actualizados`,
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
        setLeidsaStatus('🔄 Actualizando LEIDSA (fuente oficial + respaldos)...', 'loading');
        try {
            const res = await fetch('/api/resultados/leidsa/actualizar', {
                method: 'POST',
                credentials: 'same-origin',
            });
            const data = await parseJsonResponse(res);
            if (!data.ok || data.live_failed) {
                let detail = data.message || data.error || 'LEIDSA no respondió en vivo';
                if (data.used_db_fallback) {
                    detail = data.message || 'No se pudo actualizar en vivo. Mostrando últimos resultados guardados.';
                    if (data.latest_date) detail += ` Última fecha: ${data.latest_date}.`;
                    if (data.saved_count) detail += ` (${data.saved_count} en BD)`;
                } else {
                    if (data.status_code) detail += ` · HTTP ${data.status_code}`;
                    if (data.blocking_type) detail += ` · ${data.blocking_type}`;
                    if (data.detalle && !detail.includes(data.detalle)) detail += ` · ${data.detalle}`;
                    if (data.errors?.length) detail += ` · ${data.errors.slice(0, 3).join(' · ')}`;
                }
                setLeidsaStatus(detail.startsWith('❌') ? detail : `❌ ${detail}`, 'error');
                console.error('[LEIDSA FALLBACK]', data);
                await loadLeidsaBoard();
                return;
            }
            const fuente = data.fuente_label || data.fuente_usada || 'LEIDSA';
            const fecha = data.latest_date ? ` · Última fecha: ${data.latest_date}` : '';
            setLeidsaStatus(
                `✅ Actualizado desde: ${fuente} (${data.inserted || 0} nuevos, ${data.updated || 0} act.)${fecha}`,
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
            const data = await parseJsonResponse(res);
            if (!data.ok && !data.leidsa_ok && !(data.imported + data.updated)) {
                const err = formatUpdateError(data, res);
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
            const err = formatUpdateError(null, null, e);
            setLeidsaStatus(err, 'error');
            lastResultsError = err;
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
