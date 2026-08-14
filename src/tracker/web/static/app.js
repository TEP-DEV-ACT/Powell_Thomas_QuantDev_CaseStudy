const UNIVERSE = Array.from(document.querySelectorAll(".ticker-btn")).map(b => b.dataset.ticker);
let currentTicker = UNIVERSE[0];

// Plotly can't read CSS custom properties, so the palette is mirrored here.
// Keep these in sync with the .viz-root block in style.css — that file also
// explains why the chart series are derived from the Schonfeld brand hues
// rather than being the brand hex values themselves.
const PALETTE = {
  surface: "#fbfaf7",
  textSecondary: "#57544e",
  textMuted: "#8a857c",
  gridline: "#e4ded3",
  baseline: "#cdc6b8",
  series: ["#4174ec", "#30b6ba", "#c39c2e", "#7942b0", "#3a8753"],
};

// Colour follows the company, not its position in a sorted list — otherwise
// re-sorting the compare chart between fiscal years repaints every bar and
// the reader loses the thread.
const TICKER_COLORS = Object.fromEntries(
  UNIVERSE.map((t, i) => [t, PALETTE.series[i % PALETTE.series.length]])
);

// /api/prices takes a row limit, not a number of calendar days — 756 trading
// days is the ~3 years that ingest/prices.py actually fetches (PERIOD = "3y").
const PRICE_WINDOW_ROWS = 756;

// Mirrors --font-sans in style.css. Plotly measures text with whatever the
// browser has loaded, so the boot at the bottom of this file waits on
// document.fonts.ready before the first plot.
const PLOTLY_FONT = { family: "Montserrat, 'Helvetica Neue', Helvetica, Arial, sans-serif", color: PALETTE.textSecondary, size: 12 };
const AXIS_STYLE = { gridcolor: PALETTE.gridline, zerolinecolor: PALETTE.baseline, linecolor: PALETTE.baseline, tickfont: PLOTLY_FONT };

// No `height` here on purpose: the plot containers are sized by CSS (.plot),
// which is what lets a card grow when it goes fullscreen. Plotly picks the
// container height up via responsive:true plus the ResizeObserver below.
function baseLayout(extra) {
  return Object.assign({
    font: PLOTLY_FONT,
    paper_bgcolor: PALETTE.surface,
    plot_bgcolor: PALETTE.surface,
    margin: { l: 50, r: 20, t: 10, b: 40 },
    xaxis: Object.assign({}, AXIS_STYLE),
    yaxis: Object.assign({}, AXIS_STYLE),
    hovermode: "x unified",
  }, extra);
}

const PLOT_CONFIG = { displayModeBar: false, responsive: true };

async function getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

function fmtNum(v, decimals = 0) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: decimals });
}

// EDGAR reports in whole dollars, which is unreadable at these magnitudes.
// The rescale is display-only — the API, the metrics layer and the AI tools
// all keep raw dollars, so nothing downstream has to track two unit systems.
function fmtMillions(v) {
  if (v === null || v === undefined) return "—";
  return Number(v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 0 });
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

// ---------------------------------------------------------------------------
// Fundamentals table
// ---------------------------------------------------------------------------

