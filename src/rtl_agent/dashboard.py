from __future__ import annotations

import json
from html import escape

from .checks.base import Finding
from .checks.registry import rule_metadata
from .modeler import build_rtl_model
from .models import DesignIndex


def render_dashboard(index: DesignIndex, findings: list[Finding], model_level: str = "l3") -> str:
    payload = {
        "index": index.to_dict(),
        "findings": [finding.to_dict() for finding in findings],
        "rules": rule_metadata(),
        "model": build_rtl_model(index, level=model_level, max_modules=160),
    }
    data = json.dumps(payload)
    title = f"rtl-agent dashboard - {', '.join(index.top_modules) or 'no top'}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #64717f;
      --line: #d8dee6;
      --accent: #0b6bcb;
      --warn: #b7791f;
      --bad: #b42318;
      --ok: #087443;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: var(--bg); color: var(--ink); }}
    header {{ padding: 18px 22px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; }}
    h1 {{ font-size: 20px; margin: 0 0 4px; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    main {{ padding: 18px 22px 36px; max-width: 1500px; margin: 0 auto; }}
    .grid {{ display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 10px; }}
    .card, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    .card {{ padding: 12px; min-height: 74px; }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
    .tabs {{ display: flex; gap: 8px; margin: 18px 0 12px; flex-wrap: wrap; }}
    button, select, input {{ border: 1px solid var(--line); background: var(--panel); border-radius: 6px; padding: 8px 10px; font: inherit; }}
    button.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
    .toolbar {{ display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
    input {{ min-width: 260px; }}
    .view {{ display: none; }}
    .view.active {{ display: block; }}
    .two {{ display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 12px; }}
    .panel {{ padding: 14px; overflow: auto; }}
    .list {{ display: grid; gap: 8px; }}
    .finding {{ border-left: 4px solid var(--line); padding: 10px 12px; background: #fff; border-radius: 6px; border-top: 1px solid var(--line); border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .finding.compile_overlap {{ border-left-color: var(--warn); }}
    .finding.architecture_insight {{ border-left-color: var(--accent); }}
    .sev-P1 {{ color: var(--bad); font-weight: 700; }}
    .sev-P2 {{ color: var(--warn); font-weight: 700; }}
    .sev-P3, .sev-INFO {{ color: var(--muted); font-weight: 700; }}
    .meta {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .tree ul {{ list-style: none; padding-left: 18px; border-left: 1px solid var(--line); }}
    .tree li {{ margin: 5px 0; }}
    code {{ background: #eef2f6; padding: 1px 4px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f1720; color: #e6edf3; padding: 12px; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; font-size: 13px; vertical-align: top; }}
    .pill {{ display: inline-block; padding: 2px 7px; border-radius: 999px; background: #edf2f7; color: #384452; font-size: 12px; margin: 2px 4px 2px 0; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>rtl-agent dashboard</h1>
    <div class="sub" id="subtitle"></div>
  </header>
  <main>
    <section class="grid" id="metrics"></section>
    <nav class="tabs">
      <button class="active" data-view="findings">Findings</button>
      <button data-view="hierarchy">Hierarchy</button>
      <button data-view="modules">Modules</button>
      <button data-view="model">Model</button>
      <button data-view="rules">Rules</button>
    </nav>
    <section id="findings" class="view active"></section>
    <section id="hierarchy" class="view"></section>
    <section id="modules" class="view"></section>
    <section id="model" class="view"></section>
    <section id="rules" class="view"></section>
  </main>
  <script id="rtl-data" type="application/json">{data}</script>
  <script>
    const data = JSON.parse(document.getElementById('rtl-data').textContent);
    const modules = data.index.modules;
    const rules = data.rules;
    const findings = data.findings.map(f => ({{...f, rule: rules[f.rule_id] || {{value: 'unknown'}}}}));
    const $ = id => document.getElementById(id);
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    document.querySelectorAll('.tabs button').forEach(btn => btn.onclick = () => {{
      document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      btn.classList.add('active'); $(btn.dataset.view).classList.add('active');
    }});
    function metric(label, value) {{ return `<div class="card"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`; }}
    function initMetrics() {{
      const d = data.index;
      $('subtitle').textContent = `Root: ${{d.root}} | Tops: ${{d.top_modules.join(', ') || 'none'}}`;
      $('metrics').innerHTML = [
        metric('Files', d.files.length), metric('Modules', Object.keys(modules).length),
        metric('Instances', Object.values(modules).reduce((n,m)=>n+m.instances.length,0)),
        metric('Reachable', d.reachable_modules.length), metric('Orphans', d.orphan_modules.length),
        metric('Findings', findings.length)
      ].join('');
    }}
    function initFindings() {{
      $('findings').innerHTML = `
        <div class="toolbar">
          <input id="findingSearch" placeholder="Search finding, module, source">
          <select id="findingValue"><option value="">All value types</option><option value="architecture_insight">Architecture insight</option><option value="compile_overlap">Compile overlap</option></select>
          <select id="findingRule"><option value="">All rules</option>${{Object.keys(rules).map(r=>`<option>${{r}}</option>`).join('')}}</select>
        </div>
        <div class="list" id="findingList"></div>`;
      const render = () => {{
        const q = $('findingSearch').value.toLowerCase();
        const value = $('findingValue').value;
        const rule = $('findingRule').value;
        const rows = findings.filter(f => (!value || f.rule.value === value) && (!rule || f.rule_id === rule) && JSON.stringify(f).toLowerCase().includes(q));
        $('findingList').innerHTML = rows.map(f => `<div class="finding ${{esc(f.rule.value)}}">
          <div><span class="sev-${{esc(f.severity)}}">${{esc(f.severity)}}</span> <b>${{esc(f.rule_id)}}: ${{esc(f.title)}}</b></div>
          <div>${{esc(f.message)}}</div>
          <div class="meta">${{esc(f.rule.value)}} | ${{esc(f.source)}} | ${{(f.evidence||[]).map(e=>`<code>${{esc(e)}}</code>`).join(' ')}}</div>
        </div>`).join('') || '<div class="panel">No findings match.</div>';
      }};
      ['findingSearch','findingValue','findingRule'].forEach(id => setTimeout(() => $(id).oninput = render));
      setTimeout(render);
    }}
    function treeNode(name, depth=0, seen=new Set()) {{
      const m = modules[name];
      if (!m) return `<li>${{esc(name)}} <span class="meta">external</span></li>`;
      if (seen.has(name)) return `<li>${{esc(name)}} <span class="meta">recursive</span></li>`;
      const next = new Set(seen); next.add(name);
      const children = depth < 3 ? m.instances.map(i => `<li>${{esc(i.name)}}: <b>${{esc(i.module)}}</b>${{treeNode(i.module, depth+1, next).replace(/^<li>|<\\/li>$/g,'')}}</li>`).join('') : '';
      return `<li><b>${{esc(name)}}</b> <span class="meta">${{esc(m.source.file)}}:${{m.source.start_line}}</span>${{children ? `<ul>${{children}}</ul>` : ''}}</li>`;
    }}
    function initHierarchy() {{
      $('hierarchy').innerHTML = `<div class="panel tree"><ul>${{data.index.top_modules.map(t => treeNode(t)).join('')}}</ul></div>`;
    }}
    function initModules() {{
      $('modules').innerHTML = `<div class="toolbar"><input id="moduleSearch" placeholder="Search module, role, subsystem"></div><div class="panel"><table><thead><tr><th>Name</th><th>Role</th><th>Subsystem</th><th>Ports</th><th>Instances</th><th>Source</th></tr></thead><tbody id="moduleRows"></tbody></table></div>`;
      const render = () => {{
        const q = $('moduleSearch').value.toLowerCase();
        const rows = Object.values(modules).filter(m => JSON.stringify([m.name,m.role,m.subsystem,m.source.file]).toLowerCase().includes(q));
        $('moduleRows').innerHTML = rows.map(m => `<tr><td><b>${{esc(m.name)}}</b></td><td>${{esc(m.role)}}</td><td>${{esc(m.subsystem)}}</td><td>${{m.ports.length}}</td><td>${{m.instances.length}}</td><td><code>${{esc(m.source.file)}}:${{m.source.start_line}}-${{m.source.end_line}}</code></td></tr>`).join('');
      }};
      setTimeout(() => {{ $('moduleSearch').oninput = render; render(); }});
    }}
    function initModel() {{
      const arch = data.model.architecture || {{}};
      $('model').innerHTML = `<div class="two">
        <div class="panel"><h3>Architecture Hints</h3>
          <p><b>CPU-like</b><br>${{(arch.cpu_like||[]).map(x=>`<span class="pill">${{esc(x)}}</span>`).join('') || 'none'}}</p>
          <p><b>Bus-like</b><br>${{(arch.bus_like||[]).slice(0,40).map(x=>`<span class="pill">${{esc(x)}}</span>`).join('') || 'none'}}</p>
          <p><b>Memory-like</b><br>${{(arch.memory_like||[]).slice(0,40).map(x=>`<span class="pill">${{esc(x)}}</span>`).join('') || 'none'}}</p>
          <p><b>Peripheral-like</b><br>${{(arch.peripheral_like||[]).slice(0,40).map(x=>`<span class="pill">${{esc(x)}}</span>`).join('') || 'none'}}</p>
        </div>
        <div class="panel"><h3>Model JSON</h3><pre>${{esc(JSON.stringify(data.model, null, 2).slice(0, 30000))}}</pre></div>
      </div>`;
    }}
    function initRules() {{
      $('rules').innerHTML = `<div class="panel"><table><thead><tr><th>Rule</th><th>Value</th><th>Category</th><th>Description</th></tr></thead><tbody>${{Object.entries(rules).map(([id,r])=>`<tr><td><b>${{esc(id)}}</b><br>${{esc(r.title)}}</td><td>${{esc(r.value)}}</td><td>${{esc(r.category)}}</td><td>${{esc(r.description)}}</td></tr>`).join('')}}</tbody></table></div>`;
    }}
    initMetrics(); initFindings(); initHierarchy(); initModules(); initModel(); initRules();
  </script>
</body>
</html>"""
