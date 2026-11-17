#!/usr/bin/env node
// Semantic release helper: next version from Conventional Commits since the last v* tag.
//   node tools/release.mjs            -> prints JSON {release, version, tag, notes}
//   node tools/release.mjs --apply    -> also bumps Cargo.toml and installer/package.json
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

const git = (...args) => execFileSync('git', args, { encoding: 'utf8' }).trim();
const lastTag = (() => { try { return git('describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*'); } catch { return ''; } })();
const current = lastTag ? lastTag.slice(1) : readFileSync('Cargo.toml', 'utf8').match(/^version = "(\d+\.\d+\.\d+)"/m)[1];

const log = git('log', lastTag ? `${lastTag}..HEAD` : 'HEAD', '--no-merges', '--format=%H%x1f%s%x1f%b%x1e');
const groups = { breaking: [], feat: [], fix: [], perf: [] };
for (const entry of log.split('\x1e').map(e => e.trim()).filter(Boolean)) {
  const [hash, subject, body = ''] = entry.split('\x1f');
  const m = subject.match(/^(\w+)(\([^)]*\))?(!)?:\s*(.+)$/);
  if (!m || /^chore\(release\)/.test(subject)) continue;
  const [, type, scope = '', bang, text] = m;
  const line = `- ${scope ? `**${scope.slice(1, -1)}:** ` : ''}${text} (${hash.slice(0, 7)})`;
  if (bang || /^BREAKING CHANGE:/m.test(body)) groups.breaking.push(line);
  else if (groups[type]) groups[type].push(line);
}

let [major, minor, patch] = current.split('.').map(Number);
if (groups.breaking.length) { major++; minor = 0; patch = 0; }
else if (groups.feat.length) { minor++; patch = 0; }
else if (groups.fix.length || groups.perf.length) patch++;
else { console.log(JSON.stringify({ release: false })); process.exit(0); }

const version = `${major}.${minor}.${patch}`;
const section = (title, lines) => (lines.length ? `### ${title}\n${lines.join('\n')}\n\n` : '');
const notes = section('Mudanças incompatíveis', groups.breaking) + section('Novidades', groups.feat) + section('Correções', groups.fix) + section('Desempenho', groups.perf);

if (process.argv.includes('--apply')) {
  const cargo = readFileSync('Cargo.toml', 'utf8').replace(/^version = "\d+\.\d+\.\d+"/m, `version = "${version}"`);
  writeFileSync('Cargo.toml', cargo);
  const pkg = JSON.parse(readFileSync('installer/package.json', 'utf8'));
  pkg.version = version;
  writeFileSync('installer/package.json', `${JSON.stringify(pkg, null, 2)}\n`);
}
console.log(JSON.stringify({ release: true, version, tag: `v${version}`, notes }));
