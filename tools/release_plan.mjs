// Plans a release from Conventional Commits since the last v* tag.
//   node tools/release_plan.mjs            -> JSON {release, version, tag, notes}
//   node tools/release_plan.mjs --apply    -> also writes the version into the project files (CI working tree only)
// feat -> minor, fix/perf -> patch, "!" or BREAKING CHANGE -> major; chore/docs/ci/test/style/refactor/build alone -> no release.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';

const git = (...args) => execFileSync('git', args, { encoding: 'utf8' }).trim();
const root = new URL('../', import.meta.url);
const tags = git('tag', '--list', 'v[0-9]*', '--merged', 'HEAD').split('\n').filter(Boolean)
  .sort((a, b) => { const [x, y] = [a, b].map(t => t.slice(1).split('.').map(Number)); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
const last = tags.at(-1);
const log = git('log', '--first-parent', '--format=%H%x1f%s%x1f%b%x1e', last ? `${last}..HEAD` : 'HEAD');
const commits = log.split('\x1e').map(c => c.trim()).filter(Boolean).map(c => { const [sha, subject, body = ''] = c.split('\x1f'); return { sha, subject, body }; });

// A squash/merge title may hide the conventional type in the body; check both.
const parse = c => [c.subject, ...c.body.split('\n')].map(l => /^(\w+)(\([^)]*\))?(!)?: (.+)/.exec(l.trim())).find(Boolean);
let level = 0; const groups = { feat: [], fix: [], perf: [] };
for (const c of commits) {
  const m = parse(c); if (!m) continue;
  const [, type, , bang, text] = m;
  const breaking = Boolean(bang) || /^BREAKING[ -]CHANGE:/m.test(c.body);
  if (breaking) level = 3;
  if (type === 'feat') { level = Math.max(level, 2); groups.feat.push(text); }
  else if (type === 'fix' || type === 'perf') { level = Math.max(level, 1); groups[type].push(text); }
}
const base = (last ?? `v${/^version = "(.+)"/m.exec(readFileSync(new URL('Cargo.toml', root), 'utf8'))[1]}`).slice(1).split('.').map(Number);
let version;
if (!last) version = base.join('.');            // first release publishes the version already in the repository
else if (level) { const [M, m, p] = base; version = level === 3 ? `${M + 1}.0.0` : level === 2 ? `${M}.${m + 1}.0` : `${M}.${m}.${p + 1}`; }
const release = Boolean(version) && (last ? level > 0 : commits.length > 0);
const section = (title, items) => items.length ? `### ${title}\n${items.map(i => `- ${i}`).join('\n')}\n` : '';
const notes = !last ? 'Primeira versão publicada.' : [section('Novidades', groups.feat), section('Correções', groups.fix), section('Desempenho', groups.perf)].join('\n').trim();
const plan = { release, version: version ?? null, tag: version ? `v${version}` : null, previous: last ?? null, notes };

if (release && process.argv.includes('--apply')) {
  const edit = (file, pattern, replacement) => { const url = new URL(file, root); const s = readFileSync(url, 'utf8'); if (!pattern.test(s)) throw new Error(`versão não encontrada em ${file}`); writeFileSync(url, s.replace(pattern, replacement)); };
  edit('Cargo.toml', /^version = ".+"/m, `version = "${version}"`);
  edit('installer/src-tauri/tauri.conf.json', /"version": ".+"/, `"version": "${version}"`);
  edit('installer/package.json', /"version": ".+"/, `"version": "${version}"`);
}
if (process.env.GITHUB_OUTPUT) {
  const eol = `EOF_${Date.now()}`;
  appendFileSync(process.env.GITHUB_OUTPUT, `release=${release}\nversion=${plan.version ?? ''}\ntag=${plan.tag ?? ''}\nnotes<<${eol}\n${notes}\n${eol}\n`);
}
console.log(JSON.stringify(plan, null, 2));
