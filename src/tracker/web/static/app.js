const UNIVERSE = Array.from(document.querySelectorAll(".ticker-btn")).map(b => b.dataset.ticker);
let currentTicker = UNIVERSE[0];

const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const PLOTLY_FONT = { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: "#52514e", size: 12 };
const AXIS_STYLE = { gridcolor: "#e1e0d9", zerolinecolor: "#c3c2b7", linecolor: "#c3c2b7", tickfont: PLOTLY_FONT };

function baseLayout(extra) {
  return Object.assign({
    font: PLOTLY_FONT,
    paper_bgcolor: "#fcfcfb",
    plot_bgcolor: "#fcfcfb",
    margin: { l: 50, r: 20, t: 10, b: 40 },
    xaxis: Object.assign({}, AXIS_STYLE),
    yaxis: Object.assign({}, AXIS_STYLE),
    hovermode: "x unified",
    height: 280,
  }, extra);
}

async function getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

function fmtNum(v, decimals = 0) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: decimals });
}

function fmtPct(v, decimals = 1) {
  if (v === null || v === undefined) return "—";
  return (Number(v) * 100).toFixed(decimals) + "%";
}

function deltaSpan(v, decimals = 1, isBps = false, swingThreshold = 1.0) {
  if (v === null || v === undefined) return "—";
  const cls = v >= 0 ? "delta-up" : "delta-down";
  const arrow = v >= 0 ? "▲" : "▼";
  const text = isBps ? `${Math.abs(v).toFixed(0)}bps` : `${Math.abs(v * 100).toFixed(decimals)}%`;
  // A large swing in EPS/shares is usually a stock split, not real performance
  // (EDGAR doesn't retroactively re-tag pre-split EPS) — flag rather than hide it.
  // EPS gets a lower bar than revenue/net income, which can swing hard for real.
  const warn = !isBps && Math.abs(v) > swingThreshold
    ? ` <span class="swing-flag" title="Large swing — check for a stock split or other corporate action before comparing to prior year">⚠</span>`
    : "";
  return `<span class="${cls}">${arrow} ${text}</span>${warn}`;
}

