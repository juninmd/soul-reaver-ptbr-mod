'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

let defaultRoot = __dirname;
while (!fs.existsSync(path.join(defaultRoot, 'AGENTS.md'))) {
  const parent = path.dirname(defaultRoot);
  if (parent === defaultRoot) throw new Error('Repository root not found');
  defaultRoot = parent;
}
const repoRoot = path.resolve(process.argv[2] || defaultRoot);
const bridgePath = path.resolve(repoRoot, process.argv[3] ||
  'tools/subtitles/unicode_runtime_bridge.js');
const corpusPath = path.resolve(repoRoot, process.argv[4] ||
  'validate/02-legendas-unicode/captions-unicode-paginated-v1.json');
const bridgeSource = fs.readFileSync(bridgePath, 'utf8');
const canonicalCorpusPath = path.resolve(repoRoot,
  'validate/02-legendas-unicode/captions-unicode-paginated-v1.json');

function between(start, end) {
  const first = bridgeSource.indexOf(start);
  assert.notEqual(first, -1, `helper not found: ${start}`);
  const after = bridgeSource.indexOf(end, first);
  assert.notEqual(after, -1, `helper boundary not found: ${end}`);
  return bridgeSource.slice(first, after);
}

// Evaluate only pure input/timing helpers. Never evaluate the Frida bridge module.
const pureHelpers = [
  'const MAX_CAPTION_ID = 478;',
  between('function validateText(', 'function readGuid('),
  between('function clockStep(', 'function readGameState('),
  'globalThis.bridgeTestHelpers = { validateRows, clockStep };',
].join('\n');
assert.doesNotMatch(pureHelpers, /\b(?:Process|Memory|Interceptor|NativeFunction|rpc)\b/,
  'the VM harness must not include Frida/native interfaces');

const sandbox = { console, Map, Set };
vm.runInNewContext(pureHelpers, sandbox, { filename: 'bridge-pure-helpers.vm.js' });
const { validateRows, clockStep } = sandbox.bridgeTestHelpers;
const envelope = JSON.parse(fs.readFileSync(corpusPath, 'utf8'));
assert.equal(envelope.schema, 1);
assert.equal(envelope.format, 'unicode-v1');
assert.equal(envelope.encoding, 'UTF-8');
assert.equal(envelope.normalization, 'NFC');

const prepared = validateRows(envelope.captions);
const pageCount = envelope.captions.reduce((count, row) => count + row.pages.length, 0);
if (corpusPath === canonicalCorpusPath) {
  assert.equal(prepared.size, 230);
  assert.equal(pageCount, 266);
} else {
  assert.equal(prepared.size, envelope.captions.length,
    'bridge must accept every row produced by the subtitle builder');
  const acceptedPageCount = [...prepared.values()].reduce((count, row) => count + row.pages.length, 0);
  assert.equal(pageCount, acceptedPageCount, 'bridge must retain every generated page');
  for (const row of envelope.captions) {
    const accepted = prepared.get(row.id);
    assert.equal(accepted.text, row.text, `bridge changed UTF-8 caption text for id ${row.id}`);
    assert.equal(JSON.stringify(accepted.pages), JSON.stringify(row.pages),
      `bridge changed pagination or timing for id ${row.id}`);
  }
}

function rejects(rows, label) {
  let rejected = false;
  try { validateRows(rows); } catch (_) { rejected = true; }
  assert.equal(rejected, true, `${label} should be rejected`);
}

const first = envelope.captions[0];
const second = envelope.captions[1];
rejects([first, { ...second, id: first.id }], 'duplicate ID');

const validRow = {
  id: 1,
  duration_ms: 1000,
  text: 'alpha beta',
  pages: [
    { text: 'alpha', start_ms: 0, end_ms: 500 },
    { text: 'beta', start_ms: 500, end_ms: 1000 },
  ],
};
rejects([{ ...validRow, pages: [
  { text: 'alpha', start_ms: 0, end_ms: 400 },
  { text: 'beta', start_ms: 500, end_ms: 1000 },
] }], 'page gap');
rejects([{ ...validRow, pages: [
  { text: 'alpha', start_ms: 0, end_ms: 500 },
  { text: 'beta', start_ms: 499, end_ms: 1000 },
] }], 'page overlap');
rejects([{ ...validRow, pages: [...validRow.pages].reverse() }], 'reordered pages');
rejects([{ ...validRow, text: 'alpha\u0001beta', pages: undefined }], 'control character');

assert.equal(clockStep(0, 100, 1100, true).elapsedMs, 1000, 'a 1000 ms playing gap must count fully');
const paused = clockStep(320, 1000, 5100, false);
assert.equal(paused.elapsedMs, 320, 'paused time must not increase elapsed caption time');
assert.equal(clockStep(paused.elapsedMs, paused.lastTick, 5200, true).elapsedMs, 420,
  'resume should count only time since the last observed paused tick');

console.log(`PASS: ${prepared.size} captions / ${pageCount} pages; duplicate, gap, overlap, order and control rejects; 1000 ms clock gap and pause freeze. Native calls not mocked.`);
