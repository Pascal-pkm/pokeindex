/* PokéIndex – privates Pokémon-Markt-Dashboard (eigene Umsetzung) */
"use strict";

/* ---------------------------------------------------------------- Helfer */
const $ = (sel, el) => (el || document).querySelector(sel);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};
const fmtUsd = v => v == null ? "—" :
  v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " $";
const fmtUsd0 = v => v == null ? "—" : v.toLocaleString("de-DE") + " $";
const fmtLvl = v => v == null ? "—" :
  v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDate = d => {
  const [y, m, day] = d.split("-");
  return `${day}.${m}.${y}`;
};
const esc = s => (s || "").replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pctHtml = (v, carried) => {
  if (carried) return '<span class="dagger" title="Preis fortgeschrieben – keine aktuellen Verkäufe">†&nbsp;—</span>';
  if (v == null) return '<span class="pct flat">—</span>';
  const cls = v > 0 ? "up" : v < 0 ? "down" : "flat";
  const arrow = v > 0 ? "▲ " : v < 0 ? "▼ " : "";
  return `<span class="pct ${cls}">${arrow}${Math.abs(v).toLocaleString("de-DE",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %</span>`;
};
const imgUrl = id => `https://tcgplayer-cdn.tcgplayer.com/product/${id}_in_200x200.jpg`;

/* ------------------------------------------------------------- Navigation */
const nav = $("#nav");
nav.addEventListener("click", e => {
  const btn = e.target.closest("button");
  if (!btn) return;
  nav.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".view").forEach(v =>
    v.classList.toggle("visible", v.id === "view-" + btn.dataset.view));
  window.scrollTo(0, 0);
});