function renderFundamentalsTable(rows) {
  const recent = rows.slice(-5);
  const metrics = [
    { key: "revenue", label: "Revenue", fmt: v => fmtNum(v), yoyKey: "revenue_yoy" },
    { key: "net_income", label: "Net income", fmt: v => fmtNum(v), yoyKey: "net_income_yoy" },
    { key: "eps_diluted", label: "Diluted EPS", fmt: v => v == null ? "—" : Number(v).toFixed(2), yoyKey: "eps_diluted_yoy", swingThreshold: 0.5 },
    { key: "gross_margin", label: "Gross margin", fmt: v => fmtPct(v), yoyKey: "gross_margin_delta_bps", isBps: true },
    { key: "operating_margin", label: "Operating margin", fmt: v => fmtPct(v), yoyKey: "operating_margin_delta_bps", isBps: true },
    { key: "free_cash_flow", label: "Free cash flow", fmt: v => fmtNum(v), yoyKey: "free_cash_flow_yoy" },
  ];

  let html = "<table class='fundamentals'><thead><tr><th>Fiscal year</th>";
  for (const row of recent) {
    html += `<th>FY${row.fiscal_year}<br><span class="muted">${row.period_end ?? ""}</span></th>`;
  }
  html += "</tr></thead><tbody>";
  for (const m of metrics) {
    html += `<tr><td>${m.label}</td>`;
    for (const row of recent) {
      const value = m.fmt(row[m.key]);
      const delta = deltaSpan(row[m.yoyKey], 1, !!m.isBps, m.swingThreshold ?? 1.0);
      html += `<td>${value}<br>${delta}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  document.getElementById("fundamentals-table").innerHTML = html;
}

function renderPriceChart(prices, fundamentals) {
  const trace = {
    x: prices.map(p => p.trade_date),
    y: prices.map(p => p.close),
    type: "scatter",
    mode: "lines",
    line: { color: SERIES_COLORS[0], width: 2 },
    name: "Close",
    hovertemplate: "%{y:.2f}<extra></extra>",
  };
  const shapes = [];
  const annotations = [];
  for (const row of fundamentals) {
    if (!row.period_end) continue;
    shapes.push({
      type: "line", x0: row.period_end, x1: row.period_end, yref: "paper", y0: 0, y1: 1,
      line: { color: "#c3c2b7", width: 1, dash: "dot" },
    });
    annotations.push({
      x: row.period_end, y: 1, yref: "paper", yanchor: "bottom", showarrow: false,
      text: `FY${row.fiscal_year}`, font: { size: 10, color: "#898781" },
    });
  }
  Plotly.newPlot("price-chart", [trace], baseLayout({ shapes, annotations, showlegend: false }), { displayModeBar: false, responsive: true });
}

function renderCapexIntensityChart(series) {
  // Gaps in the underlying capex tag (see DESIGN.md known limitations, e.g.
  // NVDA FY2012-2023) are dropped rather than drawn as zero-height bars.
  const present = series.filter(s => s.capex_intensity != null);
  const trace = {
    x: present.map(s => `FY${s.fiscal_year}`),
    y: present.map(s => s.capex_intensity),
    type: "bar",
    marker: { color: SERIES_COLORS[0] },
    hovertemplate: "%{y:.1%}<extra></extra>",
  };
  Plotly.newPlot("capex-intensity-chart", [trace], baseLayout({
    title: { text: "Capex intensity (capex / revenue)", font: { size: 12, color: "#52514e" }, pad: { b: 10 } },
    margin: { l: 50, r: 20, t: 34, b: 40 },
    yaxis: Object.assign({}, AXIS_STYLE, { tickformat: ".0%" }),
    showlegend: false,
  }), { displayModeBar: false, responsive: true });
}

function renderCapexCycleChart(series) {
  // Anchor the x-axis to years where the company itself has capex data —
  // the FRED series has every year, so filtering on "either" would keep
  // showing the company's gap years as empty stretches instead of skipping them.
  const present = series.filter(s => s.capex_yoy != null);
  const years = present.map(s => `FY${s.fiscal_year}`);
  const traces = [
    {
      x: years, y: present.map(s => s.capex_yoy), type: "scatter", mode: "lines+markers",
      name: "Company capex YoY", line: { color: SERIES_COLORS[0], width: 2 }, marker: { size: 8 }, connectgaps: false,
    },
    {
      x: years, y: present.map(s => s.macro_capex_yoy), type: "scatter", mode: "lines+markers",
      name: "National capex YoY (FRED PNFI)", line: { color: SERIES_COLORS[1], width: 2 }, marker: { size: 8 }, connectgaps: false,
    },
  ];
  Plotly.newPlot("capex-cycle-chart", traces, baseLayout({
    title: { text: "Capex cycle: company vs. national YoY growth", font: { size: 12, color: "#52514e" }, pad: { b: 10 } },
    margin: { l: 50, r: 20, t: 34, b: 60 },
    yaxis: Object.assign({}, AXIS_STYLE, { tickformat: ".0%" }),
    showlegend: true,
    legend: { orientation: "h", y: -0.25 },
  }), { displayModeBar: false, responsive: true });
}

async function renderCapexScatter() {
  const points = [];
  for (const ticker of UNIVERSE) {
    try {
      const [fundamentals, capex] = await Promise.all([
        getJSON(`/api/fundamentals/${ticker}`),
        getJSON(`/api/capex/${ticker}`),
      ]);
      const lastFund = fundamentals[fundamentals.length - 1];
      const lastCapex = capex.series[capex.series.length - 1];
      if (lastFund && lastCapex && lastFund.revenue_yoy != null && lastCapex.capex_intensity != null) {
        points.push({ ticker, x: lastFund.revenue_yoy, y: lastCapex.capex_intensity });
      }
    } catch (e) { console.warn("scatter skip", ticker, e); }
  }
  const trace = {
    x: points.map(p => p.x), y: points.map(p => p.y), text: points.map(p => p.ticker),
    mode: "markers+text", type: "scatter", textposition: "top center",
    marker: { size: 12, color: points.map((_, i) => SERIES_COLORS[i % SERIES_COLORS.length]) },
    textfont: { color: "#52514e", size: 12 },
    hovertemplate: "%{text}<br>Revenue YoY: %{x:.1%}<br>Capex intensity: %{y:.1%}<extra></extra>",
  };
  Plotly.newPlot("capex-scatter-chart", [trace], baseLayout({
    title: { text: "Latest FY: capex intensity vs. revenue growth (all 5 companies)", font: { size: 12, color: "#52514e" } },
    xaxis: Object.assign({}, AXIS_STYLE, { title: "Revenue YoY growth", tickformat: ".0%" }),
    yaxis: Object.assign({}, AXIS_STYLE, { title: "Capex intensity", tickformat: ".0%" }),
    showlegend: false,
    height: 320,
  }), { displayModeBar: false, responsive: true });
}

async function renderValuationSummary(ticker) {
  try {
    const v = await getJSON(`/api/valuation/${ticker}`);
    document.getElementById("valuation-summary").textContent =
      `— $${v.price.toFixed(2)} as of ${v.price_as_of} · trailing P/E ${v.trailing_pe ? v.trailing_pe.toFixed(1) : "—"} · trailing P/S ${v.trailing_ps ? v.trailing_ps.toFixed(1) : "—"} (EPS/revenue as of FY${v.eps_fiscal_year})`;
  } catch (e) {
    document.getElementById("valuation-summary").textContent = "";
  }
}

async function loadTicker(ticker) {
  currentTicker = ticker;
  document.querySelectorAll(".ticker-btn").forEach(b => b.classList.toggle("active", b.dataset.ticker === ticker));

  const [fundamentals, prices, capex] = await Promise.all([
    getJSON(`/api/fundamentals/${ticker}`),
    getJSON(`/api/prices/${ticker}?days=1100`),
    getJSON(`/api/capex/${ticker}`),
  ]);

  renderFundamentalsTable(fundamentals);
  renderPriceChart(prices, fundamentals);
  renderCapexIntensityChart(capex.series);
  renderCapexCycleChart(capex.series);
  renderValuationSummary(ticker);
  populateCompareYears(fundamentals);
}

function populateCompareYears(fundamentals) {
  const select = document.getElementById("compare-year");
  const years = fundamentals.map(r => r.fiscal_year).sort((a, b) => b - a);
  select.innerHTML = years.map(y => `<option value="${y}">FY${y}</option>`).join("");
  loadCompareChart();
}

async function loadCompareChart() {
  const metric = document.getElementById("compare-metric").value;
  const year = document.getElementById("compare-year").value;
  if (!year) return;
  const rows = await getJSON(`/api/compare?metric=${metric}&fiscal_year=${year}`);
  const isPct = metric.includes("margin");
  const trace = {
    x: rows.map(r => r.ticker), y: rows.map(r => r[metric]), type: "bar",
    marker: { color: rows.map((_, i) => SERIES_COLORS[i % SERIES_COLORS.length]) },
    hovertemplate: isPct ? "%{y:.1%}<extra></extra>" : "%{y:,.0f}<extra></extra>",
  };
  Plotly.newPlot("compare-chart", [trace], baseLayout({
    yaxis: Object.assign({}, AXIS_STYLE, isPct ? { tickformat: ".0%" } : {}),
    showlegend: false,
    height: 300,
  }), { displayModeBar: false, responsive: true });
}

function escapeHtml(s) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return s.replace(/[&<>"']/g, c => map[c]);
}

function renderAnswerText(text) {
  // The model's raw text is untrusted (could echo prompt-injected content),
  // so HTML-escape it before applying the small bold/newline markdown subset.
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function renderCitations(citations) {
  if (!citations || !citations.length) return "";
  return citations.map(c =>
    `<a class="citation-chip" href="${c.url}" target="_blank" rel="noopener">${c.label}</a>`
  ).join("");
}

async function askQuestion(question) {
  const answerEl = document.getElementById("qa-answer");
  const traceEl = document.getElementById("qa-trace");
  const traceWrap = document.getElementById("qa-trace-wrap");
  answerEl.textContent = "Thinking…";
  traceWrap.hidden = true;
  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    let data;
    try {
      data = await resp.json();
    } catch {
      throw new Error(`server returned ${resp.status} ${resp.statusText}`);
    }
    if (!resp.ok) throw new Error(data.error || "request failed");
    answerEl.innerHTML = `<div>${renderAnswerText(data.answer)}</div><div>${renderCitations(data.citations)}</div>`;
    if (data.trace) {
      traceEl.textContent = JSON.stringify(data.trace, null, 2);
      traceWrap.hidden = false;
    }
  } catch (e) {
    answerEl.textContent = `Error: ${e.message}`;
  }
}

document.getElementById("ticker-select").addEventListener("click", e => {
  if (e.target.matches(".ticker-btn")) loadTicker(e.target.dataset.ticker);
});
document.getElementById("compare-metric").addEventListener("change", loadCompareChart);
document.getElementById("compare-year").addEventListener("change", loadCompareChart);
document.getElementById("qa-form").addEventListener("submit", e => {
  e.preventDefault();
  const q = document.getElementById("qa-question").value.trim();
  if (q) askQuestion(q);
});

loadTicker(currentTicker);
renderCapexScatter();
