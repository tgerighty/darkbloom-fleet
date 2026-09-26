PONYTAIL MODE ACTIVE — level: full

# Circular Dependency Assessment

## Executive Summary

- Total issues found: **0**. The local import graphs are acyclic. The complete production dependency table and repeatable checks below support this result (`fleet/main.py:12`, `fleet/web.py:19`, `fleet/static/dashboard.js:1`).
- Severity breakdown: **HIGH=0, MEDIUM=0, LOW=0**. Domain classifications: **BREAKING=0, STRUCTURAL=0, COSMETIC=0**. This is a static import assessment, not a claim that the application has no runtime faults (`fleet/main.py:19`, `fleet/static/dashboard.js:126`).
- Top three remediation priorities: **none**. Keep the existing shared modules and callback parameter; no new interface, module, dependency, or import relocation is needed (`fleet/types.py:4`, `fleet/attribution.py:46`, `fleet/static/host.js:291`).
- Estimated remediation impact: **0 source LOC; 0 source files**. No circular dependency warrants a change in the dependency table below (`fleet/collector.py:13`, `fleet/queries.py:12`, `fleet/static/host.js:1`).

## Scope, Pre-flight, and Method

Assessment date: 2026-09-26. Worktree tip checked: `a3d3e98`. Scope: local circular dependencies only.

| Ecosystem | Source evidence |
| --- | --- |
| Python service, FastAPI, Uvicorn, and psycopg | `requirements.txt:1`, `requirements.txt:2`, `requirements.txt:3`, `Dockerfile:22` |
| Native JavaScript ES modules in the dashboard | `package.json:3`, `fleet/static/dashboard.html:151` |
| Python tests and Vitest tests | `pyproject.toml:1`, `package.json:4`, `vitest.config.js:3` |

Tool pre-flight: `python3`, `node`, and `rg` were available. `madge`, `lint-imports`, `pydeps`, `grimp`, and `importlab` were not on PATH. The checked local executable paths also had no Madge, import-linter, or pydeps executable. No package was installed. The dependency manifests declare application dependencies and Vitest, but no cycle analyzer (`requirements.txt:1`, `requirements.txt:2`, `requirements.txt:3`, `package.json:4`).

Read-only checks used Python `ast` and `graphlib.TopologicalSorter`, Node `vm.SourceTextModule`, and `rg`. No application module was imported or evaluated. The checks included nested Python imports, relative imports, JavaScript re-exports, and the literal dynamic dashboard import (`tests/test_inventory.py:12`, `fleet/collector.py:13`, `fleet/static/host.js:2`, `tests/dashboard-harness.js:147`).

Measured results from the checks:

| Graph | Files or URLs | Distinct local edges | Result and source evidence |
| --- | ---: | ---: | --- |
| Production Python | 19 files | 34 explicit; 52 with package-initialization edges | Acyclic; all production edges are listed below (`fleet/__init__.py:1`, `fleet/main.py:12`, `fleet/web.py:19`). |
| All Python, including tests and check scripts | 42 files | 76 explicit; 116 with package-initialization edges | Acyclic; includes the test-to-test edge and test entry points (`tests/test_inventory.py:12`, `tests/test_web_main.py:10`, `tests/check_reward_accounting.py:6`). |
| All JavaScript, including tests and Vitest configuration | 12 files | 12 | Acyclic; includes static and literal dynamic imports (`tests/dashboard-poll.test.js:3`, `tests/dashboard-harness.js:147`, `vitest.config.js:1`). |
| Browser entry graph with query strings retained | 5 module URLs | 4 | Acyclic; the two `ui.js` URLs remain distinct (`fleet/static/dashboard.html:151`, `fleet/static/dashboard.js:5`, `fleet/static/host.js:1`). |

All local import targets resolved. Standard-library and third-party modules were outside the local graph. The Python count includes package initializers; the JavaScript file count includes `vitest.config.js`. Import and re-export of the same target count as one edge (`fleet/__init__.py:1`, `vitest.config.js:1`, `fleet/static/host.js:1`, `fleet/static/host.js:2`).