// One spec drives both the on-screen table and the spreadsheet export, so the
// two can't drift. `fmt`/`yoy*` are the display side; `xls*` is the export side,
// which keeps raw numbers (scaled to the unit named in the label) and lets
// Excel do the formatting — a sheet full of "365,817 ▲ 7.8%" strings can't be
// charted or summed.
const FUNDAMENTAL_METRICS = [
  { key: "revenue", label: "Revenue ($M)", fmt: fmtMillions, yoyKey: "revenue_yoy",
    xlsScale: 1e-6, xlsFmt: "#,##0", yoyLabel: "Revenue YoY", yoyFmt: "0.0%",
    tip: "As-reported annual revenue from the 10-K, taken from whichever XBRL revenue tag the company uses (RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, or a similar fallback)." },
  { key: "net_income", label: "Net income ($M)", fmt: fmtMillions, yoyKey: "net_income_yoy",
    xlsScale: 1e-6, xlsFmt: "#,##0", yoyLabel: "Net income YoY", yoyFmt: "0.0%",
    tip: "As-reported GAAP net income for the fiscal year, from the NetIncomeLoss (or ProfitLoss) XBRL tag." },
  // No YoY on this row — it's the adjustment itself (an as-reported non-
  // operating swing), not a metric that's meaningful to grow/shrink YoY.
  { key: "other_income_adjustments", label: "Other income adjustments ($M)", fmt: fmtMillions,
    yoyKey: null, xlsScale: 1e-6, xlsFmt: "#,##0", yoyLabel: "", yoyFmt: "",
    tip: "The pre-tax 'Other income (expense), net' line from the income statement, which can bundle equity-investment gains/losses with interest income/expense — this is what Adjusted net income backs out below." },
  { key: "adjusted_net_income", label: "Adjusted net income ($M)", fmt: fmtMillions,
    yoyKey: "adjusted_net_income_yoy",
    xlsScale: 1e-6, xlsFmt: "#,##0", yoyLabel: "Adjusted net income YoY", yoyFmt: "0.0%",
    tip: "Net income with Other income adjustments backed out at the company's own effective tax rate for the year (income tax expense divided by pretax income), so a one-off investment gain or loss doesn't read as a change in operating performance." },
  { key: "eps_diluted", label: "Diluted EPS", fmt: v => v == null ? "—" : Number(v).toFixed(2),
    yoyKey: "eps_diluted_yoy", swingThreshold: 0.5,
    xlsScale: 1, xlsFmt: "0.00", yoyLabel: "Diluted EPS YoY", yoyFmt: "0.0%",
    tip: "As-reported GAAP diluted earnings per share for the fiscal year, from the EarningsPerShareDiluted XBRL tag." },
  { key: "gross_margin", label: "Gross margin", fmt: v => fmtPct(v),
    yoyKey: "gross_margin_delta_bps", isBps: true,
    xlsScale: 1, xlsFmt: "0.0%", yoyLabel: "Gross margin Δ (bps)", yoyFmt: "0",
    tip: "Gross profit divided by revenue, where gross profit is either reported directly or derived as revenue minus cost of revenue for filers that don't report a gross profit subtotal." },
  { key: "operating_margin", label: "Operating margin", fmt: v => fmtPct(v),
    yoyKey: "operating_margin_delta_bps", isBps: true,
    xlsScale: 1, xlsFmt: "0.0%", yoyLabel: "Operating margin Δ (bps)", yoyFmt: "0",
    tip: "Operating income divided by revenue, from the OperatingIncomeLoss XBRL tag divided by reported revenue." },
  { key: "free_cash_flow", label: "Free cash flow ($M)", fmt: fmtMillions, yoyKey: "free_cash_flow_yoy",
    xlsScale: 1e-6, xlsFmt: "#,##0", yoyLabel: "Free cash flow YoY", yoyFmt: "0.0%",
    tip: "Cash from operating activities minus capital expenditure, both taken directly from the reported cash flow statement." },
];

// Populated by every card's render function (table and chart alike) with the
// same { sheetName, aoa, rowFormats|colFormats } shape; read by the
// copy/download toolbar so Excel export works identically everywhere.
const CARD_EXPORTS = {};

