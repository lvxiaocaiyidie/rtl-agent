from __future__ import annotations

import json

from .contracts import ContractGraph


def render_contract_dashboard(graph: ContractGraph) -> str:
    data = json.dumps(graph.to_dict()).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>rtl-agent contract graph</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --panel: #fff;
      --ink: #17202a;
      --muted: #64717f;
      --line: #d8dee6;
      --accent: #0b6bcb;
      --warn: #b7791f;
      --bad: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Inter, Segoe UI, Arial, sans-serif; }}
    header {{ background: var(--panel); border-bottom: 1px solid var(--line); padding: 18px 22px; position: sticky; top: 0; z-index: 2; }}
    h1 {{ font-size: 20px; margin: 0 0 4px; }}
    main {{ max-width: 1500px; margin: 0 auto; padding: 18px 22px 36px; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; }}
    .card, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    .card {{ padding: 12px; min-height: 74px; }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
    .tabs {{ display: flex; gap: 8px; margin: 18px 0 12px; flex-wrap: wrap; }}
    button, input, select {{ border: 1px solid var(--line); background: var(--panel); border-radius: 6px; padding: 8px 10px; font: inherit; }}
    button.active {{ color: #fff; background: var(--accent); border-color: var(--accent); }}
    input {{ min-width: 280px; }}
    .view {{ display: none; }}
    .view.active {{ display: block; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }}
    .panel {{ padding: 14px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; padding: 8px; font-size: 13px; }}
    code {{ background: #eef2f6; padding: 1px 4px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f1720; color: #e6edf3; padding: 12px; border-radius: 8px; }}
    .issue {{ border-left: 4px solid var(--warn); padding: 10px 12px; background: #fff; border-radius: 6px; border-top: 1px solid var(--line); border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-bottom: 8px; }}
    .issue.P1, .issue.P2 {{ border-left-color: var(--bad); }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
  <header>
    <h1>rtl-agent contract graph</h1>
    <div class="sub" id="subtitle"></div>
  </header>
  <main>
    <section id="metrics" class="grid"></section>
    <nav class="tabs">
      <button class="active" data-view="issues">Issues</button>
      <button data-view="edges">Edges</button>
      <button data-view="nodes">Nodes</button>
      <button data-view="handoff">Agent Handoff</button>
    </nav>
    <section id="issues" class="view active"></section>
    <section id="edges" class="view"></section>
    <section id="nodes" class="view"></section>
    <section id="handoff" class="view"></section>
  </main>
  <script id="contract-data" type="application/json">{data}</script>
  <script>
    const graph = JSON.parse(document.getElementById('contract-data').textContent);
    const $ = id => document.getElementById(id);
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    document.querySelectorAll('.tabs button').forEach(btn => btn.onclick = () => {{
      document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      btn.classList.add('active');
      $(btn.dataset.view).classList.add('active');
    }});
    function metric(label, value) {{ return `<div class="card"><div class="label">${{esc(label)}}</div><div class="value">${{esc(value)}}</div></div>`; }}
    function initMetrics() {{
      $('subtitle').textContent = `Tops: ${{(graph.summary.top_modules || []).join(', ') || 'none'}}`;
      $('metrics').innerHTML = [
        metric('Nodes', graph.nodes.length),
        metric('Edges', graph.edges.length),
        metric('Issues', graph.issues.length),
        metric('Tables', (graph.summary.tables || []).length),
        metric('RTL Matches', graph.edges.filter(e => e.kind === 'matches_rtl_signal' || e.kind === 'matches_rtl_object').length)
      ].join('');
    }}
    function initIssues() {{
      $('issues').innerHTML = graph.issues.length
        ? graph.issues.map(i => `<div class="issue ${{esc(i.severity)}}"><b>${{esc(i.severity)}} ${{esc(i.kind)}}</b><div>${{esc(i.message)}}</div><div class="meta">${{esc(i.source)}}</div></div>`).join('')
        : '<div class="panel">No contract issues detected.</div>';
    }}
    function initEdges() {{
      const kinds = [...new Set(graph.edges.map(e => e.kind))].sort();
      $('edges').innerHTML = `<div class="toolbar"><input id="edgeSearch" placeholder="Search edge, source, target"><select id="edgeKind"><option value="">All edge kinds</option>${{kinds.map(k=>`<option>${{esc(k)}}</option>`).join('')}}</select></div><div class="panel"><table><thead><tr><th>Source</th><th>Target</th><th>Kind</th><th>Evidence</th></tr></thead><tbody id="edgeRows"></tbody></table></div>`;
      const render = () => {{
        const q = $('edgeSearch').value.toLowerCase();
        const kind = $('edgeKind').value;
        const rows = graph.edges.filter(e => (!kind || e.kind === kind) && JSON.stringify(e).toLowerCase().includes(q));
        $('edgeRows').innerHTML = rows.map(e => `<tr><td><code>${{esc(e.source)}}</code></td><td><code>${{esc(e.target)}}</code></td><td>${{esc(e.kind)}}</td><td>${{esc(e.evidence)}}</td></tr>`).join('');
      }};
      setTimeout(() => {{ $('edgeSearch').oninput = render; $('edgeKind').oninput = render; render(); }});
    }}
    function initNodes() {{
      $('nodes').innerHTML = `<div class="toolbar"><input id="nodeSearch" placeholder="Search node, kind, attrs"></div><div class="panel"><table><thead><tr><th>ID</th><th>Kind</th><th>Name</th><th>Source</th></tr></thead><tbody id="nodeRows"></tbody></table></div>`;
      const render = () => {{
        const q = $('nodeSearch').value.toLowerCase();
        const rows = graph.nodes.filter(n => JSON.stringify(n).toLowerCase().includes(q));
        $('nodeRows').innerHTML = rows.map(n => `<tr><td><code>${{esc(n.id)}}</code></td><td>${{esc(n.kind)}}</td><td>${{esc(n.name)}}</td><td>${{esc(n.source)}}</td></tr>`).join('');
      }};
      setTimeout(() => {{ $('nodeSearch').oninput = render; render(); }});
    }}
    function initHandoff() {{
      $('handoff').innerHTML = `<div class="panel"><pre>${{esc(JSON.stringify(graph.agent_handoff, null, 2))}}</pre></div>`;
    }}
    initMetrics(); initIssues(); initEdges(); initNodes(); initHandoff();
  </script>
</body>
</html>"""