### Complete production dependency table

Targets in the Python rows are under `fleet/`. “None” means no local module dependency, not no external dependency. The checks traversed the full files; citations locate their import sections.

| Importing module | Direct local targets | Import evidence |
| --- | --- | --- |
| `main.py` | `db`, `config`, `web` | `fleet/main.py:12`, `fleet/main.py:13`, `fleet/main.py:14` |
| `web.py` | `earnings_shadow`, `hourly`, `queries`, `watch`, `config`, `scheduler` | `fleet/web.py:19`, `fleet/web.py:20`, `fleet/web.py:21` |
| `scheduler.py` | `collector`, `config` | `fleet/scheduler.py:14`, `fleet/scheduler.py:15` |
| `collector.py` | `db`, `demand`, `remote`, `scoring`, `config`, `types` | `fleet/collector.py:13`, `fleet/collector.py:14`, `fleet/collector.py:15` |
| `queries.py` | `attribution`, `card`, `config`, `health`, `hourly`, `routability` | `fleet/queries.py:12`, `fleet/queries.py:13`, `fleet/queries.py:14`, `fleet/queries.py:15`, `fleet/queries.py:16`, `fleet/queries.py:17` |
| `card.py` | `attribution`, `types` | `fleet/card.py:11`, `fleet/card.py:12` |
| `hourly.py` | `attribution` | `fleet/hourly.py:9` |
| `demand.py` | `scoring`, `types` | `fleet/demand.py:11`, `fleet/demand.py:12` |
| `scoring.py` | `types` | `fleet/scoring.py:13` |
| `db.py` | `types` | `fleet/db.py:14` |
| `remote.py` | `config`, `types` | `fleet/remote.py:9`, `fleet/remote.py:10` |
| `watch.py` | `remote` | `fleet/watch.py:16` |
| `earnings_shadow.py` | `remote` | `fleet/earnings_shadow.py:10` |
| `__init__.py` | None; docstring only | `fleet/__init__.py:1` |
| `attribution.py` | None | `fleet/attribution.py:10`, `fleet/attribution.py:12` |
| `config.py` | None | `fleet/config.py:6`, `fleet/config.py:8`, `fleet/config.py:13` |
| `health.py` | None | `fleet/health.py:6`, `fleet/health.py:8` |
| `routability.py` | None | `fleet/routability.py:7`, `fleet/routability.py:9` |
| `types.py` | None | `fleet/types.py:2`, `fleet/types.py:4` |
| `static/dashboard.js` | `hourly.js?v=4`, `host.js?v=10`, `ui.js?v=8` | `fleet/static/dashboard.js:1`, `fleet/static/dashboard.js:2`, `fleet/static/dashboard.js:5` |
| `static/host.js` | `ui.js?v=5`, also re-exported | `fleet/static/host.js:1`, `fleet/static/host.js:2` |
| `static/hourly.js` | None | `fleet/static/hourly.js:1`, `fleet/static/hourly.js:73` |
| `static/ui.js` | None | `fleet/static/ui.js:1`, `fleet/static/ui.js:8`, `fleet/static/ui.js:139` |

### Chains and cases checked

These are dependency paths, not cycles. Each left-hand citation identifies an import of the next module:

- Ingestion: `fleet/main.py:14` → `fleet/web.py:21` → `fleet/scheduler.py:14` → `fleet/collector.py:13` → `fleet/demand.py:11` → `fleet/scoring.py:13` → `fleet/types.py:4` (standard-library dependency only).
- Status rendering: `fleet/web.py:19` → `fleet/queries.py:13` → `fleet/card.py:11` → `fleet/attribution.py:12` (external dependency only). The query layer passes the data to `build_card`; the card module does not import the query layer (`fleet/queries.py:396`, `fleet/card.py:116`).
- Browser rendering: `fleet/static/dashboard.js:2` → `fleet/static/host.js:1` → `fleet/static/ui.js:8` (no imports). The `esc` re-export has no return edge. It is not a cosmetic barrel cycle (`fleet/static/host.js:2`).
- Callback composition: the dashboard imports `hourlySection` and passes it to `renderHosts`; the host renderer calls that parameter. Neither renderer imports the dashboard (`fleet/static/dashboard.js:1`, `fleet/static/dashboard.js:70`, `fleet/static/host.js:291`, `fleet/static/host.js:294`).
- Tests: `_cfg` imports another test module inside a function. That target imports production modules, with no return path to the inventory test (`tests/test_inventory.py:12`, `tests/test_collector_tick.py:8`, `tests/test_collector_tick.py:9`). The JavaScript harness dynamically imports the dashboard, with no production import of the harness (`tests/dashboard-harness.js:147`, `fleet/static/dashboard.js:1`).
- Embedded remote Python: the payout, watch, and publishing snippets import only standard-library modules. Static parsing checked these snippets separately. The payout test's `exec` uses that same fixed snippet (`fleet/remote.py:37`, `fleet/remote.py:38`, `fleet/watch.py:27`, `fleet/earnings_shadow.py:74`, `tests/test_remote.py:230`).

## Critical Findings

None. No BREAKING circular import was found in the checked graphs. Application startup and browser startup were inspected as source, not run (`fleet/main.py:17`, `fleet/static/dashboard.js:126`).

## Medium Findings

None. No STRUCTURAL cycle was found. The ingestion and presentation paths share lower-level modules without reverse imports (`fleet/collector.py:15`, `fleet/card.py:12`, `fleet/types.py:4`, `fleet/queries.py:12`, `fleet/hourly.py:9`, `fleet/attribution.py:12`).

## Low / Debatable Findings

None. The existing re-export and test helper reuse do not close a cycle. Neither warrants an import cleanup for this domain (`fleet/static/host.js:2`, `fleet/static/ui.js:8`, `tests/test_inventory.py:12`, `tests/test_collector_tick.py:8`).

## Recommendations

1. **KEEP the current dependency structure.** No cycle needs a weakest-link removal, dependency inversion, module merge, or shared-module extraction. Proposed blast radius: 0 files; no behavior change (`fleet/collector.py:13`, `fleet/queries.py:12`, `fleet/static/host.js:1`).
2. **Reuse the existing shared modules and callback parameter.** They already support the paths that could otherwise cause mutual imports (`fleet/types.py:4`, `fleet/attribution.py:46`, `fleet/static/dashboard.js:70`, `fleet/static/host.js:291`).
3. **Repeat the static check when these imports change.** No new dependency or permanent CI rule is proposed for this zero-finding assessment (`fleet/web.py:19`, `fleet/queries.py:12`, `fleet/static/dashboard.js:1`).

## Out of Scope / Flagged for Review

- Runtime startup and integration behavior were not tested. Startup initializes the database, and the web lifespan starts background tasks; running them is unnecessary for this static import assessment (`fleet/main.py:19`, `fleet/main.py:21`, `fleet/web.py:46`, `fleet/web.py:47`, `fleet/web.py:48`).
- Third-party package internals and dependencies outside this worktree were not read. The local application imports those packages at the stated boundaries (`requirements.txt:1`, `requirements.txt:2`, `requirements.txt:3`, `fleet/web.py:14`, `fleet/config.py:13`).
- Remote provider/manager data flow is outside the local import graph. The code reads remote state and publishes an earnings profile; this assessment does not classify external process feedback as a Python import cycle (`fleet/remote.py:22`, `fleet/earnings_shadow.py:71`, `fleet/earnings_shadow.py:85`).
- Browser query-version consistency is a separate topic. The two `ui.js` URLs were retained in the browser graph; neither has a return dependency (`fleet/static/dashboard.js:5`, `fleet/static/host.js:1`, `fleet/static/ui.js:8`).

