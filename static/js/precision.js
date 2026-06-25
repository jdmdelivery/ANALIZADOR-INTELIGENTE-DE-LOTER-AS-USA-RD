(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);
    let charts = {};

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function fmtPct(v) {
        if (v == null || v === '') return '—';
        return `${v}%`;
    }

    async function loadDashboard() {
        const loading = $('precisionLoading');
        const err = $('precisionError');
        const content = $('precisionContent');
        try {
            const res = await fetch('/api/precision/dashboard');
            const data = await res.json();
            if (!data.ok) throw new Error(data.message || 'Error al cargar');
            loading.style.display = 'none';
            content.style.display = 'block';
            fillKpis(data);
            fillHighlights(data);
            renderCharts(data.charts || {});
            renderStatsLimits(data.stats_limits || {});
            renderRankings(data.rankings || {});
            await loadHistory(100);
        } catch (e) {
            loading.style.display = 'none';
            err.style.display = 'block';
            err.textContent = e.message || 'No se pudo cargar el dashboard';
        }
    }

    function fillKpis(d) {
        $('kpiRecToday').textContent = d.recommendations_today ?? 0;
        $('kpiHitsToday').textContent = d.hits_today ?? 0;
        $('kpiHitsWeek').textContent = d.hits_this_week ?? 0;
        $('kpiHitsMonth').textContent = d.hits_this_month ?? 0;
        $('kpiOverall').textContent = fmtPct(d.overall_precision);
        $('kpiAvgScore').textContent = d.avg_predicted_score ?? '—';
    }

    function fillHighlights(d) {
        $('bestLottery').textContent = d.best_lottery || '—';
        $('worstLottery').textContent = d.worst_lottery || '—';
        $('bestAlgo').textContent = d.best_algorithm || '—';
        $('worstAlgo').textContent = d.worst_algorithm || '—';
    }

    function renderCharts(chartsData) {
        if (typeof Chart === 'undefined') return;
        destroyCharts();
        makeLineChart('chartByDay', chartsData.by_day, 'Precisión por día', '#4ade80');
        makeBarChart('chartByLottery', chartsData.by_lottery, 'Por lotería', '#60a5fa');
        makeBarChart('chartByAlgo', chartsData.by_algorithm, 'Por algoritmo', '#f472b6');
        makeLineChart('chartScoreHist', chartsData.score_history, 'Score histórico', '#fbbf24');
    }

    function destroyCharts() {
        Object.values(charts).forEach((c) => c.destroy());
        charts = {};
    }

    function makeLineChart(canvasId, series, label, color) {
        const el = $(canvasId);
        if (!el || !series?.length) return;
        charts[canvasId] = new Chart(el, {
            type: 'line',
            data: {
                labels: series.map((x) => x.label),
                datasets: [{ label, data: series.map((x) => x.value), borderColor: color, tension: 0.25, fill: false }],
            },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100 } } },
        });
    }

    function makeBarChart(canvasId, series, label, color) {
        const el = $(canvasId);
        if (!el || !series?.length) return;
        charts[canvasId] = new Chart(el, {
            type: 'bar',
            data: {
                labels: series.map((x) => x.label),
                datasets: [{ label, data: series.map((x) => x.value), backgroundColor: color }],
            },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100 } } },
        });
    }

    function renderStatsLimits(limits) {
        const el = $('statsLimits');
        if (!el) return;
        el.innerHTML = Object.entries(limits).map(([n, s]) =>
            `<div class="stat-limit-card"><strong>Últimos ${escapeHtml(n)}</strong><span>${s.count} eval.</span><span>Precisión ${fmtPct(s.avg_hit_percentage)}</span></div>`
        ).join('');
    }

    function renderRankings(r) {
        const fill = (id, items) => {
            const ul = $(id);
            if (!ul) return;
            ul.innerHTML = (items || []).map((x) =>
                `<li>${escapeHtml(x.status_icon || '')} ${escapeHtml(x.lottery_name || '')} — ${fmtPct(x.hit_percentage)} <button type="button" class="btn-table-link" data-id="${x.id}">#${x.id}</button></li>`
            ).join('') || '<li>Sin datos</li>';
            ul.querySelectorAll('[data-id]').forEach((btn) => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    loadCompare(parseInt(btn.dataset.id, 10));
                });
            });
        };
        fill('rankBest', r.best_hits);
        fill('rankWorst', r.worst_hits);
        fill('rankScore', r.top_predicted_score);
    }

    async function loadHistory(limit) {
        const res = await fetch(`/api/precision/history?limit=${limit}`);
        const data = await res.json();
        const tbody = $('precisionTableBody');
        if (!tbody || !data.ok) return;
        tbody.innerHTML = (data.items || []).map((row) => {
            const pred = (row.predicted_list || []).join(' ');
            const act = (row.actual_list || []).join(' ');
            const hits = `${row.position_hits ?? 0} pos · ${row.hit_percentage ?? 0}%`;
            return `<tr data-id="${row.id}">
                <td>${escapeHtml((row.evaluated_at || '').slice(0, 10))}</td>
                <td>${escapeHtml(row.lottery_name || '')}</td>
                <td>${escapeHtml(pred)}</td>
                <td>${escapeHtml(act)}</td>
                <td>${escapeHtml(hits)}</td>
                <td>${escapeHtml(String(row.score ?? '—'))}</td>
                <td>${escapeHtml(row.status_icon || '')} ${escapeHtml(row.status_text || '')}</td>
                <td><button type="button" class="btn-table-link">Ver</button></td>
            </tr>`;
        }).join('') || '<tr><td colspan="8">Sin evaluaciones aún</td></tr>';

        tbody.querySelectorAll('tr[data-id]').forEach((tr) => {
            tr.addEventListener('click', () => loadCompare(parseInt(tr.dataset.id, 10)));
        });
    }

    async function loadCompare(id) {
        const panel = $('compareDetail');
        const input = $('compareIdInput');
        if (input) input.value = id;
        if (!panel) return;
        panel.style.display = 'block';
        panel.textContent = 'Cargando…';
        try {
            const res = await fetch(`/api/precision/compare/${id}`);
            const data = await res.json();
            if (!data.ok) throw new Error(data.message);
            panel.innerHTML = buildCompareHtml(data);
        } catch (e) {
            panel.textContent = e.message || 'Error';
        }
    }

    function buildCompareHtml(data) {
        const ev = data.evaluation || {};
        const pred = data.predicted || [];
        const act = data.actual || [];
        const detail = data.detail || {};
        let html = `<p><strong>${escapeHtml(ev.lottery_name || '')}</strong> — ${escapeHtml(ev.draw_date || '')}</p>`;
        html += '<div class="compare-pos-row"><span class="compare-ball">Recomendación: ' + escapeHtml(pred.join(' ')) + '</span>';
        html += '<span class="compare-ball">Resultado: ' + escapeHtml(act.join(' ')) + '</span></div>';

        if (detail.position_results?.length) {
            html += '<p><strong>Quiniela por posición:</strong></p><ul>';
            detail.position_results.forEach((p) => {
                html += `<li>${p.hit ? '✅' : '❌'} ${escapeHtml(p.label)} — predicho ${escapeHtml(p.predicted || '—')} / salió ${escapeHtml(p.actual || '—')}</li>`;
            });
            html += '</ul>';
        }
        if (detail.lines?.length) {
            html += '<ul>' + detail.lines.map((l) => `<li>${escapeHtml(l)}</li>`).join('') + '</ul>';
        }
        html += `<p>${escapeHtml(data.compare_summary || '')}</p>`;
        html += `<p>${escapeHtml(data.status_icon || '')} <strong>${escapeHtml(data.status_text || '')}</strong> — Precisión ${fmtPct(data.hit_percentage)}</p>`;
        return html;
    }

    document.addEventListener('DOMContentLoaded', () => {
        loadDashboard();
        $('historyLimit')?.addEventListener('change', (e) => loadHistory(parseInt(e.target.value, 10)));
        $('btnLoadCompare')?.addEventListener('click', () => {
            const id = parseInt($('compareIdInput')?.value, 10);
            if (id) loadCompare(id);
        });
    });
})();
