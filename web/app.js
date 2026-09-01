/* 台股財報分析 — 前端 */
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var viewSearch = $('#view-search');
  var viewResult = $('#view-result');
  var loading = $('#loading');
  var charts = [];
  var DATA = null;
  var STANDALONE = !!window.__PRELOAD__;

  var COLOR = {
    brand: '#2563eb', teal: '#0d9488', amber: '#f59e0b', rose: '#e11d48',
    violet: '#7c3aed', slate: '#64748b', green: '#16a34a', orange: '#ea580c'
  };
  var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var GRID = dark ? 'rgba(148,163,184,.18)' : 'rgba(100,116,139,.16)';
  var TICK = dark ? '#94a3b8' : '#64748b';

  // ── 工具 ──────────────────────────────────
  function show(el, on) { el.hidden = !on; }

  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 4200);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function api(path) {
    return fetch(path).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      });
    });
  }

  // ── 搜尋 ──────────────────────────────────
  var qInput = $('#q');
  var suggest = $('#suggest');
  var timer = null;

  function renderSuggest(list) {
    suggest.innerHTML = '';
    if (!list.length) { show(suggest, false); return; }
    list.forEach(function (s) {
      var li = el('li');
      li.appendChild(el('span', 'sid', s.id));
      li.appendChild(el('span', 'sname', s.name));
      li.appendChild(el('span', 'smkt', s.market));
      li.addEventListener('click', function () {
        qInput.value = s.id + ' ' + s.name;
        show(suggest, false);
        run(s.id);
      });
      suggest.appendChild(li);
    });
    show(suggest, true);
  }

  if (qInput) {
    qInput.addEventListener('input', function () {
      var q = qInput.value.trim();
      clearTimeout(timer);
      if (q.length < 1) { show(suggest, false); return; }
      timer = setTimeout(function () {
        api('/api/search?q=' + encodeURIComponent(q))
          .then(function (j) { renderSuggest(j.results || []); })
          .catch(function () { show(suggest, false); });
      }, 180);
    });
    qInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { show(suggest, false); run(qInput.value.trim()); }
    });
    $('#go').addEventListener('click', function () {
      show(suggest, false);
      run(qInput.value.trim());
    });
    Array.prototype.forEach.call(document.querySelectorAll('.chip'), function (c) {
      c.addEventListener('click', function () { run(c.dataset.q); });
    });
    $('#back').addEventListener('click', function () {
      show(viewResult, false);
      show(viewSearch, true);
      location.hash = '';
      window.scrollTo(0, 0);
    });
    $('#download').addEventListener('click', function () {
      if (!DATA) return;
      location.href = '/api/export?q=' + encodeURIComponent(DATA.stock_id);
    });
  }

  function run(q) {
    q = (q || '').trim();
    if (!q) { toast('請先輸入公司名稱或股票代號'); return; }
    q = q.split(/\s+/)[0];                    // 「2330 台積電」→ 2330
    show(loading, true);
    $('#loading-text').textContent = '正在抓取 ' + q + ' 的財報…';
    api('/api/analyze?q=' + encodeURIComponent(q))
      .then(function (data) {
        show(loading, false);
        location.hash = data.stock_id;
        render(data);
      })
      .catch(function (e) {
        show(loading, false);
        toast(e.message || '分析失敗');
      });
  }

  // ── 渲染 ──────────────────────────────────
  function render(data) {
    DATA = data;
    show(viewSearch, false);
    show(viewResult, true);
    window.scrollTo(0, 0);

    $('#co-name').textContent = data.name;
    $('#co-meta').textContent = data.stock_id + '　' + (data.market || '') +
      '　' + data.years[0] + '–' + data.years[data.years.length - 1] + ' 年度合併財報';

    renderVerify(data);
    renderPanels(data);
    switchTab('ops');
  }

  function renderVerify(data) {
    var m = data.metadata, v = data.verification || { sanity: [] };
    var bar = $('#verifybar');
    bar.innerHTML = '';
    var errs = v.sanity.filter(function (w) { return w.level === 'error'; }).length;
    var warns = v.sanity.length - errs;

    var badge = el('span', 'badge ' + (errs ? 'err' : warns ? 'warn' : 'ok'),
      errs ? '合理性檢查 ' + errs + ' 項異常'
        : warns ? '合理性檢查 ' + warns + ' 項提醒' : '合理性檢查通過');
    bar.appendChild(badge);
    bar.appendChild(el('span', null, '更新 ' + (m.fetched_at || '').slice(0, 16)));

    var a = el('a', null, 'MOPS 原始申報');
    a.href = m.mops_url; a.target = '_blank'; a.rel = 'noopener';
    bar.appendChild(a);
    var b = el('a', null, 'FinMind 原始資料');
    b.href = m.finmind_url; b.target = '_blank'; b.rel = 'noopener';
    bar.appendChild(b);

    var box = $('#warnings');
    box.innerHTML = '';
    v.sanity.forEach(function (w) {
      var d = el('div', 'warn-item' + (w.level === 'error' ? ' error' : ''));
      d.appendChild(el('b', null, (w.level === 'error' ? '❌ ' : '⚠️ ') + w.field));
      d.appendChild(el('span', null, w.msg));
      box.appendChild(d);
    });
  }

  var TAB_TITLE = { ops: '經營分析', profit: '獲利分析', health: '財務健全度' };

  function renderPanels(data) {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var host = $('#panels');
    host.innerHTML = '';

    ['ops', 'profit', 'health'].forEach(function (key) {
      var panel = el('section', 'panel');
      panel.id = 'panel-' + key;
      panel.hidden = true;

      // KPI
      var grid = el('div', 'kpi-grid');
      (data.kpis[key] || []).forEach(function (k) {
        var card = el('div', 'kpi ' + (k.tone || 'blue'));
        card.appendChild(el('div', 'kpi-label', k.label));
        card.appendChild(el('div', 'kpi-value', k.value));
        card.appendChild(el('div', 'kpi-sub', k.sub));
        grid.appendChild(card);
      });
      panel.appendChild(grid);

      // Insight
      var ins = el('div', 'insight');
      ins.appendChild(el('h3', null, '🔍 ' + TAB_TITLE[key] + '亮點'));
      var ul = el('ul');
      (data.insights[key] || []).forEach(function (t) { ul.appendChild(el('li', null, t)); });
      ins.appendChild(ul);
      panel.appendChild(ins);

      // 圖表
      var wrap = el('div', 'charts');
      chartSpecs(key, data).forEach(function (spec, i) {
        var card = el('div', 'chart-card');
        card.appendChild(el('div', 'chart-title', spec.title));
        var cont = el('div', 'chart-container');
        var cv = document.createElement('canvas');
        cv.id = 'cv-' + key + '-' + i;
        cont.appendChild(cv);
        card.appendChild(cont);
        wrap.appendChild(card);
      });
      panel.appendChild(wrap);

      // 表格
      panel.appendChild(tableCard(data.tables[key]));
      host.appendChild(panel);

      chartSpecs(key, data).forEach(function (spec, i) {
        drawChart(document.getElementById('cv-' + key + '-' + i), spec, data);
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
      t.onclick = function () { switchTab(t.dataset.tab); };
    });
  }

  function switchTab(key) {
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
      t.classList.toggle('active', t.dataset.tab === key);
    });
    ['ops', 'profit', 'health'].forEach(function (k) {
      var p = document.getElementById('panel-' + k);
      if (p) p.hidden = (k !== key);
    });
  }

  function tableCard(t) {
    var card = el('div', 'table-card');
    if (!t) return card;
    card.appendChild(el('h3', null, t.title));
    var scroll = el('div', 'table-scroll');
    var table = el('table');

    var thead = el('thead');
    var htr = el('tr');
    htr.appendChild(el('th', null, '項目'));
    t.cols.forEach(function (c) { htr.appendChild(el('th', null, c)); });
    htr.appendChild(el('th', null, '趨勢評估'));
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = el('tbody');
    t.rows.forEach(function (r) {
      if (r.values.every(function (v) { return v === '—'; })) return;   // 全無資料則不顯示
      var tr = el('tr');
      tr.appendChild(el('td', null, r.name));
      r.values.forEach(function (v) { tr.appendChild(el('td', null, v)); });
      tr.appendChild(el('td', 'trend ' + (r.tone || 'neutral'), r.trend));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    card.appendChild(scroll);
    return card;
  }

  // ── 圖表定義 ──────────────────────────────
  function chartSpecs(key, d) {
    var S = d.series, M = d.metrics;
    var hasOpex = S.rd.some(function (v) { return v !== null; });

    if (key === 'ops') {
      return [
        { title: '營收與毛利率', bars: [['營收（億）', S.revenue, COLOR.brand]],
          lines: [['毛利率 %', M.gross_margin, COLOR.amber]] },
        hasOpex
          ? { title: '費用結構（億元）', stacked: true, bars: [
              ['推銷', S.sell, COLOR.teal], ['管理', S.admin, COLOR.violet],
              ['研發', S.rd, COLOR.brand]] }
          : { title: '營業費用（億元）', bars: [['營業費用', S.op_expense, COLOR.violet]] },
        hasOpex
          ? { title: '費用率趨勢（%）', lines: [
              ['推銷率', M.sell_ratio, COLOR.teal], ['管理率', M.admin_ratio, COLOR.violet],
              ['研發率', M.rd_ratio, COLOR.brand], ['合計費用率', M.opex_ratio, COLOR.rose]],
              singleAxis: true }
          : { title: '費用率趨勢（%）', lines: [['合計費用率', M.opex_ratio, COLOR.rose]],
              singleAxis: true },
        { title: '營業利益與利益率', bars: [['營業利益（億）', S.op_income, COLOR.teal]],
          lines: [['營益率 %', M.op_margin, COLOR.rose]] }
      ];
    }
    if (key === 'profit') {
      return [
        { title: '稅後淨利與淨利率', bars: [['稅後淨利（億）', S.net_income, COLOR.brand]],
          lines: [['淨利率 %', M.net_margin, COLOR.amber]] },
        { title: 'EPS（元）', bars: [['EPS', S.eps, COLOR.teal]] },
        { title: '三層利潤率（%）', singleAxis: true, lines: [
            ['毛利率', M.gross_margin, COLOR.brand], ['營益率', M.op_margin, COLOR.teal],
            ['淨利率', M.net_margin, COLOR.rose]] },
        { title: '現金股利與配息率', bars: [['現金股利（元）', S.dps, COLOR.violet]],
          lines: [['配息率 %', M.payout, COLOR.amber]] }
      ];
    }
    return [
      { title: '資產負債結構（億元）', stacked: true, bars: [
          ['負債總額', S.liabilities, COLOR.rose], ['股東權益', S.equity, COLOR.teal]] },
      { title: '現金流量三表（億元）', bars: [
          ['營業活動', S.ocf, COLOR.brand], ['投資活動', S.icf, COLOR.orange],
          ['融資活動', S.fcf_fin, COLOR.violet]] },
      { title: '流動比率與負債比率（%）', singleAxis: true, lines: [
          ['流動比率', M.current_ratio, COLOR.teal], ['負債比率', M.debt_ratio, COLOR.rose]] },
      { title: '現金部位與占資產比', bars: [['現金及約當現金（億）', S.cash, COLOR.brand]],
        lines: [['占總資產 %', S.cash.map(function (v, i) {
          return (v == null || !S.assets[i]) ? null : v / S.assets[i] * 100;
        }), COLOR.amber]] }
    ];
  }

  function drawChart(canvas, spec, d) {
    if (!canvas || typeof Chart === 'undefined') return;
    var labels = d.years.map(String);
    var datasets = [];
    var hasLine = !!(spec.lines && spec.lines.length);
    var hasBar = !!(spec.bars && spec.bars.length);
    var dual = hasBar && hasLine && !spec.singleAxis;

    (spec.bars || []).forEach(function (b) {
      datasets.push({
        type: 'bar', label: b[0], data: b[1], backgroundColor: b[2],
        borderRadius: 4, yAxisID: 'y', order: 2, maxBarThickness: 44
      });
    });
    (spec.lines || []).forEach(function (l) {
      datasets.push({
        type: 'line', label: l[0], data: l[1], borderColor: l[2],
        backgroundColor: l[2], borderWidth: 2, tension: .3,
        pointRadius: 3, pointHoverRadius: 5, spanGaps: true,
        yAxisID: dual ? 'y2' : 'y', order: 1
      });
    });

    var scales = {
      x: { stacked: !!spec.stacked, grid: { display: false },
           ticks: { color: TICK, font: { size: 11 } } },
      y: { stacked: !!spec.stacked, position: 'left',
           grid: { color: GRID }, ticks: { color: TICK, font: { size: 10 },
             callback: function (v) { return Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + '萬' : v; } } }
    };
    if (dual) {
      scales.y2 = { position: 'right', grid: { drawOnChartArea: false },
                    ticks: { color: TICK, font: { size: 10 } } };
    }

    charts.push(new Chart(canvas, {
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { boxWidth: 10, boxHeight: 10, color: TICK,
                              font: { size: 11 }, usePointStyle: true } },
          tooltip: { callbacks: { label: function (c) {
            var v = c.parsed.y;
            return c.dataset.label + '：' + (v == null ? '—' :
              v.toLocaleString('zh-TW', { maximumFractionDigits: 2 }));
          } } }
        },
        scales: scales
      }
    }));
  }

  // ── 啟動 ──────────────────────────────────
  if (STANDALONE) {
    var dl = $('#download'), bk = $('#back');
    if (dl) dl.style.visibility = 'hidden';
    if (bk) bk.style.visibility = 'hidden';
    show(viewSearch, false);
    render(window.__PRELOAD__);
  } else if (location.hash.length > 1) {
    run(location.hash.slice(1));
  }
})();
