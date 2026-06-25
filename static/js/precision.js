(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);
    let charts = {};
    let dashboardData = null;

    const KPI_DEFS = [
        { key: 'recommendations_today', icon: '🎯', label: 'Recomendaciones hoy' },
        { key: 'hits_today', icon: '✅', label: 'Aciertadas hoy' },
        { key: 'precision_7d', icon: '📈', label: 'Precisión 7 días', pct: true },
        { key: 'precision_30d', icon: '📅', label: 'Precisión 30 días', pct: true },
        { key: 'best_algorithm', icon: '🏆', label: 'Mejor algoritmo', fromRoot: true },
        { key: 'worst_algorithm', icon: '📉', label: 'Peor algoritmo', fromRoot: true },
        { key: 'avg_score', icon: '🧠', label: 'Score promedio' },
        { key: 'best_lottery', icon: '🔥', label: 'Mejor lotería', fromRoot: true },
        { key: 'total_analyses', icon: '📊', label: 'Total análisis' },
        { key: 'total_evaluated', icon: '✔️', label: 'Evaluaciones' },
    ];

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function fmtPct(v) {
        if (v == null || v === '') return '—';
        return `${v}%`;
    }

    function fmtVal(v, pct) {
        if (v == null || v === '') return '—';
        return pct ? fmtPct(v) : String(v);
    }

    async function loadDashboard() {
        const loading = $('precisionLoading');
        const err = $('precisionError');
        const content = $('precisionContent');
        try {
            const res = await fetch('/api/precision/dashboard');
            const data = await res.json();
            if (!data.ok) throw new Error(data.message || 'Error al cargar');
            dashboardData = data;
            loading.style.display = 'none';
            content.style.display = 'block';
            renderExecutive(data.executive || {}, data.last_updated);
            renderKpis(data);
            renderGameTypes(data.precision_by_game_type || []);
            renderIQ(data.intelligence_answers || {});
            renderLearning(data.learning_insights || []);
            renderFactors(data.factor_performance || []);
            renderLotteryTable(data.lottery_table || []);
            renderAlgoTable(data.algorithm_ranking || []);
            renderLotteryRankings(data.lottery_rankings || {});
            renderEvolution(data.evolution || []);
            renderCharts(data.charts || {});
            await loadHistory(100);
        } catch (e) {
            loading.style.display = 'none';
            err.style.display = 'block';
            err.textContent = e.message || 'No se pudo cargar el dashboard';
        }
    }

    function renderExecutive(ex, updated) {
        $('execStatus').textContent = `${ex.status_icon || ''} ${ex.status_label || '—'}`;
        $('execHist').textContent = fmtPct(ex.precision_historical);
        $('exec30').textContent = fmtPct(ex.precision_30d);
        $('exec7').textContent = fmtPct(ex.precision_7d);
        $('execToday').textContent = fmtPct(ex.precision_today);
        $('lastUpdated').textContent = updated || '—';
        const banner = $('execBanner');
        if (banner && ex.status) banner.dataset.status = ex.status;
    }

    function renderKpis(d) {
        const grid = $('kpiGrid');
        if (!grid) return;
        const k = d.kpis || {};
        grid.innerHTML = KPI_DEFS.map((def) => {
            let val = def.fromRoot ? d.kpis?.[def.key] ?? d[def.key] : k[def.key];
            if (def.key === 'best_algorithm') val = d.kpis?.best_algorithm ?? d.best_algorithm;
            if (def.key === 'worst_algorithm') val = d.kpis?.worst_algorithm ?? d.worst_algorithm;
            if (def.key === 'best_lottery') val = d.kpis?.best_lottery ?? d.best_lottery;
            return `<article class="kpi-card glass-panel">
                <span class="kpi-icon">${def.icon}</span>
                <span class="kpi-label">${escapeHtml(def.label)}</span>
                <strong class="kpi-value">${escapeHtml(fmtVal(val, def.pct))}</strong>
            </article>`;
        }).join('');
    }

    function renderGameTypes(items) {
        const el = $('gameTypeCards');
        if (!el) return;
        if (!items.length) {
            el.innerHTML = '<p class="empty-msg">Aún no hay evaluaciones por tipo. Genera recomendaciones y espera los resultados oficiales.</p>';
            return;
        }
        el.innerHTML = items.map((g) =>
            `<article class="game-type-card">
                <span class="gt-icon">${g.icon}</span>
                <h3>${escapeHtml(g.label)}</h3>
                <strong class="gt-pct">${fmtPct(g.precision_pct)}</strong>
                <span class="gt-sub">${g.hits}/${g.evaluations} aciertos</span>
                <span class="gt-status">${escapeHtml(g.status_icon || '')} ${escapeHtml(g.status_label || '')}</span>
            </article>`
        ).join('');
    }

    function renderIQ(a) {
        const el = $('iqAnswers');
        if (!el) return;
        const items = [
            ['¿Mejor algoritmo?', a.best_algorithm?.label || a.best_algorithm?.motor || '—'],
            ['¿Peor algoritmo?', a.worst_algorithm?.label || '—'],
            ['¿Mayor precisión?', a.best_lottery?.name || '—', a.best_lottery?.precision_pct],
            ['¿Menor precisión?', a.worst_lottery?.name || '—', a.worst_lottery?.precision_pct],
            ['¿Tipo con más aciertos?', a.best_analysis_type?.label || '—', a.best_analysis_type?.precision_pct],
            ['¿Mejor día?', a.best_weekday?.day || '—', a.best_weekday?.precision_pct],
            ['¿Mejor horario/tanda?', a.best_draw_slot?.draw_name || '—', a.best_draw_slot?.precision_pct],
            ['¿Factor clave?', a.top_contributing_factor?.label || '—', a.top_contributing_factor?.effectiveness_pct],
        ];
        el.innerHTML = items.map(([q, ans, pct]) =>
            `<div class="iq-card"><span class="iq-q">${escapeHtml(q)}</span>
             <strong>${escapeHtml(ans)}${pct != null ? ` (${fmtPct(pct)})` : ''}</strong></div>`
        ).join('');
    }

    function renderLearning(items) {
        const el = $('learningList');
        if (!el) return;
        el.innerHTML = items.map((i) =>
            `<li><span>${i.icon || '✔'}</span> ${escapeHtml(i.text)}</li>`
        ).join('');
    }

    function renderFactors(factors) {
        const el = $('factorBars');
        if (!el) return;
        el.innerHTML = factors.map((f) => {
            const w = f.effectiveness_pct || 0;
            return `<div class="factor-row">
                <span class="factor-name">${escapeHtml(f.label)}</span>
                <div class="progress-track"><div class="progress-fill" style="width:${w}%"></div></div>
                <span class="factor-pct">${w}%</span>
            </div>`;
        }).join('');
    }

    function renderLotteryTable(rows) {
        const tbody = $('lotteryTableBody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((r) =>
            `<tr data-lottery-id="${r.lottery_id}">
                <td>${escapeHtml(r.lottery_name)}</td>
                <td>${escapeHtml(r.country)}</td>
                <td>${escapeHtml(r.game_type_label)}</td>
                <td>${r.recommendations}</td>
                <td>${r.hits}</td>
                <td>${r.precision_pct != null ? fmtPct(r.precision_pct) : '—'}</td>
                <td>${r.avg_score ?? '—'}</td>
                <td>${r.icon || ''} ${escapeHtml(r.label || '—')}</td>
                <td><button type="button" class="btn-table-link btn-intel">Ver</button></td>
            </tr>`
        ).join('') || '<tr><td colspan="9">Sin datos</td></tr>';

        tbody.querySelectorAll('.btn-intel').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.closest('tr')?.dataset.lotteryId;
                if (id) loadLotteryIntel(parseInt(id, 10));
            });
        });
    }

    function renderAlgoTable(rows) {
        const tbody = $('algoTableBody');
        if (!tbody) return;
        tbody.innerHTML = rows.map((r) =>
            `<tr>
                <td>${r.icon || ''} ${escapeHtml(r.label)}</td>
                <td>${fmtPct(r.precision_pct)}</td>
                <td>${r.hits}</td>
                <td>${r.errors}</td>
                <td>${escapeHtml((r.last_hit || '—').slice(0, 16))}</td>
                <td>${escapeHtml((r.last_miss || '—').slice(0, 16))}</td>
                <td>${r.icon || ''} ${escapeHtml(r.label)}</td>
            </tr>`
        ).join('') || '<tr><td colspan="7">Sin evaluaciones</td></tr>';
    }

    function renderLotteryRankings(r) {
        const renderBars = (id, items, good) => {
            const el = $(id);
            if (!el) return;
            el.innerHTML = (items || []).map((x) => {
                const w = Math.min(100, x.precision_pct || 0);
                return `<div class="rank-bar-row">
                    <span class="rank-name">${escapeHtml(x.name)}</span>
                    <div class="progress-track ${good ? 'good' : 'bad'}"><div class="progress-fill" style="width:${w}%"></div></div>
                    <span class="rank-pct">${fmtPct(x.precision_pct)}</span>
                </div>`;
            }).join('') || '<p class="empty-msg">Sin datos</p>';
        };
        renderBars('rankTop10', r.top_10, true);
        renderBars('rankBottom10', r.bottom_10, false);
    }

    function renderEvolution(items) {
        const el = $('evolutionTimeline');
        if (!el) return;
        el.innerHTML = items.map((w) =>
            `<div class="evo-step">
                <span class="evo-week">Semana ${w.week}</span>
                <strong class="evo-pct">${fmtPct(w.precision_pct)}</strong>
                <span class="evo-n">${w.evaluations} eval.</span>
            </div>`
        ).join('') || '<p class="empty-msg">Sin evolución aún</p>';
    }

    function renderCharts(c) {
        if (typeof Chart === 'undefined') return;
        destroyCharts();
        lineChart('chartDaily', c.precision_daily, 'Precisión %', '#4ade80');
        lineChart('chartWeekly', c.precision_weekly, 'Precisión %', '#38bdf8');
        lineChart('chartMonthly', c.precision_monthly, 'Precisión %', '#a78bfa');
        barChart('chartLottery', c.by_lottery, 'Precisión %', '#60a5fa');
        barChart('chartAlgo', c.by_algorithm, 'Precisión %', '#f472b6');
        dualLineChart('chartScore', c.score_and_precision);
        barChart('chartRecs', c.recommendations_daily, 'Cantidad', '#fbbf24', false);
        barChart('chartHits', c.hits_daily, 'Aciertos', '#34d399', false);
    }

    function destroyCharts() {
        Object.values(charts).forEach((ch) => ch.destroy());
        charts = {};
    }

    function lineChart(id, series, label, color) {
        const el = $(id);
        if (!el || !series?.length) return;
        charts[id] = new Chart(el, {
            type: 'line',
            data: {
                labels: series.map((x) => x.label),
                datasets: [{ label, data: series.map((x) => x.value), borderColor: color, tension: 0.3, fill: false }],
            },
            options: chartOpts(100),
        });
    }

    function barChart(id, series, label, color, pctScale = true) {
        const el = $(id);
        if (!el || !series?.length) return;
        charts[id] = new Chart(el, {
            type: 'bar',
            data: {
                labels: series.map((x) => x.label),
                datasets: [{ label, data: series.map((x) => x.value), backgroundColor: color }],
            },
            options: chartOpts(pctScale ? 100 : undefined),
        });
    }

    function dualLineChart(id, series) {
        const el = $(id);
        if (!el || !series?.length) return;
        charts[id] = new Chart(el, {
            type: 'line',
            data: {
                labels: series.map((x) => x.label),
                datasets: [
                    { label: 'Score', data: series.map((x) => x.score), borderColor: '#fbbf24', tension: 0.3 },
                    { label: 'Precisión', data: series.map((x) => x.precision), borderColor: '#4ade80', tension: 0.3 },
                ],
            },
            options: chartOpts(100),
        });
    }

    function chartOpts(maxY) {
        const scales = maxY ? { y: { min: 0, max: maxY } } : {};
        return { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#ccc' } } }, scales };
    }

    async function loadHistory(limit) {
        const res = await fetch(`/api/precision/history?limit=${limit}`);
        const data = await res.json();
        const tbody = $('historyTableBody');
        if (!tbody || !data.ok) return;
        tbody.innerHTML = (data.items || []).map((row) => {
            const pred = (row.predicted_list || []).join(' ');
            const act = (row.actual_list || []).join(' ');
            return `<tr data-id="${row.id}">
                <td>${escapeHtml(row.eval_date)}</td>
                <td>${escapeHtml(row.eval_time)}</td>
                <td>${escapeHtml(row.lottery_name)}</td>
                <td>${escapeHtml(row.lottery_type || row.game_type || '—')}</td>
                <td>${escapeHtml(pred)}</td>
                <td>${escapeHtml(act)}</td>
                <td>${row.position_hits ?? 0} · ${fmtPct(row.hit_percentage)}</td>
                <td>${escapeHtml(String(row.score ?? '—'))}</td>
                <td>${escapeHtml(row.confidence)}</td>
                <td>${row.status_icon} ${escapeHtml(row.status_text)}</td>
                <td><button type="button" class="btn-table-link">Ver análisis</button></td>
            </tr>`;
        }).join('') || '<tr><td colspan="11">Sin evaluaciones — genera recomendaciones y espera resultados oficiales.</td></tr>';

        tbody.querySelectorAll('tr[data-id]').forEach((tr) => {
            tr.addEventListener('click', () => {
                loadCompare(parseInt(tr.dataset.id, 10));
                $('compareSection')?.scrollIntoView({ behavior: 'smooth' });
            });
        });
    }

    async function loadCompare(id) {
        const panel = $('compareDetail');
        const input = $('compareIdInput');
        if (input) input.value = id;
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = '<p>Cargando…</p>';
        try {
            const res = await fetch(`/api/precision/compare/${id}`);
            const data = await res.json();
            if (!data.ok) throw new Error(data.message);
            panel.innerHTML = buildCompareVisual(data);
        } catch (e) {
            panel.innerHTML = `<p>${escapeHtml(e.message)}</p>`;
        }
    }

    function buildCompareVisual(data) {
        const pred = data.predicted || [];
        const act = data.actual || [];
        const positions = data.position_results || data.detail?.position_results || [];
        let html = '<div class="compare-columns">';
        html += '<div class="compare-col"><h4>RECOMENDACIÓN</h4><div class="ball-row">';
        pred.forEach((n) => { html += `<span class="ball-pred">${escapeHtml(n)}</span>`; });
        html += '</div></div>';
        html += '<div class="compare-col"><h4>RESULTADO</h4><div class="ball-row">';
        act.forEach((n) => { html += `<span class="ball-act">${escapeHtml(n)}</span>`; });
        html += '</div></div></div>';

        if (positions.length) {
            html += '<div class="compare-results"><h4>Resultado</h4><ul>';
            positions.forEach((p) => {
                const lbl = { primera: 'Primera', segunda: 'Segunda', tercera: 'Tercera' }[p.label] || p.label;
                html += `<li>${p.hit ? '✅' : '❌'} ${escapeHtml(lbl)}</li>`;
            });
            html += '</ul></div>';
        } else if (data.detail?.lines?.length) {
            html += '<ul class="compare-lines">' + data.detail.lines.map((l) => `<li>${escapeHtml(l)}</li>`).join('') + '</ul>';
        }

        html += `<div class="compare-precision"><strong>Precisión ${fmtPct(data.hit_percentage)}</strong></div>`;
        html += `<p class="compare-status">${data.status_icon} ${escapeHtml(data.status_text)}</p>`;
        return html;
    }

    async function loadLotteryIntel(lotteryId) {
        const panel = $('lotteryIntelPanel');
        const body = $('lotteryIntelBody');
        if (!panel || !body) return;
        panel.style.display = 'block';
        body.innerHTML = 'Cargando…';
        panel.scrollIntoView({ behavior: 'smooth' });
        try {
            const res = await fetch(`/api/precision/lottery/${lotteryId}`);
            const data = await res.json();
            if (!data.ok) throw new Error(data.message);
            $('intelTitle').textContent = `📊 ${data.lottery.name}`;
            const s = data.stats || {};
            body.innerHTML = `
                <div class="intel-stats">
                    <span>Evaluaciones: <strong>${s.evaluations}</strong></span>
                    <span>Precisión: <strong>${fmtPct(s.precision_pct)}</strong></span>
                    <span>Score: <strong>${s.avg_score ?? '—'}</strong></span>
                    <span>Algoritmo: <strong>${escapeHtml(data.algorithm?.version || '—')}</strong></span>
                </div>
                <h4>Top 10 mejores</h4><ul class="rank-list">${(data.top_10 || []).map((x) =>
                    `<li>${x.status_icon} ${fmtPct(x.hit_percentage)} — ${escapeHtml(x.predicted || '')}</li>`
                ).join('') || '<li>—</li>'}</ul>
                <h4>Últimos aciertos</h4><ul class="rank-list">${(data.recent_hits || []).map((x) =>
                    `<li><button type="button" class="btn-table-link" data-cid="${x.id}">${fmtPct(x.hit_percentage)}</button> ${escapeHtml(x.predicted || '')}</li>`
                ).join('') || '<li>—</li>'}</ul>
                <h4>Últimos fallos</h4><ul class="rank-list">${(data.recent_misses || []).map((x) =>
                    `<li><button type="button" class="btn-table-link" data-cid="${x.id}">${fmtPct(x.hit_percentage)}</button> ${escapeHtml(x.predicted || '')}</li>`
                ).join('') || '<li>—</li>'}</ul>
                <h4>Errores frecuentes</h4><ul class="rank-list">${(data.frequent_errors || []).map((e) =>
                    `<li>${escapeHtml(e.description)} (${e.count})</li>`
                ).join('') || '<li>—</li>'}</ul>`;
            body.querySelectorAll('[data-cid]').forEach((btn) => {
                btn.addEventListener('click', () => loadCompare(parseInt(btn.dataset.cid, 10)));
            });
        } catch (e) {
            body.innerHTML = `<p>${escapeHtml(e.message)}</p>`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        loadDashboard();
        $('historyLimit')?.addEventListener('change', (e) => loadHistory(parseInt(e.target.value, 10)));
        $('btnLoadCompare')?.addEventListener('click', () => {
            const id = parseInt($('compareIdInput')?.value, 10);
            if (id) loadCompare(id);
        });
        $('btnCloseIntel')?.addEventListener('click', () => {
            const p = $('lotteryIntelPanel');
            if (p) p.style.display = 'none';
        });
    });
})();
