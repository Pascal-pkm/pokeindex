# -*- coding: utf-8 -*-
"""HTML-Bericht des Portfolios (lokal, ersetzt die handgepflegte Portfolio-Seite).

Die alte "Pokemon Sealed Portfolio.html" trug das Label "Cardmarket Live",
enthielt aber fest einkodierte Preise – sie veraltete ab dem Moment ihrer
Erzeugung. Diese Seite wird bei jedem Lauf neu erzeugt, nennt ihren
Datenstand, die Preisquelle je Position und den Proxy-Anteil.

Selbstenthaltendes HTML, ein CDN-Chart (Chart.js), keine Tracker.
"""
from __future__ import annotations

import html
import json

from pokedata.atomicio import write_text

CSS = """
:root{--bg:#0f1420;--panel:#161d2e;--panel2:#1c2538;--line:#27314a;--txt:#e8edf7;
--muted:#93a0bd;--accent:#ffcb05;--green:#28c76f;--red:#ef5a72;--proxy:#f0a020}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(180deg,#0d1220,#0f1420 240px);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.45}
.wrap{max-width:1280px;margin:0 auto;padding:26px 22px 60px}
h1{margin:0;font-size:26px;letter-spacing:-.3px}
h1 .pk{color:var(--accent)}
h2{font-size:17px;margin:30px 0 12px}
.sub{color:var(--muted);margin-top:6px;font-size:13px}
.note{background:rgba(240,160,32,.10);border:1px solid rgba(240,160,32,.35);
border-radius:12px;padding:12px 15px;margin:18px 0 22px;color:#f6e2c4;font-size:12.5px}
.note b{color:#fff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi .l{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:22px;font-weight:700;margin-top:6px}
.kpi .m{color:var(--muted);font-size:11.5px;margin-top:4px}
.pos{color:var(--green)}.neg{color:var(--red)}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{background:var(--panel2);text-align:left;padding:9px 10px;font-size:11.5px;
text-transform:uppercase;letter-spacing:.05em;color:var(--muted);white-space:nowrap}
td{padding:9px 10px;border-top:1px solid var(--line);font-size:13px}
td.r,th.r{text-align:right}
.tag{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:20px;
border:1px solid var(--proxy);color:var(--proxy)}
.tag.ok{border-color:var(--green);color:var(--green)}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:14px;margin:14px 0;height:340px}
footer{color:var(--muted);font-size:11.5px;margin-top:34px;line-height:1.7}
"""


def _fmt(v, suffix=" €", dash="–"):
    if v is None:
        return dash
    return f"{v:,.2f}".replace(",", " ") + suffix


def _pct(v):
    if v is None:
        return '<span style="color:#93a0bd">–</span>'
    cls = "pos" if v >= 0 else "neg"
    return f'<span class="{cls}">{v:+.2f} %</span>'