## Repeatable Read-only Check

Run from the worktree root. This check reads source text and parses modules. It does not import application code, run tests, or write files. The dynamic-import check covers the literal form found in the harness; other dynamic forms require manual review (`tests/dashboard-harness.js:147`).

```bash
python3 -B - <<'PY'
import ast
import json
import subprocess
from graphlib import TopologicalSorter
from pathlib import Path

files = sorted([*Path('fleet').rglob('*.py'), *Path('tests').rglob('*.py')])
modules = {}
for p in files:
    assert not p.is_symlink(), p
    parts = p.with_suffix('').parts
    modules['.'.join(parts[:-1] if p.name == '__init__.py' else parts)] = p
graph = {name: set() for name in modules}
for name, p in modules.items():
    package = name if p.name == '__init__.py' else name.rpartition('.')[0]
    for node in ast.walk(ast.parse(p.read_text(), filename=str(p))):
        targets = []
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                prefix = package.split('.')[:len(package.split('.')) - node.level + 1]
                base = '.'.join(filter(None, ['.'.join(prefix), base]))
            targets = [base + '.' + a.name if base + '.' + a.name in modules else base
                       for a in node.names]
        for target in targets:
            if target in modules:
                graph[name].add(target)
            else:
                assert target.split('.')[0] not in ('fleet', 'tests'), (p, target)
print('Python files / explicit edges:', len(graph), sum(map(len, graph.values())))
for name in graph:
    parent = name.rpartition('.')[0]
    if parent in graph:
        graph[name].add(parent)
assert len(tuple(TopologicalSorter(graph).static_order())) == len(graph)
print('Python: acyclic, including package initialization')

js = r'''
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const files = ['vitest.config.js', ...['fleet/static', 'tests'].flatMap(dir =>
  fs.readdirSync(dir).filter(f => f.endsWith('.js')).map(f => dir + '/' + f))];
const graph = Object.fromEntries(files.map(f => [f, []]));
for (const file of files) {
  if (fs.lstatSync(file).isSymbolicLink()) throw Error('Symlink: ' + file);
  const src = fs.readFileSync(file, 'utf8');
  const mod = new vm.SourceTextModule(src);
  const dynamic = [...src.matchAll(/\bimport\s*\(\s*(['"])([^'"]+)\1\s*\)/g)];
  if (dynamic.length !== [...src.matchAll(/\bimport\s*\(/g)].length)
    throw Error('Review dynamic imports: ' + file);
  for (const spec of [...mod.dependencySpecifiers, ...dynamic.map(m => m[2])]) {
    if (!spec.startsWith('.')) continue;
    const url = new URL(spec, pathToFileURL(path.resolve(file)));
    const target = path.relative(process.cwd(), fileURLToPath(url));
    if (!(target in graph)) throw Error('Unresolved local import: ' + file);
    graph[file].push(target);
  }
  graph[file] = [...new Set(graph[file])];
}
process.stdout.write(JSON.stringify(graph));
'''
result = subprocess.run(['node', '--experimental-vm-modules', '--input-type=module'],
                        input=js, text=True, capture_output=True, check=True)
graph = json.loads(result.stdout)
assert len(tuple(TopologicalSorter(graph).static_order())) == len(graph)
print('JavaScript files / edges:', len(graph), sum(map(len, graph.values())))
print('JavaScript: acyclic, including literal dynamic imports and re-exports')
PY
```

The repeatable JavaScript check merges URL variants into file nodes. The separate browser check retained query strings and also passed; its complete edges are cited in the production table (`fleet/static/dashboard.js:1`, `fleet/static/dashboard.js:2`, `fleet/static/dashboard.js:5`, `fleet/static/host.js:1`).

## Machine-Readable Findings

No actionable finding is emitted. Analysis findings must have `verified: false`; there are no finding objects to mark in this assessment.

```json
{"findings": []}
```
