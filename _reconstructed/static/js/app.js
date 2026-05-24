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
    const loadingOverlay = $('loadingOverlay');
    const liveIndicator = $('liveIndicator');

    if (!selectCountry) return;

    let currentLotteryId = null;
    let currentLotteryName = '';
    let refreshTimer = null;
    let activeDrawBtn = null;

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
        resetLotterySelect();
        hideMain();

        if (country === 'USA') {
            stateGroup.style.display = 'block';
            loadStates(country);
        } else if (country === 'RD') {
            stateGroup.style.display = 'none';
            loadLotteries();
        } else {
            stateGroup.style.display = 'none';
        }
    }

    async function loadStates(country) {
        selectState.innerHTML = '<option value="">— Seleccionar estado —</option>';
        try {
            const res = await fetch(`/api/states?country=${country}`);
            const data = await res.json();
            data.states.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = s;
                selectState.appendChild(opt);
            });
        } catch (e) {
            console.error(e);
        }
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
            data.lotteries.forEach(lot => {
                const opt = document.createElement('option');
                opt.value = lot.id;
                opt.textContent = lot.name;
                opt.dataset.name = lot.name;
                selectLottery.appendChild(opt);
            });
            selectLottery.disabled = data.lotteries.length === 0;
        } catch (e) {
            console.error(e);
        }
    }

    function resetLotterySelect() {
        selectLottery.innerHTML = '<option value="">— Seleccionar lotería —</option>';
        selectLottery.disabled = true;
        currentLotteryId = null;
        stopAutoRefresh();
    }

    function hideMain() {
        mainSplit.style.display = 'none';
        liveIndicator.style.display = 'none';
        resetAnalysisPanel();
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
        hideMain();

        if (!currentLotteryId) return;

        mainSplit.style.display = 'grid';
        resetAnalysisPanel();
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

    async function loadRecentResults(silent) {
        if (!silent) {
            recentResults.innerHTML = '<p class="empty-msg">Cargando resultados...</p>';
        }
        try {
            const res = await fetch(`/api/results?lottery_id=${currentLotteryId}&limit=12`);
            const data = await res.json();

            if (!data.results?.length) {
                recentResults.innerHTML = '<p class="empty-msg">No hay resultados registrados aún.</p>';
                return;
            }

            recentResults.innerHTML = data.results.map(r => `
                <div class="result-card-hd ${tandaClass(r.draw_name)} animate-fade-in">
                    
                    <div class="rc-tanda">${escapeHtml(r.draw_name)}</div>
                    <div class="rc-date">${escapeHtml(r.draw_date)}${r.time_display ? ' · ' + escapeHtml(r.time_display) : (r.draw_time ? ' · ' + escapeHtml(r.draw_time) : '')}</div>
                    
                    <div class="rc-balls">
                        ${renderBallSet(r.main_numbers || r.numbers, r.bonus_numbers)}
                    </div>
                </div>
            `).join('');
        } catch (e) {
            if (!silent) recentResults.innerHTML = '<p class="empty-msg">Error al cargar resultados.</p>';
        }
    }

    async function loadDrawButtons() {
        drawButtons.innerHTML = '';
        try {
            const res = await fetch(`/api/draw-times?lottery_id=${currentLotteryId}`);
            const data = await res.json();

            data.buttons.forEach(btn => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `btn-tanda ${btn.css || 'tanda-default'}`;
                const timeLine = btn.time_display || '';
                button.innerHTML = `
                    <span class="tanda-emoji">${btn.emoji || '🎱'}</span>
                    <span class="tanda-label">${escapeHtml(btn.label || btn.draw_name)}</span>
                    ${timeLine ? `<span class="tanda-time">${escapeHtml(timeLine)}</span>` : ''}
                `;
                button.dataset.drawName = btn.draw_name;
                button.title = btn.schedule_label || btn.draw_name;
                button.addEventListener('click', () => {
                    if (activeDrawBtn) activeDrawBtn.classList.remove('active');
                    button.classList.add('active');
                    activeDrawBtn = button;
                    getPrediction(btn);
                });
                drawButtons.appendChild(button);
            });
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
    }

    function showLoading(show) {
        loadingOverlay.style.display = show ? 'flex' : 'none';
    }

    function renderStatNumbers(containerId, numbers) {
        const el = $(containerId);
        if (!numbers?.length) {
            el.innerHTML = '<span class="stat-chip">—</span>';
            return;
        }
        el.innerHTML = numbers.map(n => `<span class="stat-chip">${escapeHtml(n)}</span>`).join('');
    }

    async function getPrediction(btn) {
        showLoading(true);
        $('analysisPlaceholder').style.display = 'none';
        $('analysisContent').style.display = 'none';
        $('analysisError').style.display = 'none';

        try {
            const res = await fetch(
                `/api/prediction?lottery_id=${currentLotteryId}&draw_name=${encodeURIComponent(btn.draw_name)}`
            );
            const data = await res.json();

            if (!data.ok) {
                $('analysisError').style.display = 'block';
                $('analysisErrorMsg').textContent = data.message || 'No hay suficientes datos históricos.';
                return;
            }

            const drawLabel = (data.draw_display || btn.label || btn.draw_name);
            $('predictionDraw').textContent = drawLabel;

            const scheduleEl = $('predictionSchedule');
            if (data.schedule_label) {
                scheduleEl.innerHTML = `
                    <span class="schedule-prefix">📌 Recomendado para:</span>
                    <span class="schedule-value">${escapeHtml(data.schedule_label)}</span>
                `;
            } else {
                scheduleEl.textContent = `🕘 ${currentLotteryName} — ${drawLabel}`;
            }

            const bonus = data.bonus_numbers || (data.generated_bonus ? [data.generated_bonus] : []);
            $('predictionBalls').innerHTML = renderBallSet(data.generated_numbers, bonus, 'large');

            $('predictionReason').textContent = data.analysis_text || '';

            const confEl = $('predictionConfidence');
            confEl.textContent = data.confidence_level || '—';
            confEl.className = `confidence-badge confidence-${data.confidence_level || 'bajo'}`;

            $('predictionScore').textContent = data.score ?? '—';
            $('predictionHistoric').textContent = data.total_results ? `${data.total_results} sorteos` : '—';
            $('predictionDate').textContent = data.created_at ? `Generado: ${data.created_at}` : '';

            renderStatNumbers('statHot', data.hot_numbers);
            renderStatNumbers('statCold', data.cold_numbers);
            renderStatNumbers('statOverdue', data.overdue_numbers);

            $('analysisContent').style.display = 'block';
            scrollToEl('analisis');
        } catch (e) {
            $('analysisError').style.display = 'block';
            $('analysisErrorMsg').textContent = 'Error al obtener el análisis.';
            console.error(e);
        } finally {
            showLoading(false);
        }
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
})();