def write_html(path: str, result: dict) -> None:
    s = result["summary"]
    pos = result["positionen"]
    bench = result.get("benchmark") or {}

    kpis = [
        ("Einstand", _fmt(s["kosten_eur"]), f"{s['stueckzahl']} Stück, "
         f"{s['positionen']} Positionen"),
        ("Marktwert (brutto)", _fmt(s["marktwert_eur"]),
         f"Proxy-Anteil {s['proxy_anteil_pct']} %"),
        ("P&amp;L brutto", _fmt(s["pl_eur"]), f"{s['pl_pct']:+.2f} %"
         if s["pl_pct"] is not None else "–"),
        ("Marktwert netto", _fmt(s["marktwert_netto_eur"]),
         "nach Verkaufsgebühren"),
        ("P&amp;L netto", _fmt(s["pl_netto_eur"]),
         f"{s['pl_netto_pct']:+.2f} %" if s["pl_netto_pct"] is not None else "–"),
        ("Zeitgew. Rendite", f"{s['twr_pct']:+.2f} %"
         if s.get("twr_pct") is not None else "–", "TWR, zuflussneutral"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="l">{k}</div>'
        f'<div class="v">{v}</div><div class="m">{m}</div></div>'
        for k, v, m in kpis)

    rows = []
    for p in pos:
        proxy = ('<span class="tag">Proxy EN</span>' if p["is_proxy"]
                 else ('<span class="tag ok">Cardmarket</span>'
                       if p["is_proxy"] == 0 else '<span class="tag">offen</span>'))
        rows.append(
            "<tr>"
            f'<td>{html.escape(p["artikel"])}<br>'
            f'<span style="color:#93a0bd;font-size:11.5px">'
            f'{html.escape(p.get("product_name") or "keine Zuordnung")}</span></td>'
            f'<td class="r">{p["menge"]}</td>'
            f'<td class="r">{_fmt(p["kosten_stueck_eur"])}</td>'
            f'<td class="r">{_fmt(p["preis_stueck_eur"])}</td>'
            f'<td class="r">{_fmt(p["kosten_eur"])}</td>'
            f'<td class="r">{_fmt(p["wert_eur"])}</td>'
            f'<td class="r">{_fmt(p["pl_eur"])}</td>'
            f'<td class="r">{_pct(p["pl_pct"])}</td>'
            f'<td class="r">{_pct(p["pl_netto_pct"])}</td>'
            f'<td class="r">{_fmt(p["breakeven_stueck_eur"])}</td>'
            f"<td>{proxy}</td></tr>")

    series = result.get("serie") or []
    chart_labels = [d for d, _w, _k in series]
    chart_value = [w for _d, w, _k in series]
    chart_cost = [k for _d, _w, k in series]

    bench_js = "null"
    if bench.get("series"):
        bench_js = json.dumps({
            "labels": sorted({d for s2 in bench["series"].values() for d, _v in s2}),
            "series": {k: dict(v) for k, v in bench["series"].items()},
        }, ensure_ascii=False)

    offen = ""
    if result.get("nicht_bewertet"):
        items = "".join(
            f'<tr><td>{html.escape(u["artikel"])}</td>'
            f'<td>{html.escape(u["grund"])}</td>'
            f'<td class="r">{_fmt(u["kosten_eur"])}</td></tr>'
            for u in result["nicht_bewertet"])
        offen = (f"<h2>Ohne Bewertung ({len(result['nicht_bewertet'])})</h2>"
                 f'<p class="sub">Zuordnung in <code>portfolio_map.csv</code> '
                 f"ergänzen oder Preis in <code>portfolio_prices_manual.csv</code> "
                 f"eintragen.</p><table><tr><th>Artikel</th><th>Grund</th>"
                 f'<th class="r">Einstand</th></tr>{items}</table>')

    hinweise = "".join(f"<li>{html.escape(h)}</li>" for h in result.get("hinweise", []))

    doc = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>Pokémon Sealed Portfolio – Stand {s['stand']}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>Poké<span class="pk">Portfolio</span></h1>
<div class="sub">Bewertungsstand {s['stand']} · erzeugt {result['built']} ·
Methodik {result['method_version']}</div></header>

<div class="note"><b>Wie die Werte zustande kommen:</b> Einstandskosten sind exakt
(inkl. Versand). Marktwerte sind zu {s['proxy_anteil_pct']} % Näherungswerte aus
englischen TCGplayer-Marktpreisen (USD→EUR, EZB-Tageskurs); der Bestand ist
deutschsprachig und wird real auf Cardmarket gehandelt. Für belastbare Werte echte
Cardmarket-Preise in <code>portfolio_prices_manual.csv</code> eintragen – diese haben
Vorrang. Netto-Werte sind nach Verkaufsgebühren.</div>

<div class="kpis">{kpi_html}</div>

<h2>Wertentwicklung</h2>
<div class="chart"><canvas id="c1"></canvas></div>

<h2>Vergleich mit Benchmarks (Basis 100)</h2>
<div class="chart"><canvas id="c2"></canvas></div>

<h2>Positionen ({len(pos)})</h2>
<table><tr><th>Artikel</th><th class="r">Menge</th><th class="r">Einstand/Stk</th>
<th class="r">Markt/Stk</th><th class="r">Einstand</th><th class="r">Marktwert</th>
<th class="r">P&amp;L</th><th class="r">P&amp;L %</th><th class="r">netto %</th>
<th class="r">Break-even/Stk</th><th>Quelle</th></tr>
{''.join(rows)}</table>

{offen}

<h2>Nebenkosten</h2>
<p class="sub">Schutzhüllen und Zubehör: {_fmt(result.get('nebenkosten_eur'))} –
nicht in den Positionskosten enthalten.</p>

<footer><b>Hinweise</b><ul>{hinweise}</ul>
Historische Wertentwicklung ist keine Prognose. Screening- und
Bewertungswerkzeug, keine Anlageberatung.</footer>
</div>
<script>
const S={{labels:{json.dumps(chart_labels)},value:{json.dumps(chart_value)},
cost:{json.dumps(chart_cost)}}};
const B={bench_js};
const grid={{color:'#27314a'}},tick={{color:'#93a0bd'}};
new Chart(document.getElementById('c1'),{{type:'line',
data:{{labels:S.labels,datasets:[
{{label:'Marktwert (€)',data:S.value,borderColor:'#ffcb05',backgroundColor:'rgba(255,203,5,.12)',
fill:true,tension:.25,pointRadius:0,borderWidth:2}},
{{label:'Einstand (€)',data:S.cost,borderColor:'#93a0bd',borderDash:[5,4],
fill:false,tension:0,pointRadius:0,borderWidth:1.5}}]}},
options:{{maintainAspectRatio:false,plugins:{{legend:{{labels:{{color:'#e8edf7'}}}}}},
scales:{{x:{{grid,ticks:tick}},y:{{grid,ticks:tick}}}}}}}});
if(B){{
const colors=['#ffcb05','#3b6fe0','#28c76f','#ef5a72','#00cfe8','#c084fc'];
const ds=Object.keys(B.series).map((k,i)=>({{label:k,
data:B.labels.map(d=>B.series[k][d]??null),borderColor:colors[i%colors.length],
fill:false,tension:.2,pointRadius:0,borderWidth:k==='Portfolio'?2.5:1.4,spanGaps:true}}));
new Chart(document.getElementById('c2'),{{type:'line',
data:{{labels:B.labels,datasets:ds}},
options:{{maintainAspectRatio:false,plugins:{{legend:{{labels:{{color:'#e8edf7'}}}}}},
scales:{{x:{{grid,ticks:tick}},y:{{grid,ticks:tick}}}}}}}});
}}
</script></body></html>"""
    write_text(path, doc)
