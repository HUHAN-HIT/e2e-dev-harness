import json
from collections import defaultdict
from pathlib import Path

g = json.loads(Path('graphify-out/graph.json').read_text(encoding='utf-8'))
labels_raw = json.loads(Path('graphify-out/.graphify_labels.json').read_text(encoding='utf-8'))
communities = {int(k): v for k, v in labels_raw.items()}

enrich = {}
for i in '123':
    p = Path(f'graphify-out/.enrich_out_{i}.json')
    if p.exists():
        for x in json.loads(p.read_text(encoding='utf-8')):
            if x.get('id'):
                enrich[x['id']] = x

raw_nodes = g.get('nodes', [])
ids = [n['id'] for n in raw_nodes]
idx_to_id = {i: nid for i, nid in enumerate(ids)}


def norm(v):
    # link endpoints may be id (str), index (int), or dict
    if isinstance(v, dict):
        return v.get('id')
    if isinstance(v, int):
        return idx_to_id.get(v, v)
    return v


raw_links = g.get('links', g.get('edges', []))
adj = defaultdict(set)
links = []
for e in raw_links:
    s = norm(e.get('source'))
    t = norm(e.get('target'))
    if s is None or t is None:
        continue
    adj[s].add(t)
    adj[t].add(s)
    links.append({'source': s, 'target': t,
                  'relation': e.get('relation', ''),
                  'confidence': e.get('confidence', '')})

# community assignment per node: graph.json may store it on the node, else derive
node_comm = {}
for n in raw_nodes:
    if 'community' in n:
        node_comm[n['id']] = n['community']
# fallback from analysis if missing
if len(node_comm) < len(raw_nodes):
    try:
        analysis = json.loads(Path('graphify-out/.graphify_analysis.json').read_text(encoding='utf-8'))
        for k, members in analysis['communities'].items():
            for m in members:
                node_comm.setdefault(m, int(k))
    except Exception:
        pass

nodes = []
for n in raw_nodes:
    nid = n['id']
    en = enrich.get(nid, {})
    nodes.append({
        'id': nid,
        'label': n.get('label', nid),
        'type': n.get('file_type', ''),
        'community': int(node_comm.get(nid, 0)),
        'what': en.get('what', ''),
        'why': en.get('why', ''),
        'how': en.get('how', ''),
        'source': n.get('source_file', ''),
        'deg': len(adj[nid]),
    })

data = {'nodes': nodes, 'links': links,
        'communities': {str(k): v for k, v in communities.items()}}

tpl = Path('graphify-out/_template.html').read_text(encoding='utf-8')
html = tpl.replace('__DATA__', json.dumps(data, ensure_ascii=False))
Path('graphify-out/knowledge-graph.html').write_text(html, encoding='utf-8')

enriched_n = sum(1 for n in nodes if n['what'])
print(f'wrote knowledge-graph.html: {len(nodes)} nodes ({enriched_n} with explanations), '
      f'{len(links)} links, {len(communities)} communities, {len(html)} bytes')