function renderFundamentalsTable(rows) {
  const recent = rows.slice(-5);

  let html = "<table class='fundamentals'><thead><tr><th>Fiscal year</th>";
  for (const row of recent) {
    html += `<th>FY${row.fiscal_year}<br><span class="muted">${row.period_end ?? ""}</span></th>`;
  }
  html += "</tr></thead><tbody>";

  const aoa = [["Metric", ...recent.map(r => `FY${r.fiscal_year}`)]];
  const rowFormats = [null];
  const periodRow = ["Period end", ...recent.map(r => r.period_end ?? null)];

  for (const m of FUNDAMENTAL_METRICS) {
    html += `<tr><td>${m.label} <span class="info-icon" title="${m.tip}">ⓘ</span></td>`;
    const values = [];
    const deltas = [];
    for (const row of recent) {
      const raw = row[m.key];
      const yoy = row[m.yoyKey];
      html += `<td>${m.fmt(raw)}<br>${deltaSpan(yoy, 1, !!m.isBps, m.swingThreshold ?? 1.0)}</td>`;
      values.push(raw == null ? null : raw * m.xlsScale);
      deltas.push(yoy == null ? null : yoy);
    }
    html += "</tr>";
    // Each YoY gets its own spreadsheet row rather than sharing a cell with
    // the level, so both columns stay numeric. Metrics with no YoY key (e.g.
    // other_income_adjustments — an adjustment, not something meaningful to
    // grow/shrink) skip that row instead of exporting an all-blank one.
    aoa.push([m.label, ...values]);
    rowFormats.push(m.xlsFmt);
    if (m.yoyKey) {
      aoa.push([m.yoyLabel, ...deltas]);
      rowFormats.push(m.yoyFmt);
    }
  }
  html += "</tbody></table>";
  document.getElementById("fundamentals-table").innerHTML = html;

  aoa.splice(1, 0, periodRow);
  rowFormats.splice(1, 0, null);
  CARD_EXPORTS.fundamentals = { sheetName: "Fundamentals", aoa, rowFormats };
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

function renderPriceChart(ticker, prices, fundamentals) {
  const chart = document.getElementById("price-chart");
  CARD_EXPORTS.price = {
    sheetName: "Price",
    aoa: [["Date", "Close"], ...prices.map(p => [p.trade_date, p.close])],
    colFormats: [null, "0.00"],
  };
  if (!prices.length) {
    Plotly.purge(chart);
    chart.innerHTML = `<p class="muted">No price history for ${ticker}.</p>`;
    return;
  }
  const trace = {
    x: prices.map(p => p.trade_date),
    y: prices.map(p => p.close),
    type: "scatter",
    mode: "lines",
    line: { color: TICKER_COLORS[ticker], width: 2 },
    name: "Close",
    hovertemplate: "%{y:.2f}<extra></extra>",
  };

  // Rows arrive ascending (routes_api.py reverses its DESC query), so these
  // bracket the window the price data actually covers.
  const windowStart = prices[0].trade_date;
  const windowEnd = prices[prices.length - 1].trade_date;

  const shapes = [];
  const annotations = [];
  for (const row of fundamentals) {
    // Fundamentals reach back to FY2009 for some tickers while prices only
    // cover ~3 years. A shape placed at an out-of-window date is still an
    // x-axis data point to Plotly, so leaving these in stretches the axis to
    // a decade and squeezes the price line into the right-hand edge.
    if (!row.period_end) continue;
    if (row.period_end < windowStart || row.period_end > windowEnd) continue;
    shapes.push({
      type: "line", x0: row.period_end, x1: row.period_end, yref: "paper", y0: 0, y1: 1,
      line: { color: PALETTE.baseline, width: 1, dash: "dot" },
    });
    annotations.push({
      x: row.period_end, y: 1, yref: "paper", yanchor: "bottom", showarrow: false,
      text: `FY${row.fiscal_year}`, font: { size: 10, color: PALETTE.textMuted },
    });
  }

  Plotly.newPlot("price-chart", [trace], baseLayout({
    shapes,
    annotations,
    // Pin the window explicitly rather than relying on autorange.
    xaxis: Object.assign({}, AXIS_STYLE, { range: [windowStart, windowEnd] }),
    // The FY labels are anchored above the plot area and now all fall inside
    // the window, so the default 10px top margin clips them.
    margin: { l: 50, r: 20, t: 24, b: 40 },
    showlegend: false,
  }), PLOT_CONFIG);
}

function renderCapexIntensityChart(series) {
  // Gaps in the underlying capex tag (see DESIGN.md known limitations, e.g.
  // NVDA FY2012-2023) are dropped rather than drawn as zero-height bars.
  const present = series.filter(s => s.capex_intensity != null);
  CARD_EXPORTS["capex-intensity"] = {
    sheetName: "Capex intensity",
    aoa: [["Fiscal year", "Capex intensity"], ...present.map(s => [`FY${s.fiscal_year}`, s.capex_intensity])],
    colFormats: [null, "0.0%"],
  };
  const trace = {
    x: present.map(s => `FY${s.fiscal_year}`),
    y: present.map(s => s.capex_intensity),
    type: "bar",
    marker: { color: PALETTE.series[0] },
    hovertemplate: "%{y:.1%}<extra></extra>",
  };
  Plotly.newPlot("capex-intensity-chart", [trace], baseLayout({
    yaxis: Object.assign({}, AXIS_STYLE, { tickformat: ".0%" }),
    showlegend: false,
  }), PLOT_CONFIG);
}

function renderCapexCycleChart(series) {
  // Anchor the x-axis to years where the company itself has capex data —
  // the FRED series has every year, so filtering on "either" would keep
  // showing the company's gap years as empty stretches instead of skipping them.
  const present = series.filter(s => s.capex_yoy != null);
  const years = present.map(s => `FY${s.fiscal_year}`);
  CARD_EXPORTS["capex-cycle"] = {
    sheetName: "Capex cycle",
    aoa: [["Fiscal year", "Company capex YoY", "National capex YoY"],
          ...present.map(s => [`FY${s.fiscal_year}`, s.capex_yoy, s.macro_capex_yoy])],
    colFormats: [null, "0.0%", "0.0%"],
  };
  const traces = [
    {
      x: years, y: present.map(s => s.capex_yoy), type: "scatter", mode: "lines+markers",
      name: "Company capex YoY", line: { color: PALETTE.series[0], width: 2 }, marker: { size: 8 }, connectgaps: false,
    },
    {
      x: years, y: present.map(s => s.macro_capex_yoy), type: "scatter", mode: "lines+markers",
      // The FRED PNFI attribution lives in the card heading — spelled out here
      // the legend overruns the plot width and gets clipped.
      name: "National capex YoY", line: { color: PALETTE.series[2], width: 2 }, marker: { size: 8 }, connectgaps: false,
    },
  ];
  Plotly.newPlot("capex-cycle-chart", traces, baseLayout({
    margin: { l: 50, r: 20, t: 10, b: 60 },
    yaxis: Object.assign({}, AXIS_STYLE, { tickformat: ".0%" }),
    showlegend: true,
    legend: { orientation: "h", y: -0.25 },
  }), PLOT_CONFIG);
}

async function renderCapexScatter() {
  const points = [];
  const results = await Promise.all(UNIVERSE.map(async ticker => {
    try {
      const [fundamentals, capex] = await Promise.all([
        getJSON(`/api/fundamentals/${ticker}`),
        getJSON(`/api/capex/${ticker}`),
      ]);
      return { ticker, fundamentals, capex };
    } catch (e) {
      console.warn("scatter skip", ticker, e);
      return null;
    }
  }));
  for (const r of results) {
    if (!r) continue;
    const lastFund = r.fundamentals[r.fundamentals.length - 1];
    const lastCapex = r.capex.series[r.capex.series.length - 1];
    if (lastFund && lastCapex && lastFund.revenue_yoy != null && lastCapex.capex_intensity != null) {
      points.push({ ticker: r.ticker, x: lastFund.revenue_yoy, y: lastCapex.capex_intensity });
    }
  }
  CARD_EXPORTS["capex-scatter"] = {
    sheetName: "Capex vs revenue growth",
    aoa: [["Ticker", "Revenue YoY", "Capex intensity"], ...points.map(p => [p.ticker, p.x, p.y])],
    colFormats: [null, "0.0%", "0.0%"],
  };
  const trace = {
    x: points.map(p => p.x), y: points.map(p => p.y), text: points.map(p => p.ticker),
    mode: "markers+text", type: "scatter", textposition: "top center",
    marker: {
      size: 12,
      color: points.map(p => TICKER_COLORS[p.ticker]),
      // A 2px surface ring keeps two near-coincident companies readable.
      line: { color: PALETTE.surface, width: 2 },
    },
    textfont: { color: PALETTE.textSecondary, size: 12 },
    hovertemplate: "%{text}<br>Revenue YoY: %{x:.1%}<br>Capex intensity: %{y:.1%}<extra></extra>",
  };
  Plotly.newPlot("capex-scatter-chart", [trace], baseLayout({
    margin: { l: 60, r: 20, t: 16, b: 50 },
    xaxis: Object.assign({}, AXIS_STYLE, { title: "Revenue YoY growth", tickformat: ".0%" }),
    yaxis: Object.assign({}, AXIS_STYLE, { title: "Capex intensity", tickformat: ".0%" }),
    showlegend: false,
  }), PLOT_CONFIG);
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

  let fundamentals, prices, capex;
  try {
    [fundamentals, prices, capex] = await Promise.all([
      getJSON(`/api/fundamentals/${ticker}`),
      getJSON(`/api/prices/${ticker}?days=${PRICE_WINDOW_ROWS}`),
      getJSON(`/api/capex/${ticker}`),
    ]);
  } catch (e) {
    // A silent failure here would leave the previous ticker's charts on
    // screen looking current when they aren't, or nothing at all after the
    // ticker buttons have already switched — surface it instead.
    console.error(`loadTicker(${ticker}) failed`, e);
    toast(`Couldn't load data for ${ticker} — try again in a moment.`);
    return;
  }

  renderFundamentalsTable(fundamentals);
  renderPriceChart(ticker, prices, fundamentals);
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

// Every compare option is a ratio now (margin or yield), not a dollar
// figure, but fcf_yield's values sit in the low single-digit percent range
// where ".0%" rounds to 0 — give it an extra decimal.
const COMPARE_FORMATS = {
  fcf_yield: { hover: "%{y:.2%}<extra></extra>", tick: ".2%" },
};
const DEFAULT_COMPARE_FORMAT = { hover: "%{y:.1%}<extra></extra>", tick: ".0%" };

async function loadCompareChart() {
  const metric = document.getElementById("compare-metric").value;
  const year = document.getElementById("compare-year").value;
  if (!year) return;
  let rows;
  try {
    rows = await getJSON(`/api/compare?metric=${metric}&fiscal_year=${year}`);
  } catch (e) {
    console.error("loadCompareChart failed", e);
    toast("Couldn't load the comparison chart — try again in a moment.");
    return;
  }
  const fmt = COMPARE_FORMATS[metric] || DEFAULT_COMPARE_FORMAT;
  const metricLabel = document.getElementById("compare-metric").selectedOptions[0].text;
  CARD_EXPORTS.compare = {
    sheetName: "Cross-company compare",
    aoa: [["Ticker", metricLabel], ...rows.map(r => [r.ticker, r[metric]])],
    colFormats: [null, metric === "fcf_yield" ? "0.00%" : "0.0%"],
  };
  const trace = {
    x: rows.map(r => r.ticker), y: rows.map(r => r[metric]), type: "bar",
    // Half-slot bars in category units, so a year with only two reporting
    // companies doesn't render as two slabs across the full panel width.
    width: 0.5,
    // Keyed on the ticker, not the bar index, so a company keeps its colour
    // as the ranking reshuffles between metrics and fiscal years.
    marker: { color: rows.map(r => TICKER_COLORS[r.ticker]) },
    hovertemplate: fmt.hover,
  };
  Plotly.newPlot("compare-chart", [trace], baseLayout({
    yaxis: Object.assign({}, AXIS_STYLE, { tickformat: fmt.tick }),
    showlegend: false,
  }), PLOT_CONFIG);
}

// ---------------------------------------------------------------------------
// Card toolbar — copy / download / fullscreen on every chart and table
// ---------------------------------------------------------------------------

const ICONS = {
  copy: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="5.5" width="8.5" height="8.5" rx="1.5"/><path d="M10.5 5.5v-2A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>',
  check: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8.5 3.5 3.5L13 4.5"/></svg>',
  download: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v7.5m0 0 3-3m-3 3-3-3"/><path d="M2.5 13.5h11"/></svg>',
  expand: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 2h-4v4M9.5 2h4v4M6.5 14h-4v-4M9.5 14h4v-4"/></svg>',
};

function buildCardTools() {
  for (const card of document.querySelectorAll("[data-card]")) {
    const title = card.dataset.title;
    // Every card — table or chart — offers the same three formats, backed by
    // the same download logic below (CARD_EXPORTS for xlsx, html2canvas or
    // Plotly for the images) so none of them drift out of sync.
    let items =
      '<button type="button" data-act="download" data-format="xlsx">Excel (.xlsx)</button>' +
      '<button type="button" data-act="download" data-format="png">PNG image</button>' +
      '<button type="button" data-act="download" data-format="jpeg">JPEG image</button>';
    // Opt-in per card — only the price card has an underlying raw endpoint
    // worth exporting as CSV on top of the three universal formats.
    if (card.dataset.csv) {
      items += '<button type="button" data-act="download" data-format="csv">Data (.csv)</button>';
    }

    const tools = document.createElement("div");
    tools.className = "card-tools";
    tools.innerHTML =
      `<button type="button" class="icon-btn" data-act="copy"
               title="Copy ${title}" aria-label="Copy ${title}">${ICONS.copy}</button>` +
      `<details class="dl-menu">
         <summary class="icon-btn" title="Download ${title}" aria-label="Download ${title}">${ICONS.download}</summary>
         <div class="dl-menu-items">${items}</div>
       </details>` +
      `<button type="button" class="icon-btn" data-act="fullscreen"
               title="Fullscreen ${title}" aria-label="Fullscreen ${title}">${ICONS.expand}</button>`;
    card.querySelector(".card-head").appendChild(tools);
  }
}

let toastTimer = null;
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

// A copied button briefly shows a tick, which reads faster than a toast for
// an action whose whole result is invisible.
function flashOk(btn) {
  const original = btn.innerHTML;
  btn.innerHTML = ICONS.check;
  btn.classList.add("is-ok");
  setTimeout(() => { btn.innerHTML = original; btn.classList.remove("is-ok"); }, 1300);
}

// Cross-company cards are named for the universe; the rest carry the ticker
// they're currently showing, so a folder of downloads stays self-describing.
function exportBaseName(card) {
  const id = card.dataset.card;
  if (id === "compare") {
    const metric = document.getElementById("compare-metric").value;
    const year = document.getElementById("compare-year").value;
    return `universe_compare_${metric}_FY${year}`;
  }
  return `${card.dataset.scope === "universe" ? "universe" : currentTicker}_${id}`;
}

// The element a card's toolbar actions act on — a Plotly div for charts, the
// rendered <table>'s container for tables.
function cardTarget(card) {
  return document.getElementById(card.dataset.target);
}

function cardExportSpec(card) {
  const spec = CARD_EXPORTS[card.dataset.card];
  if (!spec) throw new Error("no data loaded yet");
  return spec;
}

function aoaToTsv(aoa) {
  return aoa.map(row => row.map(v => (v == null ? "" : String(v))).join("\t")).join("\n");
}

async function copyCard(card, btn) {
  try {
    if (card.dataset.kind === "chart") {
      const dataUrl = await Plotly.toImage(cardTarget(card), { format: "png", scale: 2 });
      const blob = await (await fetch(dataUrl)).blob();
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    } else {
      const spec = cardExportSpec(card);
      const tsv = aoaToTsv(spec.aoa);
      const table = card.querySelector("table");
      try {
        // Both flavours: the HTML pastes into Excel/Sheets/Word as a real
        // grid, the TSV covers plain-text targets and older clipboards.
        await navigator.clipboard.write([new ClipboardItem({
          "text/html": new Blob([table.outerHTML], { type: "text/html" }),
          "text/plain": new Blob([tsv], { type: "text/plain" }),
        })]);
      } catch {
        await navigator.clipboard.writeText(tsv);
      }
    }
    flashOk(btn);
  } catch (e) {
    console.warn("copy failed", e);
    toast(card.dataset.kind === "chart"
      ? "This browser won't let a page copy images — use Download instead."
      : `Copy failed: ${e.message}`);
  }
}

// Applies a spec's number formats to a freshly built worksheet. Fundamentals
// is row-oriented (one metric per row, a value per fiscal year), so its
// format varies by row; every chart export is column-oriented (one field per
// column, a value per record), so its format varies by column. A spec
// carries exactly one of the two.
function applyFormats(ws, spec) {
  const nRows = spec.aoa.length;
  const nCols = spec.aoa[0].length;
  if (spec.rowFormats) {
    spec.rowFormats.forEach((z, r) => {
      if (!z) return;
      for (let c = 1; c < nCols; c++) {
        const cell = ws[XLSX.utils.encode_cell({ r, c })];
        if (cell && cell.t === "n") cell.z = z;
      }
    });
  } else if (spec.colFormats) {
    spec.colFormats.forEach((z, c) => {
      if (!z) return;
      for (let r = 1; r < nRows; r++) {
        const cell = ws[XLSX.utils.encode_cell({ r, c })];
        if (cell && cell.t === "n") cell.z = z;
      }
    });
  }
}

// Chart cards rasterize via Plotly's own exporter; table cards have no
// built-in one, so html2canvas shoots the same element the toolbar sits on
// top of. Both land on the same {name}.{format} naming as the xlsx/csv paths.
async function downloadTableImage(card, format, name) {
  try {
    const canvas = await html2canvas(cardTarget(card), { backgroundColor: PALETTE.surface, scale: 2 });
    const mime = format === "jpeg" ? "image/jpeg" : "image/png";
    const a = document.createElement("a");
    a.href = canvas.toDataURL(mime, 0.92);
    a.download = `${name}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    console.warn("table image export failed", e);
    toast(`Download failed: ${e.message}`);
  }
}

async function downloadCard(card, format) {
  const name = exportBaseName(card);
  if (format === "csv") {
    // Content-Disposition: attachment means this never navigates the page.
    const a = document.createElement("a");
    a.href = `/api/prices/${currentTicker}.csv?days=${PRICE_WINDOW_ROWS}`;
    a.download = `${name}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  if (format === "xlsx") {
    const spec = cardExportSpec(card);
    const ws = XLSX.utils.aoa_to_sheet(spec.aoa);
    applyFormats(ws, spec);
    ws["!cols"] = spec.aoa[0].map((_, i) => ({ wch: i === 0 ? 26 : 14 }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, spec.sheetName);
    XLSX.writeFile(wb, `${name}.xlsx`);
    return;
  }
  // png / jpeg
  if (card.dataset.kind === "chart") {
    Plotly.downloadImage(cardTarget(card), { format, scale: 2, filename: name });
  } else {
    await downloadTableImage(card, format, name);
  }
}

function toggleFullscreen(card) {
  if (document.fullscreenElement === card) {
    document.exitFullscreen();
    return;
  }
  if (card.classList.contains("faux-fullscreen")) {
    card.classList.remove("faux-fullscreen");
    return;
  }
  const request = card.requestFullscreen?.();
  if (request) {
    // Rejected when the page is in a sandboxed iframe or the gesture was
    // consumed — fall back to an in-page overlay rather than doing nothing.
    request.catch(() => card.classList.add("faux-fullscreen"));
  } else {
    card.classList.add("faux-fullscreen");
  }
}

function initCardTools() {
  buildCardTools();

  document.getElementById("card-grid").addEventListener("click", e => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const card = btn.closest("[data-card]");
    if (!card) return;
    btn.closest("details.dl-menu")?.removeAttribute("open");

    if (btn.dataset.act === "copy") copyCard(card, btn);
    else if (btn.dataset.act === "download") downloadCard(card, btn.dataset.format);
    else if (btn.dataset.act === "fullscreen") toggleFullscreen(card);
  });

  // <details> menus don't close themselves when you click elsewhere.
  document.addEventListener("click", e => {
    for (const menu of document.querySelectorAll("details.dl-menu[open]")) {
      if (!menu.contains(e.target)) menu.removeAttribute("open");
    }
  });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.dl-menu[open]").forEach(m => m.removeAttribute("open"));
    // Native fullscreen already exits on Escape; the fallback overlay doesn't.
    document.querySelectorAll(".card.faux-fullscreen").forEach(c => c.classList.remove("faux-fullscreen"));
  });
}

// Plotly's own responsive:true only listens to window resize. Everything that
// actually changes a chart's width here — collapsing the chat rail, entering
// fullscreen — resizes the *container* instead, so one observer covers all of
// it. Trailing-debounced rather than per-frame: the rail collapse is a 180ms
// width transition, and relaying out five charts on every frame of it is
// visibly worse than doing it once at the end.
const RESIZE_DEBOUNCE_MS = 120;

function observePlots() {
  const pending = new Set();
  let timer = null;
  const observer = new ResizeObserver(entries => {
    for (const entry of entries) pending.add(entry.target);
    clearTimeout(timer);
    timer = setTimeout(() => {
      for (const el of pending) {
        if (el._fullLayout) Plotly.Plots.resize(el);   // skip not-yet-plotted divs
      }
      pending.clear();
    }, RESIZE_DEBOUNCE_MS);
  });
  document.querySelectorAll(".plot").forEach(el => observer.observe(el));
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

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

// The transcript the server replays on the next question. Only completed turns
// go in — a failed request leaves it untouched so the error can't poison the
// next call.
const chatHistory = [];

function appendMessage(role) {
  const log = document.getElementById("chat-log");
  log.querySelector(".chat-empty")?.remove();
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function setChatBusy(busy) {
  document.getElementById("qa-send").disabled = busy;
  document.getElementById("qa-question").disabled = busy;
}

function appendTrace(botEl, trace) {
  const details = document.createElement("details");
  details.className = "msg-trace";
  const summary = document.createElement("summary");
  summary.textContent = `Tool-call trace (${trace.length})`;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(trace, null, 2);
  details.append(summary, pre);
  botEl.appendChild(details);
}

async function askQuestion(question) {
  appendMessage("user").textContent = question;
  const botEl = appendMessage("bot");
  botEl.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  setChatBusy(true);

  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: chatHistory }),
    });
    let data;
    try {
      data = await resp.json();
    } catch {
      throw new Error(`server returned ${resp.status} ${resp.statusText}`);
    }
    if (!resp.ok) throw new Error(data.error || "request failed");

    botEl.innerHTML = renderAnswerText(data.answer);
    if (data.citations?.length) {
      const chips = document.createElement("div");
      chips.className = "msg-citations";
      chips.innerHTML = renderCitations(data.citations);
      botEl.appendChild(chips);
    }
    if (data.trace?.length) appendTrace(botEl, data.trace);
    chatHistory.push({ role: "user", content: question }, { role: "assistant", content: data.answer });
  } catch (e) {
    botEl.classList.add("is-error");
    botEl.textContent = `Error: ${e.message}`;
  } finally {
    setChatBusy(false);
    const log = document.getElementById("chat-log");
    log.scrollTop = log.scrollHeight;
  }
}