/* ------------------------------------------------------------- SVG-Chart */
function renderChart(container, series, opts) {
  opts = opts || {};
  const W = 900, H = 320, padL = 56, padR = 16, padT = 14, padB = 30;
  container.innerHTML = "";
  if (!series || series.length < 2) {
    container.append(el("p", "note", "Noch nicht genug Datenpunkte für einen Chart – die Historie wächst mit jedem Tageslauf (Backfill läuft automatisch)."));
    return;
  }
  const xs = series.map(p => new Date(p[0]).getTime());
  const ys = series.map(p => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1];
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.08 || y1 * 0.05 || 1;
  y0 -= pad; y1 += pad;
  const X = t => padL + (t - x0) / (x1 - x0 || 1) * (W - padL - padR);
  const Y = v => padT + (y1 - v) / (y1 - y0 || 1) * (H - padT - padB);

  const up = ys[ys.length - 1] >= ys[0];
  const col = up ? "#2ecc71" : "#ff5c5c";
  let d = "";
  series.forEach((p, i) => { d += (i ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(ys[i]).toFixed(1); });
  const area = d + `L${X(x1).toFixed(1)} ${H - padB}L${X(x0).toFixed(1)} ${H - padB}Z`;

  let grid = "", labels = "";
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, y = Y(v);
    grid += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#232b36" stroke-dasharray="3 4"/>`;
    labels += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" fill="#8b95a3" font-size="11">${Math.round(v).toLocaleString("de-DE")}</text>`;
  }
  const nTicks = Math.min(5, series.length);
  for (let i = 0; i < nTicks; i++) {
    const t = x0 + (x1 - x0) * i / (nTicks - 1 || 1);
    const dt = new Date(t);
    const lbl = dt.toLocaleDateString("de-DE", { month: "short", year: "2-digit" });
    labels += `<text x="${X(t)}" y="${H - 8}" text-anchor="middle" fill="#8b95a3" font-size="11">${lbl}</text>`;
  }
  const gid = "g" + Math.random().toString(36).slice(2, 8);
  const svg = el("div");
  svg.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${col}" stop-opacity=".28"/>
        <stop offset="1" stop-color="${col}" stop-opacity="0"/>
      </linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#${gid})"/>
      <path d="${d}" fill="none" stroke="${col}" stroke-width="2"/>
      <circle cx="${X(x1)}" cy="${Y(ys[ys.length - 1])}" r="3.5" fill="${col}"/>
      ${labels}
      <rect id="hit" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"/>
    </svg>`;
  container.append(svg.firstElementChild);

  const svgEl = container.querySelector("svg");
  const tip = $("#chart-tip");
  const toSvgX = clientX => {
    const r = svgEl.getBoundingClientRect();
    return (clientX - r.left) / r.width * W;
  };
  svgEl.addEventListener("pointermove", ev => {
    if (dragging) return;
    const r = svgEl.getBoundingClientRect();
    const t = x0 + ((ev.clientX - r.left) / r.width * W - padL) / (W - padL - padR) * (x1 - x0);
    let best = 0, bd = Infinity;
    xs.forEach((x, i) => { const dd = Math.abs(x - t); if (dd < bd) { bd = dd; best = i; } });
    tip.classList.remove("multi");
    tip.style.display = "block";
    tip.style.left = (r.left + (X(xs[best]) / W) * r.width + window.scrollX) + "px";
    tip.style.top = (r.top + (Y(ys[best]) / H) * r.height + window.scrollY) + "px";
    tip.textContent = `${fmtDate(series[best][0])} · ${fmtLvl(ys[best])}`;
  });
  svgEl.addEventListener("pointerleave", () => { if (!dragging) tip.style.display = "none"; });

  /* Ziehen zum Zoomen (Drill-down auf Zeitraum) */
  let dragging = false, startPx = 0;
  if (opts.onZoom) {
    const brush = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    brush.setAttribute("y", padT);
    brush.setAttribute("height", H - padT - padB);
    brush.setAttribute("fill", "#1f6feb");
    brush.setAttribute("fill-opacity", "0.18");
    brush.setAttribute("stroke", "#1f6feb");
    brush.setAttribute("stroke-width", "1");
    brush.style.display = "none";
    svgEl.appendChild(brush);
    const nearestDate = px => {
      const t = x0 + (px - padL) / (W - padL - padR) * (x1 - x0);
      let best = 0, bd = Infinity;
      xs.forEach((x, i) => { const dd = Math.abs(x - t); if (dd < bd) { bd = dd; best = i; } });
      return series[best][0];
    };
    svgEl.addEventListener("pointerdown", ev => {
      dragging = true; startPx = toSvgX(ev.clientX);
      brush.style.display = "block";
      brush.setAttribute("x", startPx); brush.setAttribute("width", 0);
      try { svgEl.setPointerCapture(ev.pointerId); } catch (e) {}
    });
    svgEl.addEventListener("pointermove", ev => {
      if (!dragging) return;
      const cur = toSvgX(ev.clientX);
      brush.setAttribute("x", Math.min(startPx, cur));
      brush.setAttribute("width", Math.abs(cur - startPx));
    });
    const endDrag = ev => {
      if (!dragging) return;
      dragging = false;
      brush.style.display = "none";
      const cur = toSvgX(ev.clientX);
      if (Math.abs(cur - startPx) < 8) return;
      const d1 = nearestDate(Math.min(startPx, cur));
      const d2 = nearestDate(Math.max(startPx, cur));
      if (d1 !== d2) opts.onZoom(d1, d2);
    };
    svgEl.addEventListener("pointerup", endDrag);
    svgEl.addEventListener("pointercancel", endDrag);
  }
  if (opts.onDblClick) svgEl.addEventListener("dblclick", opts.onDblClick);
}

/* ------------------------------------------------- Zoom/Drill-down-Leiste */
// Baut Range-Buttons + Ziehen-zum-Zoomen für einen einzelnen Chart (Index,
// EW-Index). Gibt { redraw } zurück, falls der Aufrufer neu zeichnen muss.
function mountLineChartWithControls(container, fullSeries, rangesObj, defaultKey) {
  const chartWrap = el("div", "chart-wrap");
  const bar = el("div", "ranges");
  container.append(chartWrap, bar);
  container.append(el("p", "note",
    "Im Chart klicken und ziehen, um in einen Zeitraum hineinzuzoomen. Doppelklick oder der Button 'Zoom zurücksetzen' springt zurück."));
  let active = defaultKey, customRange = null;
  const buildBar = () => {
    bar.innerHTML = "";
    Object.keys(rangesObj).forEach(k => {
      const b = el("button", (!customRange && k === active) ? "active" : null, k);
      b.addEventListener("click", () => { active = k; customRange = null; buildBar(); draw(); });
      bar.append(b);
    });
    if (customRange) {
      const rb = el("button", "active", "Zoom zurücksetzen ↺");
      rb.addEventListener("click", () => { customRange = null; buildBar(); draw(); });
      bar.append(rb);
    }
  };
  const doZoom = (d1, d2) => { customRange = [d1, d2]; buildBar(); draw(); };
  const doReset = () => { if (customRange) { customRange = null; buildBar(); draw(); } };
  const draw = () => {
    let s;
    if (customRange) {
      s = fullSeries.filter(p => p[0] >= customRange[0] && p[0] <= customRange[1]);
    } else {
      const days = rangesObj[active];
      const last = new Date(fullSeries[fullSeries.length - 1][0]).getTime();
      s = fullSeries.filter(p => (last - new Date(p[0]).getTime()) / 864e5 <= days);
    }
    renderChart(chartWrap, s, { onZoom: doZoom, onDblClick: doReset });
  };
  buildBar();
  draw();
  return { redraw: draw };
}

/* --------------------------------------------------------- Index-Ansicht */
const RANGES = { "1W": 7, "1M": 31, "6M": 186, "1J": 366, "MAX": 1e9 };

function renderIndexView(container, data, kind) {
  const isCards = kind === "cards";
  if (!data) {
    container.innerHTML = "";
    container.append(el("p", "note",
      "Noch keine Indexdaten vorhanden. Der erste Datenlauf (fetch_prices + build_indices) füllt diese Ansicht."));
    return;
  }
  const o = data.overview;
  container.innerHTML = "";

  const isCs2 = kind === "cs2";
  const hasEw = isCs2 && data.ew && data.ew.length > 1 && data.ew_overview;

  // Bei CS2 ist der gleichgewichtete Index (EW) die Hauptkennzahl: er misst
  // die tatsaechliche Marktrendite. "Top 500 nach Preis" erfasst dagegen nur
  // das bereits teure Blue-Chip-Segment (ein Item zaehlt erst mit, sobald es
  // ohnehin schon eines der 500 teuersten ist) und zeigt daher strukturell
  // eine viel niedrigere Rendite als der Gesamtmarkt.
  const head = hasEw
    ? { level: data.ew_overview.level, prev: data.ew_overview.prev,
        asof: data.ew_overview.asof, ticker: "CS2-EW" }
    : { level: o.level, prev: o.prev, asof: data.asof, ticker: data.name };
  const chg = head.prev ? (head.level / head.prev - 1) * 100 : null;
  const abs = head.prev ? head.level - head.prev : null;

  const kicker = el("div", "kicker",
    `Marktindex <span class="ticker">${head.ticker}</span>`);
  const h1 = el("h1", null, isCards ? "Pokémon-Karten-Index" :
    isCs2 ? "CS2-Skin-Index" : "Pokémon-Sealed-Index");
  const lr = el("div", "level-row");
  lr.append(el("span", "level", fmtLvl(head.level)));
  if (chg != null) {
    const cls = chg >= 0 ? "up" : "down";
    lr.append(el("span", `chg ${cls}`,
      `${chg >= 0 ? "▲" : "▼"} ${Math.abs(chg).toFixed(2).replace(".", ",")} % ` +
      `(${abs >= 0 ? "+" : "−"}${fmtLvl(Math.abs(abs))}) ${hasEw ? "" : "heute"}`));
  }
  const asof = el("div", "asof",
    `Stand ${fmtDate(head.asof)} · Datenabzug täglich ~20:00 UTC · <a href="#" data-goto="method">Wie diese Preise entstehen</a>`);
  container.append(kicker, h1, lr, asof);

  if (hasEw) {
    container.append(el("p", "note",
      "Gleichgewichteter Preisindex über alle erfassten CS2-Items (winsorisiert 1 %/99 %, " +
      "Seasoning-Filter ≥ 6 Monate) – bildet die tatsächliche Marktrendite ab. Historie: " +
      "Steam-Monatsdaten; tägliche Fortführung: Skinport (Quellenwechsel Juli 2026, per " +
      "Verkettung angeschlossen)."));
    mountLineChartWithControls(container, data.ew, RANGES, "MAX");

    container.append(el("h2", null, `Top 500 nach Preis (${data.name}) – Blue-Chip-Segment`));
    container.append(el("p", "note",
      "Enthält nur die 500 aktuell teuersten Items. Ein Item zählt erst mit, sobald es ohnehin " +
      "schon zu den teuersten gehört – das frühe Wachstum günstiger Items zu teuren wird dadurch " +
      "nicht erfasst. Deshalb liegt diese Kennzahl strukturell weit unter der Marktrendite oben " +
      "und ist eher ein Preisniveau-Indikator für das obere Marktsegment als eine Renditekennzahl."));
    mountLineChartWithControls(container, data.series, RANGES, "MAX");
  } else {
    mountLineChartWithControls(container, data.series, RANGES, "MAX");
  }

  container.append(el("h2", null, isCs2 ? `Überblick – Top 500 nach Preis (${data.name})` : "Überblick"));
  const tiles = el("div", "tiles");
  const tile = (k, v) => { const t = el("div", "tile"); t.append(el("span", "k", k), el("span", "v", v)); return t; };
  tiles.append(
    tile("Vortagesschluss", fmtLvl(o.prev)),
    tile("Allzeithoch", fmtLvl(o.ath)),
    tile("Allzeittief", fmtLvl(o.atl)),
    tile("Korbwert", fmtUsd0(o.basket)),
    tile("Gestiegen / Gefallen", `<span class="pct up">${o.adv ?? "–"}</span> / <span class="pct down">${o.dec ?? "–"}</span>`));
  container.append(tiles);

  container.append(el("h2", null, "Heutige Mover"));
  const mv = el("div", "movers");
  const col = (title, rows) => {
    const c = el("div", "mover-col");
    c.append(el("h3", null, title));
    if (!rows || !rows.length) c.append(el("p", "note", "Keine bestätigten Bewegungen."));
    (rows || []).forEach(r => {
      const m = el("div", "mover");
      m.innerHTML =
        `${isCs2 ? "" : `<img loading="lazy" src="${imgUrl(r.id)}" onerror="this.style.visibility='hidden'">`}
         <div class="m-name"><div class="n">${esc(r.n)}</div><div class="s">${esc(r.s)}</div></div>
         <div class="m-price">${fmtUsd(r.p)}<br>${pctHtml(r.chg)}</div>`;
      m.addEventListener("click", () => isCs2 ? openCs2Modal(r.n, r, data) : openTcgModal(r, data));
      c.append(m);
    });
    return c;
  };
  mv.append(col("Top-Gewinner", data.gainers), col("Top-Verlierer", data.losers));
  container.append(mv);
  container.append(el("p", "note",
    "Tagesbewegungen werden nur für Produkte mit bestätigtem TCGplayer-Preis an beiden Tagen gezeigt – Details in der Methodik."));

  const th = el("div", "table-head");
  th.append(el("h2", null, "Top 500"));
  const search = el("input");
  search.type = "search";
  search.placeholder = isCards ? "Karte oder Set suchen …" : "Produkt oder Set suchen …";
  th.append(search);
  container.append(th);

  const table = el("table");
  table.innerHTML = `<thead><tr><th>#</th><th>${isCards ? "Karte" : isCs2 ? "Item" : "Produkt"}</th>
    <th class="hide-m">Set</th><th class="num">Preis</th><th class="num">Änderung</th></tr></thead>`;
  const tbody = el("tbody");
  table.append(tbody);
  container.append(table);
  container.append(el("p", "note",
    "† Kein aktueller Verkaufspreis – letzter bekannter Preis wird bis zu 70 Tage fortgeschrieben."));

  let limit = 100;
  const renderRows = () => {
    const toks = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const rows = data.rows.filter(r => {
      if (!toks.length) return true;
      const hay = ((r.n || "") + " " + (r.s || "")).toLowerCase();
      return toks.every(t => hay.includes(t));
    });
    tbody.innerHTML = "";
    rows.slice(0, limit).forEach(r => {
      const tr = el("tr");
      tr.innerHTML =
        `<td class="muted">${r.r}</td>
         <td><span class="cardname">${esc(r.n)}</span>${r.num ? `<span class="cardnum">#${esc(r.num)}</span>` : ""}${r.new ? '<span class="badge new">NEU</span>' : ""}</td>
         <td class="set hide-m">${esc(r.s)}</td>
         <td class="num">${r.p >= 1000 ? fmtUsd0(Math.round(r.p)) : fmtUsd(r.p)}${r.car ? ' <span class="dagger" title="fortgeschrieben">†</span>' : ""}</td>
         <td class="num">${pctHtml(r.car ? null : r.chg, r.car)}</td>`;
      tr.addEventListener("click", () => isCs2 ? openCs2Modal(r.n, r, data) : openTcgModal(r, data));
      tbody.append(tr);
    });
    if (rows.length > limit) {
      const tr = el("tr", "more-row");
      tr.innerHTML = `<td colspan="5">Mehr anzeigen (${rows.length - limit} weitere) …</td>`;
      tr.addEventListener("click", () => { limit += 200; renderRows(); });
      tbody.append(tr);
    }
    $("#pccards-count");
  };
  search.addEventListener("input", () => { limit = 100; renderRows(); });
  renderRows();

  container.addEventListener("click", e => {
    const a = e.target.closest("[data-goto]");
    if (a) { e.preventDefault(); nav.querySelector(`[data-view="${a.dataset.goto}"]`).click(); }
  });
}

/* ------------------------------------------------------------------ Modal */
const modalBg = $("#modal-bg"), modal = $("#modal");
modalBg.addEventListener("click", e => { if (e.target === modalBg) closeModal(); });
function closeModal() { modalBg.classList.remove("open"); modal.innerHTML = ""; }
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

function openTcgModal(r, data) {
  const links = [];
  if (r.u) links.push(`<a href="${esc(r.u)}" target="_blank" rel="noopener">TCGplayer ↗</a>`);
  const q = encodeURIComponent(`${r.n} ${r.s} pokemon`);
  links.push(`<a href="https://www.pricecharting.com/search-products?type=prices&q=${q}" target="_blank" rel="noopener">PriceCharting ↗</a>`);
  links.push(`<a href="https://www.ebay.de/sch/i.html?_nkw=${q}&LH_Sold=1&LH_Complete=1" target="_blank" rel="noopener">eBay-Verkäufe ↗</a>`);
  modal.innerHTML =
    `<button class="close" onclick="this.closest('.modal-bg').classList.remove('open')">×</button>
     <img class="big" src="${imgUrl(r.id).replace("200x200", "400x400")}" onerror="this.remove()">
     <h3>${esc(r.n)}${r.num ? ` <span class="muted">#${esc(r.num)}</span>` : ""}</h3>
     <div class="sub">${esc(r.s)}</div>
     <div class="price">${fmtUsd(r.p)} <small>${r.car ? "† fortgeschrieben" : pctHtml(r.chg)}</small></div>
     <div class="stat-grid">
       <div><div class="k">Rang</div><div class="v">#${r.r} von 500</div></div>
       <div><div class="k">${r.cat ? "Kategorie" : "Wochenänderung"}</div>
            <div class="v">${r.cat ? esc(r.cat) : (r.wchg != null ? pctHtml(r.wchg) : "—")}</div></div>
       <div><div class="k">Stand</div><div class="v">${fmtDate(data.asof)}</div></div>
     </div>
     <div class="links">${links.join(" ")}</div>
     <p class="note">Preise unterscheiden sich zwischen Quellen – siehe Methodik.</p>`;
  modalBg.classList.add("open");
}

/* ----------------------------------------- PriceCharting-Bestandsansichten */
const PC_GRADE_META = {
  u:  { name: "Ungraded", col: "#6cb2ff" },
  g9: { name: "Grade 9", col: "#f1c40f" },
  p10:{ name: "PSA 10", col: "#2ecc71" },
  n:  { name: "Neu/OVP", col: "#f1c40f" },
  g:  { name: "Graded", col: "#2ecc71" },
  st: { name: "Steam-Monatsmedian", col: "#6cb2ff" },
};
const CAT_NAMES = { booster_box: "Booster-Box", etb: "ETB", bundle: "Bundle",
  pack_blister: "Pack/Blister", tin: "Tin", deck: "Deck",
  collection_box: "Collection/Box", sonstiges: "Sonstiges" };

const loadedShards = {};
function loadShard(prefix, shard, cb) {
  const key = prefix + "_" + shard;
  const store = prefix === "cards" ? "PC_CARD_SHARDS" : "PC_SEALED_SHARDS";
  if (window[store] && window[store][shard]) { cb(); return; }
  if (!loadedShards[key]) {
    loadedShards[key] = true;
    const s = document.createElement("script");
    s.src = `data/pc/${key}.js`;
    document.body.append(s);
  }
  const onEv = e => {
    if (e.detail[0] === prefix && e.detail[1] === shard) {
      document.removeEventListener("pcshard", onEv);
      cb();
    }
  };
  document.addEventListener("pcshard", onEv);
}

function pcChart(container, seriesByGrade) {
  const W = 420, H = 200, padL = 46, padR = 8, padT = 10, padB = 22;
  const grades = Object.keys(seriesByGrade).filter(g => seriesByGrade[g] && seriesByGrade[g].length > 1);
  if (!grades.length) { container.append(el("p", "note", "Zu wenig Historie für einen Chart.")); return; }
  const allX = [], allY = [];
  grades.forEach(g => seriesByGrade[g].forEach(p => {
    allX.push(new Date(p[0] + "-01").getTime()); allY.push(p[1] / 100);
  }));
  const x0 = Math.min(...allX), x1 = Math.max(...allX);
  let y0 = 0, y1 = Math.max(...allY) * 1.08 || 1;
  const X = t => padL + (t - x0) / (x1 - x0 || 1) * (W - padL - padR);
  const Y = v => padT + (y1 - v) / (y1 - y0 || 1) * (H - padT - padB);
  let paths = "", grid = "", labels = "";
  for (let i = 0; i <= 3; i++) {
    const v = y0 + (y1 - y0) * i / 3, y = Y(v);
    grid += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#232b36" stroke-dasharray="3 4"/>`;
    labels += `<text x="${padL - 6}" y="${y + 4}" text-anchor="end" fill="#8b95a3" font-size="10">${Math.round(v).toLocaleString("de-DE")}$</text>`;
  }
  for (let i = 0; i < 4; i++) {
    const t = x0 + (x1 - x0) * i / 3;
    labels += `<text x="${X(t)}" y="${H - 6}" text-anchor="middle" fill="#8b95a3" font-size="10">${new Date(t).toLocaleDateString("de-DE", { month: "short", year: "2-digit" })}</text>`;
  }
  const legend = el("div", "legend");
  grades.forEach(g => {
    const meta = PC_GRADE_META[g];
    let d = "";
    seriesByGrade[g].forEach((p, i) => {
      d += (i ? "L" : "M") + X(new Date(p[0] + "-01").getTime()).toFixed(1) + " " + Y(p[1] / 100).toFixed(1);
    });
    paths += `<path d="${d}" fill="none" stroke="${meta.col}" stroke-width="1.8"/>`;
    legend.innerHTML += `<span><span class="sw" style="background:${meta.col}"></span>${meta.name}</span>`;
  });
  const div = el("div");
  div.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${grid}${paths}${labels}</svg>`;
  container.append(div.firstElementChild, legend);
}

function openPcModal(entry, prefix, shards) {
  const [id, name, set, cents, url, cat] = entry;
  modal.innerHTML =
    `<button class="close" onclick="this.closest('.modal-bg').classList.remove('open')">×</button>
     <h3>${esc(name)}</h3>
     <div class="sub">${esc(set)}${cat ? " · " + (CAT_NAMES[cat] || cat) : ""}</div>
     <div class="price">${cents != null ? fmtUsd(cents / 100) : "—"} <small>letzter Monatswert (Ungraded)</small></div>
     <div id="pc-chart"><p class="note">Lade Historie …</p></div>
     <div class="links">
       ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">PriceCharting ↗</a>` : ""}
       <a href="https://www.ebay.de/sch/i.html?_nkw=${encodeURIComponent(name + " pokemon")}&LH_Sold=1&LH_Complete=1" target="_blank" rel="noopener">eBay-Verkäufe ↗</a>
     </div>
     <p class="note">Quelle: eigene PriceCharting-Scrapes, monatliche Punkte (USD).</p>`;
  modalBg.classList.add("open");
  const nShards = prefix === "cards" ? 64 : 8;
  loadShard(prefix, id % nShards, () => {
    const store = prefix === "cards" ? window.PC_CARD_SHARDS : window.PC_SEALED_SHARDS;
    const series = (store[id % nShards] || {})[id];
    const c = $("#pc-chart");
    c.innerHTML = "";
    if (series) pcChart(c, series);
    else c.append(el("p", "note", "Keine Historie gefunden."));
  });
}

function setupPcView(listVar, bodyId, searchId, countId, prefix, chipsId) {
  const list = window[listVar] || [];
  const body = $("#" + bodyId), search = $("#" + searchId), count = $("#" + countId);
  let catFilter = null, limit = 200;
  if (chipsId && list.length) {
    const cats = [...new Set(list.map(e => e[5]).filter(Boolean))];
    const chips = $("#" + chipsId);
    const all = el("button", "active", "Alle");
    all.addEventListener("click", () => { catFilter = null; setActive(all); limit = 200; render(); });
    chips.append(all);
    const setActive = btn => chips.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === btn));
    cats.sort().forEach(c => {
      const b = el("button", null, CAT_NAMES[c] || c);
      b.addEventListener("click", () => { catFilter = c; setActive(b); limit = 200; render(); });
      chips.append(b);
    });
  }
  const render = () => {
    const toks = (search.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    const rows = list.filter(e => {
      if (catFilter && e[5] !== catFilter) return false;
      if (!toks.length) return true;
      const hay = (e[1] + " " + (e[2] || "")).toLowerCase();
      return toks.every(t => hay.includes(t));
    });
    count.textContent = `${rows.length.toLocaleString("de-DE")} Einträge`;
    body.innerHTML = "";
    const frag = document.createDocumentFragment();
    rows.slice(0, limit).forEach((e, i) => {
      const tr = el("tr");
      tr.innerHTML =
        `<td class="muted">${i + 1}</td>
         <td><span class="cardname">${esc(e[1])}</span></td>
         <td class="set hide-m">${esc(e[2])}</td>
         <td class="num">${e[3] != null ? fmtUsd(e[3] / 100) : "—"}</td>`;
      tr.addEventListener("click", () => openPcModal(e, prefix));
      frag.append(tr);
    });
    if (rows.length > limit) {
      const tr = el("tr", "more-row");
      tr.innerHTML = `<td colspan="4">Mehr anzeigen (${(rows.length - limit).toLocaleString("de-DE")} weitere) …</td>`;
      tr.addEventListener("click", () => { limit += 500; render(); });
      frag.append(tr);
    }
    body.append(frag);
  };
  if (search) search.addEventListener("input", () => { limit = 200; render(); });
  if (list.length) render();
  else if (count) count.textContent = "Noch keine Daten exportiert (export_pricecharting.py ausführen).";
}

/* ------------------------------------------------------------------- CS2 */
const CS2_SHARDS = 32;
function djb2(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h;
}
const cs2Loaded = {};
function loadCs2Shard(shard, cb) {
  if (window.CS2_HIST && window.CS2_HIST[shard]) { cb(); return; }
  if (!cs2Loaded[shard]) {
    cs2Loaded[shard] = true;
    const s = document.createElement("script");
    s.src = `data/cs2/hist_${shard}.js`;
    document.body.append(s);
  }
  const onEv = e => {
    if (e.detail === shard) { document.removeEventListener("cs2shard", onEv); cb(); }
  };
  document.addEventListener("cs2shard", onEv);
}

function openCs2Modal(name, row, data) {
  const steamUrl = "https://steamcommunity.com/market/listings/730/" + encodeURIComponent(name);
  modal.innerHTML =
    `<button class="close" onclick="this.closest('.modal-bg').classList.remove('open')">×</button>
     <h3>${esc(name)}</h3>
     <div class="sub">CS2 · Steam-Historie (monatlich) + Skinport (täglich)</div>
     ${row ? `<div class="price">${fmtUsd(row.p)} <small>${row.car ? "† fortgeschrieben" : pctHtml(row.chg)} · Skinport heute</small></div>` : ""}
     ${row && row.r ? `<div class="stat-grid">
        <div><div class="k">Rang</div><div class="v">#${row.r} von 500</div></div>
        <div><div class="k">Wochenänderung</div><div class="v">${row.wchg != null ? pctHtml(row.wchg) : "—"}</div></div>
        <div><div class="k">Stand</div><div class="v">${data ? fmtDate(data.asof) : "—"}</div></div>
      </div>` : ""}
     <div id="cs2-chart"><p class="note">Lade Steam-Historie …</p></div>
     <div class="links">
       ${row && row.u ? `<a href="${esc(row.u)}" target="_blank" rel="noopener">Skinport ↗</a>` : ""}
       <a href="${steamUrl}" target="_blank" rel="noopener">Steam Market ↗</a>
     </div>`;
  modalBg.classList.add("open");
  loadCs2Shard(djb2(name) % CS2_SHARDS, () => {
    const series = (window.CS2_HIST[djb2(name) % CS2_SHARDS] || {})[name];
    const c = $("#cs2-chart");
    c.innerHTML = "";
    if (series && series.length > 1) pcChart(c, { st: series });
    else c.append(el("p", "note", "Keine Steam-Historie zu diesem Item (neu oder nie gescrapt)."));
  });
}

function setupCs2All() {
  const list = window.CS2_STEAM_LIST || [];
  const body = $("#cs2all-body"), search = $("#cs2all-search"), count = $("#cs2all-count");
  if (!list.length) {
    if (count) count.textContent = "Noch keine Steam-Historie exportiert.";
    return;
  }
  let limit = 200;
  const render = () => {
    const toks = (search.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    const rows = list.filter(e => !toks.length ||
      toks.every(t => e[0].toLowerCase().includes(t)));
    count.textContent = `${rows.length.toLocaleString("de-DE")} Items`;
    body.innerHTML = "";
    const frag = document.createDocumentFragment();
    rows.slice(0, limit).forEach((e, i) => {
      const tr = el("tr");
      tr.innerHTML =
        `<td class="muted">${i + 1}</td>
         <td><span class="cardname">${esc(e[0])}</span></td>
         <td class="num hide-m muted">${e[3]}</td>
         <td class="num">${fmtUsd(e[2] / 100)} <span class="muted">(${e[1]})</span></td>`;
      tr.addEventListener("click", () => openCs2Modal(e[0], null, null));
      frag.append(tr);
    });
    if (rows.length > limit) {
      const tr = el("tr", "more-row");
      tr.innerHTML = `<td colspan="4">Mehr anzeigen (${(rows.length - limit).toLocaleString("de-DE")} weitere) …</td>`;
      tr.addEventListener("click", () => { limit += 500; render(); });
      frag.append(tr);
    }
    body.append(frag);
  };
  search.addEventListener("input", () => { limit = 200; render(); });
  render();
}

/* ---------------------------------------------------------------- Märkte */
const MARKET_NAMES = {
  SP500: "S&P 500", DAX: "DAX", NASDAQ100: "NASDAQ 100",
  EUROSTOXX50: "EuroStoxx 50", MSCIWORLD: "MSCI World (URTH)",
  GOLD: "Gold", SILVER: "Silber", BITCOIN: "Bitcoin",
  SPK500: "Pokémon-Karten (SPK500)", SPKS: "Pokémon-Sealed (SPKS)",
  CS2500: "CS2-Skins (CS2500)",
};
const MARKET_COLORS = ["#6cb2ff", "#f1c40f", "#2ecc71", "#ff5c5c", "#b48cff",
  "#4dd0e1", "#ff9f43", "#e84393", "#4cc38a", "#a3cb38", "#fd79a8"];

function renderMultiChart(container, seriesMap, rangeDays, opts) {
  opts = opts || {};
  const W = 900, H = 360, padL = 46, padR = 12, padT = 12, padB = 28;
  container.innerHTML = "";
  const names = Object.keys(seriesMap);
  const norm = {};
  let x0 = Infinity, x1 = -Infinity;
  names.forEach(n => {
    let s = seriesMap[n];
    if (!s || s.length < 2) return;
    const last = new Date(s[s.length - 1][0]).getTime();
    s = s.filter(p => (last - new Date(p[0]).getTime()) / 864e5 <= rangeDays);
    if (s.length < 2) return;
    const base = s[0][1];
    norm[n] = s.map(p => [new Date(p[0]).getTime(), p[1] / base * 100]);
    x0 = Math.min(x0, norm[n][0][0]);
    x1 = Math.max(x1, norm[n][norm[n].length - 1][0]);
  });
  const keys = Object.keys(norm);
  if (!keys.length) {
    container.append(el("p", "note", "Keine Daten im gewählten Zeitraum."));
    return;
  }
  let y0 = Infinity, y1 = -Infinity;
  keys.forEach(n => norm[n].forEach(p => { y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); }));
  const pad = (y1 - y0) * 0.05 || 1;
  y0 -= pad; y1 += pad;
  const X = t => padL + (t - x0) / (x1 - x0 || 1) * (W - padL - padR);
  const Y = v => padT + (y1 - v) / (y1 - y0 || 1) * (H - padT - padB);
  let grid = "", labels = "", paths = "";
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, y = Y(v);
    grid += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#232b36" stroke-dasharray="3 4"/>`;
    labels += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" fill="#8b95a3" font-size="11">${Math.round(v)}</text>`;
  }
  for (let i = 0; i < 5; i++) {
    const t = x0 + (x1 - x0) * i / 4;
    labels += `<text x="${X(t)}" y="${H - 8}" text-anchor="middle" fill="#8b95a3" font-size="11">${new Date(t).toLocaleDateString("de-DE", { month: "short", year: "2-digit" })}</text>`;
  }
  const legend = el("div", "legend");
  keys.forEach((n, i) => {
    const col = MARKET_COLORS[i % MARKET_COLORS.length];
    let d = "";
    norm[n].forEach((p, j) => { d += (j ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1); });
    paths += `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.8"/>`;
    const endVal = norm[n][norm[n].length - 1][1];
    legend.innerHTML += `<span><span class="sw" style="background:${col}"></span>${esc(MARKET_NAMES[n] || n)} (${Math.round(endVal)})</span>`;
  });
  const div = el("div");
  div.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
      ${grid}${paths}${labels}
      <line id="cross" x1="0" y1="${padT}" x2="0" y2="${H - padB}" stroke="#8b95a3" stroke-dasharray="2 3" style="display:none"/>
      <rect id="hit" x="${padL}" y="${padT}" width="${W - padL - padR}" height="${H - padT - padB}" fill="transparent"/>
    </svg>`;
  container.append(div.firstElementChild, legend);

  const svgEl = container.querySelector("svg");
  const cross = svgEl.querySelector("#cross");
  const tip = $("#chart-tip");
  const toSvgX = clientX => {
    const r = svgEl.getBoundingClientRect();
    return (clientX - r.left) / r.width * W;
  };
  svgEl.addEventListener("pointermove", ev => {
    if (dragging) return;
    const r = svgEl.getBoundingClientRect();
    const relX = toSvgX(ev.clientX);
    const t = x0 + (relX - padL) / (W - padL - padR) * (x1 - x0);
    let rows = "";
    keys.forEach((n, i) => {
      const pts = norm[n];
      let best = 0, bd = Infinity;
      pts.forEach((p, j) => { const dd = Math.abs(p[0] - t); if (dd < bd) { bd = dd; best = j; } });
      const col = MARKET_COLORS[i % MARKET_COLORS.length];
      rows += `<div><span class="sw" style="background:${col}"></span>${esc(MARKET_NAMES[n] || n)}: ` +
        `<b>${Math.round(pts[best][1])}</b> (${new Date(pts[best][0]).toLocaleDateString("de-DE")})</div>`;
    });
    cross.style.display = "block";
    cross.setAttribute("x1", relX.toFixed(1));
    cross.setAttribute("x2", relX.toFixed(1));
    tip.classList.add("multi");
    tip.style.display = "block";
    tip.style.left = (ev.clientX + window.scrollX) + "px";
    tip.style.top = (r.top + window.scrollY + 10) + "px";
    tip.innerHTML = rows;
  });
  svgEl.addEventListener("pointerleave", () => {
    if (dragging) return;
    tip.style.display = "none";
    tip.classList.remove("multi");
    cross.style.display = "none";
  });

  /* Ziehen zum Zoomen */
  let dragging = false, startPx = 0;
  if (opts.onZoom) {
    const brush = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    brush.setAttribute("y", padT);
    brush.setAttribute("height", H - padT - padB);
    brush.setAttribute("fill", "#1f6feb");
    brush.setAttribute("fill-opacity", "0.18");
    brush.setAttribute("stroke", "#1f6feb");
    brush.setAttribute("stroke-width", "1");
    brush.style.display = "none";
    svgEl.appendChild(brush);
    const toDate = px => {
      const t = x0 + (px - padL) / (W - padL - padR) * (x1 - x0);
      return new Date(t).toISOString().slice(0, 10);
    };
    svgEl.addEventListener("pointerdown", ev => {
      dragging = true; startPx = toSvgX(ev.clientX);
      brush.style.display = "block";
      brush.setAttribute("x", startPx); brush.setAttribute("width", 0);
      try { svgEl.setPointerCapture(ev.pointerId); } catch (e) {}
    });
    svgEl.addEventListener("pointermove", ev => {
      if (!dragging) return;
      const cur = toSvgX(ev.clientX);
      brush.setAttribute("x", Math.min(startPx, cur));
      brush.setAttribute("width", Math.abs(cur - startPx));
    });
    const endDrag = ev => {
      if (!dragging) return;
      dragging = false;
      brush.style.display = "none";
      const cur = toSvgX(ev.clientX);
      if (Math.abs(cur - startPx) < 8) return;
      const d1 = toDate(Math.min(startPx, cur));
      const d2 = toDate(Math.max(startPx, cur));
      if (d1 !== d2) opts.onZoom(d1, d2);
    };
    svgEl.addEventListener("pointerup", endDrag);
    svgEl.addEventListener("pointercancel", endDrag);
  }
  if (opts.onDblClick) svgEl.addEventListener("dblclick", opts.onDblClick);
}

function setupMarkets() {
  const root = $("#markets-root");
  const mk = window.MARKETS;
  if (!root || !mk) {
    if (root) root.append(el("p", "note", "Noch keine Marktdaten vorhanden."));
    return;
  }
  const seriesAll = Object.assign({}, mk.series);
  if (window.IDX_CARDS) seriesAll.SPK500 = window.IDX_CARDS.series;
  if (window.IDX_SEALED) seriesAll.SPKS = window.IDX_SEALED.series;
  if (window.IDX_CS2 && window.IDX_CS2.ew) seriesAll.CS2500 = window.IDX_CS2.ew;

  const active = new Set(["SP500", "GOLD", "BITCOIN", "SPK500", "CS2500"]);
  const chips = el("div", "chips");
  Object.keys(seriesAll).forEach(n => {
    const b = el("button", active.has(n) ? "active" : null, MARKET_NAMES[n] || n);
    b.addEventListener("click", () => {
      if (active.has(n)) active.delete(n); else active.add(n);
      b.classList.toggle("active");
      draw();
    });
    chips.append(b);
  });
  root.append(chips);

  const chartWrap = el("div", "chart-wrap");
  const ranges = el("div", "ranges");
  root.append(chartWrap, ranges);
  root.append(el("p", "note",
    "Im Chart klicken und ziehen, um in einen Zeitraum hineinzuzoomen. Doppelklick oder der Button 'Zoom zurücksetzen' springt zurück."));
  const R = { "1M": 31, "6M": 186, "1J": 366, "5J": 1830, "MAX": 1e9 };
  let activeRange = "1J", customRange = null;
  const buildBar = () => {
    ranges.innerHTML = "";
    Object.keys(R).forEach(k => {
      const b = el("button", (!customRange && k === activeRange) ? "active" : null, k);
      b.addEventListener("click", () => { activeRange = k; customRange = null; buildBar(); draw(); });
      ranges.append(b);
    });
    if (customRange) {
      const rb = el("button", "active", "Zoom zurücksetzen ↺");
      rb.addEventListener("click", () => { customRange = null; buildBar(); draw(); });
      ranges.append(rb);
    }
  };
  const doZoom = (d1, d2) => { customRange = [d1, d2]; buildBar(); draw(); };
  const doReset = () => { if (customRange) { customRange = null; buildBar(); draw(); } };
  const draw = () => {
    const sel = {};
    active.forEach(n => { if (seriesAll[n]) sel[n] = seriesAll[n]; });
    if (customRange) {
      const trimmed = {};
      Object.entries(sel).forEach(([k, v]) => {
        trimmed[k] = v.filter(p => p[0] >= customRange[0] && p[0] <= customRange[1]);
      });
      renderMultiChart(chartWrap, trimmed, 1e9, { onZoom: doZoom, onDblClick: doReset });
    } else {
      renderMultiChart(chartWrap, sel, R[activeRange], { onZoom: doZoom, onDblClick: doReset });
    }
  };
  buildBar();
  draw();

  root.append(el("h2", null, "Tagesüberblick"));
  const tiles = el("div", "tiles");
  Object.entries(mk.changes).forEach(([n, c]) => {
    const t = el("div", "tile");
    t.append(el("span", "k", MARKET_NAMES[n] || n),
      el("span", "v", `${c.level.toLocaleString("de-DE")} ${pctHtml(c.d1)}`));
    tiles.append(t);
  });
  root.append(tiles);
  root.append(el("p", "note", "Änderung = letzter vs. vorletzter Schlusskurs der jeweiligen Quelle."));
}

/* ------------------------------------------------------------- Newsletter */
function setupNews() {
  const c = $("#news-list");
  const raw = window.NEWSLETTERS || [];
  // Altformat (Liste von Datumsstrings) weiterhin unterstuetzen
  const list = raw.map(item => typeof item === "string" ? { d: item, t: "weekly" } : item);
  if (!list.length) {
    c.append(el("p", "note", "Noch keine Ausgaben – der erste Tagesbericht wird automatisch erstellt."));
    return;
  }
  const LABEL = { daily: "Tagesbericht", weekly: "Wochenbriefing" };
  const ul = el("ul");
  list.forEach(({ d, t }) => ul.append(el("li", null,
    `<a href="newsletter/${d}-${t}.html">${LABEL[t] || t} vom ${fmtDate(d)}</a>`)));
  c.append(ul);
}

/* ------------------------------------------------------------------ Risiko */
function setupRisk() {
  const root = $("#risk-root");
  const R = window.RISK;
  if (!root) return;
  if (!R) {
    root.append(el("p", "note", "Noch keine Risikodaten – build_risk.py ausführen."));
    return;
  }
  const L = R.labels || {};
  const order = ["SPK500", "SPKS", "CS2500", "CS2_EW", "SP500", "NASDAQ100",
                 "DAX", "EUROSTOXX50", "MSCIWORLD", "GOLD", "SILVER", "BITCOIN"];
  const names = order.filter(n => R.kennzahlen && R.kennzahlen[n]);

  // Kennzahlentabelle (Gesamtzeitraum)
  const t = el("table");
  t.innerHTML = `<thead><tr><th>Reihe</th><th class="num">Rendite ges.</th>
    <th class="num">p. a. (CAGR)</th><th class="num">Vola p. a.</th>
    <th class="num">Max. Rückgang</th><th class="num">Sharpe</th>
    <th class="num">Sortino</th><th class="num">Positive Tage</th>
    <th class="num">Zeitraum</th></tr></thead>`;
  const tb = el("tbody");
  names.forEach(n => {
    const m = (R.kennzahlen[n].fenster || {})["Gesamt"] || {};
    const tr = el("tr");
    tr.innerHTML = `<td>${esc(L[n] || n)}</td>
      <td class="num">${m.rendite_gesamt_pct != null ? m.rendite_gesamt_pct.toFixed(1) + " %" : "—"}</td>
      <td class="num">${m.cagr_pct != null ? m.cagr_pct.toFixed(1) + " %" : "—"}</td>
      <td class="num">${m.vola_pa_pct != null ? m.vola_pa_pct.toFixed(1) + " %" : "—"}</td>
      <td class="num">${m.max_drawdown_pct != null ? m.max_drawdown_pct.toFixed(1) + " %" : "—"}</td>
      <td class="num">${m.sharpe != null ? m.sharpe.toFixed(2) : "—"}</td>
      <td class="num">${m.sortino != null ? m.sortino.toFixed(2) : "—"}</td>
      <td class="num">${m.positive_tage_pct != null ? m.positive_tage_pct.toFixed(0) + " %" : "—"}</td>
      <td class="num">${m.von ? fmtDate(m.von) + "–" + fmtDate(m.bis) : "—"}</td>`;
    tb.append(tr);
  });
  t.append(tb);
  root.append(el("h2", null, "Kennzahlen (Gesamtzeitraum)"));
  root.append(t);

  // Einzelprodukt-Volatilität als Realitätsabgleich
  if (R.einzelprodukt_vola) {
    const rows = Object.entries(R.einzelprodukt_vola)
      .filter(([, d]) => d && d.median_pa_pct != null);
    if (rows.length) {
      const t2 = el("table");
      t2.innerHTML = `<thead><tr><th>Universum</th><th class="num">Median</th>
        <th class="num">25 %</th><th class="num">75 %</th><th class="num">90 %</th>
        <th class="num">Produkte</th></tr></thead>`;
      const b2 = el("tbody");
      rows.forEach(([n, d]) => {
        const tr = el("tr");
        tr.innerHTML = `<td>${esc(L[n] || n)}</td>
          <td class="num">${d.median_pa_pct.toFixed(1)} %</td>
          <td class="num">${d.p25_pa_pct.toFixed(1)} %</td>
          <td class="num">${d.p75_pa_pct.toFixed(1)} %</td>
          <td class="num">${d.p90_pa_pct.toFixed(1)} %</td>
          <td class="num">${d.n.toLocaleString("de-DE")}</td>`;
        b2.append(tr);
      });
      t2.append(b2);
      root.append(el("h2", null, "Einzelprodukt-Volatilität (letzte 12 Monate)"));
      root.append(el("p", "note", "Verteilung der annualisierten Volatilität je "
        + "Produkt. Diese Werte – nicht die Index-Volatilität – beschreiben das "
        + "Risiko eines einzelnen Kaufs."));
      root.append(t2);
    }
  }

  // Korrelationsmatrix
  if (R.korrelation && R.korrelation.names) {
    const K = R.korrelation;
    const t3 = el("table");
    t3.innerHTML = "<thead><tr><th>Korrelation</th>"
      + K.names.map(n => `<th class="num">${esc(L[n] || n)}</th>`).join("")
      + "</tr></thead>";
    const b3 = el("tbody");
    K.names.forEach((a, i) => {
      const tr = el("tr");
      let html = `<td>${esc(L[a] || a)}</td>`;
      K.matrix[i].forEach(v => {
        const col = v == null ? "" :
          (v > 0.5 ? "color:#ff8080" : v < -0.2 ? "color:#4cc38a" : "");
        html += `<td class="num" style="${col}">${v == null ? "—" : v.toFixed(2)}</td>`;
      });
      tr.innerHTML = html;
      b3.append(tr);
    });
    t3.append(b3);
    root.append(el("h2", null, "Korrelation der Tagesrenditen"));
    root.append(el("p", "note", "Werte nahe 0 bedeuten: die Klasse bewegt sich "
      + "unabhängig von den klassischen Märkten (Diversifikationsnutzen). "
      + "Grün = gegenläufig, rot = stark mitlaufend."));
    root.append(t3);
  }

  // Normierter Vergleich
  if (R.vergleich && R.vergleich.series) {
    const map = {};
    Object.entries(R.vergleich.series).forEach(([k, s]) => {
      map[L[k] || k] = s;
    });
    const box = el("div");
    root.append(el("h2", null, "Wertentwicklung im Vergleich (Basis 100)"));
    root.append(box);
    renderMultiChart(box, map, 1e9, { normalize: false });
  }

  const m = R.methodik || {};
  root.append(el("p", "note", esc(m.warnung_glaettung || "")));
  root.append(el("p", "note", esc(m.hinweis_preisart || "")));
}

/* -------------------------------------------------------------- Screening */
function setupScreen() {
  const root = $("#screen-root");
  const S = window.SCREEN;
  if (!root) return;
  if (!S) {
    root.append(el("p", "note", "Noch keine Screening-Daten – build_screening.py ausführen."));
    return;
  }
  const SIG = { "Günstig & stabil": "up", "Stabile Basis": "", "Nahe Tief": "",
                "Solide": "", "Neutral": "" };
  ["sealed", "karten"].forEach(key => {
    const block = S[key];
    if (!block || !block.top || !block.top.length) return;
    root.append(el("h2", null, key === "sealed" ? "Sealed-Produkte" : "Einzelkarten"));
    root.append(el("p", "note",
      `${block.n_bewertet.toLocaleString("de-DE")} Reihen bewertet, Stand ${fmtDate(S.as_of)}.`));
    const t = el("table");
    t.innerHTML = `<thead><tr><th class="num">#</th><th>Produkt</th><th>Set</th>
      <th class="num">Preis</th><th class="num">Score</th><th class="num">Günstig</th>
      <th class="num">Stabil</th><th class="num">Vola p. a.</th>
      <th class="num">Trend p. a.</th><th class="num">Abschlag ATH</th>
      <th>Signal</th><th>Risiken</th></tr></thead>`;
    const tb = el("tbody");
    block.top.filter(r => r.investierbar).slice(0, 60).forEach((r, i) => {
      const tr = el("tr");
      tr.innerHTML = `<td class="num">${i + 1}</td>
        <td>${esc(r.name)}</td><td>${esc(r.set || "")}</td>
        <td class="num">${fmtUsd(r.preis_usd)}</td>
        <td class="num"><b>${r.score.toFixed(1)}</b></td>
        <td class="num">${r.guenstigkeit.toFixed(0)}</td>
        <td class="num">${r.stabilitaet.toFixed(0)}</td>
        <td class="num">${r.vola_pa_pct != null ? r.vola_pa_pct.toFixed(0) + " %" : "—"}</td>
        <td class="num">${r.trend_pa_pct != null ? r.trend_pa_pct.toFixed(0) + " %" : "—"}</td>
        <td class="num">${r.abschlag_ath_pct != null ? r.abschlag_ath_pct.toFixed(0) + " %" : "—"}</td>
        <td class="${SIG[r.signal] ? "pct up" : ""}">${esc(r.signal)}</td>
        <td style="color:var(--muted);font-size:11.5px">${esc((r.risiken || []).join(", "))}</td>`;
      tb.append(tr);
    });
    t.append(tb);
    root.append(t);
  });

  // Backtest-Ergebnisse: die entscheidende Einordnung
  if (S.backtest) {
    root.append(el("h2", null, "Validierung: hat das Signal funktioniert?"));
    Object.entries(S.backtest).forEach(([uni, bt]) => {
      const fz = bt.fazit_90d || {};
      root.append(el("h3", null, uni === "sealed" ? "Sealed" : "Karten"));
      const t = el("table");
      t.innerHTML = `<thead><tr><th>Signal</th><th>Beschreibung</th>
        <th class="num">IC</th><th class="num">t</th>
        <th class="num">Überschuss netto</th><th class="num">monoton</th>
        <th class="num">Stichtage</th></tr></thead>`;
      const tb = el("tbody");
      (fz.rangliste || []).forEach(r => {
        const tr = el("tr");
        const cls = (r.ueberschuss_pp || 0) > 0 ? "pct up" : "pct down";
        tr.innerHTML = `<td><b>${esc(r.signal)}</b></td>
          <td style="color:var(--muted)">${esc(r.beschreibung || "")}</td>
          <td class="num">${r.ic != null ? r.ic.toFixed(3) : "—"}</td>
          <td class="num">${r.t != null ? r.t.toFixed(1) : "—"}</td>
          <td class="num ${cls}">${r.ueberschuss_pp != null ? r.ueberschuss_pp.toFixed(1) + " pp" : "—"}</td>
          <td class="num">${r.monoton ? "ja" : "nein"}</td>
          <td class="num">${r.stichtage ?? "—"}</td>`;
        tb.append(tr);
      });
      t.append(tb);
      root.append(t);
      root.append(el("p", "note", "<b>Fazit (90 Tage):</b> " + esc(fz.fazit || "")));
      const st = bt.strategie && bt.strategie.ergebnis;
      if (st) {
        root.append(el("p", "note",
          `Strategie „Top ${bt.strategie.parameter.top_n}, `
          + `${bt.strategie.parameter.haltedauer_tage} Tage halten“ netto nach `
          + `${bt.strategie.parameter.round_trip_gebuehr_pct} % Gebühren: `
          + `<b>${st.strategie_netto_pct.toFixed(1)} %</b> gegen `
          + `${st.markt_pct.toFixed(1)} % gleichgewichteten Markt `
          + `(${st.ueberschuss_pp.toFixed(1)} pp).`));
      }
      ((bt.event_study || {}).hinweise || []).forEach(h =>
        root.append(el("p", "note", esc(h))));
    });
  }
  const m = S.methodik || {};
  root.append(el("p", "note", esc(m.guenstigkeit ? "Günstigkeit: " + m.guenstigkeit : "")));
  root.append(el("p", "note", esc(m.stabilitaet ? "Stabilität: " + m.stabilitaet : "")));
  root.append(el("p", "note", esc(m.hinweis || "")));
}

/* ------------------------------------------------------------------ Start */
renderIndexView($('[data-idx="cards"]'), window.IDX_CARDS, "cards");
renderIndexView($('[data-idx="sealed"]'), window.IDX_SEALED, "sealed");
renderIndexView($('[data-idx="cs2"]'), window.IDX_CS2, "cs2");
setupPcView("PC_CARDS", "pccards-body", "pccards-search", "pccards-count", "cards");
setupPcView("PC_SEALED", "pcsealed-body", "pcsealed-search", "pcsealed-count", "sealed", "pcsealed-chips");
setupCs2All();
setupMarkets();
setupRisk();
setupScreen();
setupNews();
