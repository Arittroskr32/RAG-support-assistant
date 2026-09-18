/* Renders assistant answers: Markdown (sanitized), tables with CSV export, Chart.js charts
   from ```chart JSON blocks and Mermaid diagrams from ```mermaid blocks.

   Model output is untrusted. Defences, in order:
   1. The server validates chart/mermaid blocks after the L8 output guard.
   2. Markdown is rendered with marked and sanitized with DOMPurify (no scripts, styles,
      forms, iframes or event handlers survive).
   3. Chart specs are re-validated here and only whitelisted fields reach Chart.js.
   4. Mermaid runs with securityLevel "strict" and its SVG output is sanitized again.
   5. The server's Content-Security-Policy blocks inline and remote scripts. */
"use strict";

const Render = (() => {
  const CHART_TYPES = new Set(["bar", "line", "pie", "doughnut"]);
  const FENCE = /```[ \t]*(chart|mermaid)[ \t]*\n([\s\S]*?)```/gi;
  const ICON = {
    table: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/></svg>',
    chart: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    diagram: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="6" rx="1.5"/><rect x="14" y="15" width="7" height="6" rx="1.5"/><path d="M6.5 9v3a3 3 0 0 0 3 3h4.5"/></svg>',
    copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    download: '<svg viewBox="0 0 24 24"><path d="M12 3v12M7 10l5 5 5-5M4 21h16"/></svg>',
    code: '<svg viewBox="0 0 24 24"><path d="m8 7-5 5 5 5M16 7l5 5-5 5"/></svg>',
  };
  let seq = 0;
  const liveCharts = new WeakMap();   // container -> Chart[]

  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function el(tag, cls, html) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html !== undefined) node.innerHTML = html;
    return node;
  }

  function button(label, icon, onClick) {
    const b = el("button", "meta-btn", `${icon}<span>${escapeHtml(label)}</span>`);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function download(filename, blob) {
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function card(kind, title) {
    const wrap = el("div", "rich");
    const head = el("div", "rich-head");
    head.appendChild(el("span", "rich-kind", ICON[kind]));
    const t = el("span", "title"); t.textContent = title || kind[0].toUpperCase() + kind.slice(1);
    head.appendChild(t);
    const body = el("div", "rich-body");
    wrap.append(head, body);
    return { wrap, head, body };
  }

  /* ---------------- tables ---------------- */
  function tableToCsv(table) {
    return [...table.rows].map((row) => [...row.cells].map((c) => {
      const v = c.textContent.trim();
      return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    }).join(",")).join("\n");
  }

  function enhanceTables(container, notify) {
    container.querySelectorAll("table").forEach((table, i) => {
      const { wrap, head, body } = card("table", `Table ${i + 1}`);
      body.className = "table-scroll";
      table.replaceWith(wrap);
      body.appendChild(table);
      head.append(
        button("Copy", ICON.copy, async () => {
          try { await navigator.clipboard.writeText(tableToCsv(table)); notify("Table copied as CSV"); }
          catch { notify("Couldn't copy"); }
        }),
        button("CSV", ICON.download, () => download(`table-${i + 1}.csv`, new Blob([tableToCsv(table)], { type: "text/csv" }))),
      );
    });
  }

  /* ---------------- charts ---------------- */
  function validateChart(raw) {
    const spec = JSON.parse(raw);
    const type = String(spec.type || "bar").toLowerCase();
    if (!CHART_TYPES.has(type)) throw new Error("type");
    const labels = spec.labels, sets = spec.datasets;
    if (!Array.isArray(labels) || !labels.length || labels.length > 50) throw new Error("labels");
    if (!Array.isArray(sets) || !sets.length || sets.length > 6) throw new Error("datasets");
    const datasets = sets.map((d) => {
      if (!Array.isArray(d.data) || d.data.length !== labels.length) throw new Error("data");
      const data = d.data.map(Number);
      if (data.some((n) => !Number.isFinite(n))) throw new Error("number");
      return { label: String(d.label || "").slice(0, 80), data };
    });
    return { type, title: String(spec.title || "").slice(0, 120), labels: labels.map((l) => String(l).slice(0, 80)),
             datasets: (type === "pie" || type === "doughnut") ? datasets.slice(0, 1) : datasets };
  }

  function buildChart(raw, slot, container) {
    let spec;
    try { spec = validateChart(raw); }
    catch { return fallback(slot, "chart", "The chart data couldn't be displayed.", raw); }

    const { wrap, head, body } = card("chart", spec.title || "Chart");
    const box = el("div", "chart-box");
    const canvas = el("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `${spec.title || "Chart"}: ${spec.labels.join(", ")}`);
    box.appendChild(canvas); body.appendChild(box);
    slot.replaceWith(wrap);

    const palette = [1, 2, 3, 4, 5, 6].map((i) => cssVar(`--chart-${i}`));
    const text = cssVar("--text-2"), grid = cssVar("--chart-grid"), surface = cssVar("--surface");
    const radial = spec.type === "pie" || spec.type === "doughnut";
    const datasets = spec.datasets.map((d, i) => radial
      ? { ...d, backgroundColor: spec.labels.map((_, j) => palette[j % palette.length]), borderColor: surface, borderWidth: 2 }
      : { ...d, backgroundColor: palette[i % palette.length] + (spec.type === "line" ? "33" : ""),
          borderColor: palette[i % palette.length], borderWidth: 2, borderRadius: spec.type === "bar" ? 6 : 0,
          tension: .3, fill: spec.type === "line", pointRadius: 3 });
    const background = { id: "bg", beforeDraw(c) {
      const ctx = c.ctx; ctx.save(); ctx.globalCompositeOperation = "destination-over";
      ctx.fillStyle = surface; ctx.fillRect(0, 0, c.width, c.height); ctx.restore(); } };

    const chart = new Chart(canvas, {
      type: spec.type,
      data: { labels: spec.labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 400 },
        plugins: { legend: { display: radial || datasets.length > 1, labels: { color: text, boxWidth: 12 } } },
        scales: radial ? {} : {
          x: { ticks: { color: text }, grid: { display: false } },
          y: { ticks: { color: text }, grid: { color: grid }, beginAtZero: true },
        },
      },
      plugins: [background],
    });
    const list = liveCharts.get(container) || [];
    list.push(chart); liveCharts.set(container, list);
    head.append(
      button("Data", ICON.copy, async () => {
        const rows = [["label", ...spec.datasets.map((d) => d.label || "value")],
                      ...spec.labels.map((l, j) => [l, ...spec.datasets.map((d) => d.data[j])])];
        try { await navigator.clipboard.writeText(rows.map((r) => r.join(",")).join("\n")); } catch { /* ignore */ }
      }),
      button("PNG", ICON.download, () => {
        const a = el("a"); a.href = chart.toBase64Image("image/png", 1);
        a.download = `${(spec.title || "chart").replace(/[^\w-]+/g, "_")}.png`; a.click();
      }),
    );
  }

  /* ---------------- diagrams ---------------- */
  async function buildDiagram(src, slot) {
    const { wrap, head, body } = card("diagram", "Diagram");
    const target = el("div", "diagram");
    body.appendChild(target);
    slot.replaceWith(wrap);
    try {
      // htmlLabels must be off at the root (Mermaid 11+): HTML labels live in <foreignObject>,
      // which the SVG sanitizer below removes, leaving empty boxes. SVG <text> labels survive.
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: isDark() ? "dark" : "default",
                           htmlLabels: false, flowchart: { htmlLabels: false }, fontFamily: cssVar("--font") });
      const { svg } = await mermaid.render(`mmd-${Date.now()}-${seq++}`, src);
      const clean = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ["style"] });
      target.innerHTML = clean;
      head.append(
        button("Source", ICON.code, () => {
          const pre = body.querySelector("pre");
          if (pre) { pre.remove(); return; }
          const p = el("pre"); p.textContent = src; body.appendChild(p);
        }),
        button("SVG", ICON.download, () => download("diagram.svg", new Blob([clean], { type: "image/svg+xml" }))),
      );
    } catch {
      wrap.replaceWith(fallback(null, "diagram", "This diagram couldn't be drawn.", src));
    }
  }

  function fallback(slot, kind, message, source) {
    const { wrap, body } = card(kind, kind === "chart" ? "Chart" : "Diagram");
    const box = el("div", "rich-error");
    box.textContent = message;
    const pre = el("pre"); pre.textContent = source;
    box.appendChild(pre); body.appendChild(box);
    if (slot) slot.replaceWith(wrap);
    return wrap;
  }

  /* ---------------- main entry ---------------- */
  function renderAnswer(container, text, citations, notify = () => {}) {
    destroy(container);
    const slots = [];
    let md = String(text || "").replace(FENCE, (_, kind, body) => {
      slots.push({ kind: kind.toLowerCase(), body: body.trim() });
      return `\n\n<div data-rich-slot="${slots.length - 1}"></div>\n\n`;
    });
    md = md.replace(/\[(c\d+)\]/g, (_, c) =>
      `<sup class="cite" title="${escapeHtml((citations && citations[c]) || "Source")}">${c.slice(1)}</sup>`);

    const html = marked.parse(md, { gfm: true, breaks: false });
    container.innerHTML = DOMPurify.sanitize(html, {
      ADD_ATTR: ["data-rich-slot"],
      FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed"],
      FORBID_ATTR: ["style"],
    });

    container.querySelectorAll("a[href]").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
    enhanceTables(container, notify);
    container.querySelectorAll("[data-rich-slot]").forEach((slot) => {
      const s = slots[Number(slot.getAttribute("data-rich-slot"))];
      if (!s) { slot.remove(); return; }
      if (s.kind === "chart") buildChart(s.body, slot, container);
      else buildDiagram(s.body, slot);
    });
  }

  function destroy(container) {
    (liveCharts.get(container) || []).forEach((c) => c.destroy());
    liveCharts.delete(container);
  }

  return { renderAnswer, destroy, escapeHtml };
})();