function initChat() {
  const form = document.getElementById("qa-form");
  const input = document.getElementById("qa-question");

  const submit = () => {
    const q = input.value.trim();
    if (!q || document.getElementById("qa-send").disabled) return;
    input.value = "";
    input.style.height = "";
    askQuestion(q);
  };

  form.addEventListener("submit", e => { e.preventDefault(); submit(); });

  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  });

  // Grow with the question up to the max-height set in CSS, then scroll.
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  });
}

const CHAT_STATE_KEY = "tracker.chat";

function setChatCollapsed(collapsed) {
  const root = document.getElementById("viz-root");
  const toggle = document.getElementById("chat-toggle");
  const expand = document.getElementById("chat-expand");
  root.dataset.chat = collapsed ? "collapsed" : "open";
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.title = collapsed ? "Expand chat" : "Collapse chat";
  // The rail tab and the toggle are the same control in two positions; only
  // the visible one should be reachable by keyboard.
  expand.tabIndex = collapsed ? 0 : -1;
  expand.setAttribute("aria-hidden", String(!collapsed));
  try { localStorage.setItem(CHAT_STATE_KEY, collapsed ? "collapsed" : "open"); } catch { /* private mode */ }
}

function initChatCollapse() {
  const collapsed = (() => {
    try { return localStorage.getItem(CHAT_STATE_KEY) === "collapsed"; } catch { return false; }
  })();
  setChatCollapsed(collapsed);
  document.getElementById("chat-toggle").addEventListener("click", () => {
    setChatCollapsed(document.getElementById("viz-root").dataset.chat !== "collapsed");
  });
  document.getElementById("chat-expand").addEventListener("click", () => setChatCollapsed(false));
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.getElementById("ticker-select").addEventListener("click", e => {
  if (e.target.matches(".ticker-btn")) loadTicker(e.target.dataset.ticker);
});
document.getElementById("compare-metric").addEventListener("change", loadCompareChart);
document.getElementById("compare-year").addEventListener("change", loadCompareChart);

initCardTools();
initChat();
initChatCollapse();
observePlots();

// Plotly lays out axis ticks against measured text width, so plotting before
// Montserrat has loaded produces margins sized for the fallback face.
document.fonts.ready.then(() => {
  loadTicker(currentTicker);
  renderCapexScatter();
});
