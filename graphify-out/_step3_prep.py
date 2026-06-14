import json
from pathlib import Path
from graphify.extract import collect_files, extract
from graphify.cache import check_semantic_cache

detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))

# Part A: AST (docs corpus has no code files -> empty AST)
code_files = []
for f in detect.get('files', {}).get('code', []):
    code_files.extend(collect_files(Path(f)) if Path(f).is_dir() else [Path(f)])
if code_files:
    result = extract(code_files)
else:
    result = {'nodes': [], 'edges': [], 'input_tokens': 0, 'output_tokens': 0}
Path('graphify-out/.graphify_ast.json').write_text(
    json.dumps(result, ensure_ascii=False), encoding='utf-8')

# Part B0: semantic cache check -> uncached list drives subagent chunks
all_files = [f for files in detect['files'].values() for f in files]
cached_nodes, cached_edges, cached_hyper, uncached = check_semantic_cache(all_files)
if cached_nodes or cached_edges or cached_hyper:
    Path('graphify-out/.graphify_cached.json').write_text(
        json.dumps({'nodes': cached_nodes, 'edges': cached_edges,
                    'hyperedges': cached_hyper}, ensure_ascii=False), encoding='utf-8')
Path('graphify-out/.graphify_uncached.txt').write_text(
    '\n'.join(str(u) for u in uncached), encoding='utf-8')
Path('graphify-out/.step3prep_done').write_text(
    f'ast_code={len(code_files)} all={len(all_files)} uncached={len(uncached)}',
    encoding='utf-8')
