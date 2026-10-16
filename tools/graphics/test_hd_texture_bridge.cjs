'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repo = path.resolve(__dirname, '../..');
const bridgePath = path.join(repo, 'tools/graphics/hd_texture_bridge.js');
const source = fs.readFileSync(bridgePath, 'utf8');
const pureSource = source.slice(0, source.indexOf('const CACHE_EXPORTS'));
assert(pureSource.length > 0, 'pure helper boundary exists');
assert.doesNotMatch(pureSource, /\b(?:Process|Memory|Interceptor|NativeFunction|rpc)\b/,
  'VM only receives pure validators and decisions');

const sandbox = { Set, Map };
vm.runInNewContext(pureSource, sandbox, { filename: 'hd-texture-pure.vm.js' });
const { validatePages, resolveBindingBatch, releaseOwnedBindings } = sandbox.hdTexturePure;
const hashA = 'a'.repeat(64);
const hashB = 'b'.repeat(64);
const valid = [{ sourceRawPath: 'D:\\safe\\source.raw', sourceSha256: hashA,
  hdRawPath: 'D:\\safe\\hd.raw', hdSha256: hashB, width: 1024, height: 1024, format: 'R16_UINT' }];
assert.equal(validatePages(valid).length, 1);
const inputs = Array(128).fill(null);
inputs[0] = { id: 'source-0' };
inputs[8] = { id: 'source-8' };
inputs[127] = { id: 'source-127' };
const resolverCalls = [];
const replacement0 = { id: 'replacement-0' };
const released = [];
const batch = resolveBindingBatch(0, inputs, (input, slot) => {
  resolverCalls.push(slot);
  if (slot === 0) return { hr: 0, value: replacement0 };
  if (slot === 8) return { hr: 1, value: { id: 'unowned-s_false-output' } }; // S_FALSE, unmatched
  if (slot === 127) return { hr: -1, value: { id: 'invalid-output' } };
  throw new Error('unexpected resolver call at slot ' + slot);
}, value => released.push(value), 128);
assert.deepEqual(resolverCalls, [0, 8, 127], 'resolver must inspect input bindings at slots 0, 8, and 127');
assert.equal(batch.bindings[0], replacement0, 'S_OK plus non-null output replaces its binding');
assert.equal(batch.bindings[8], inputs[8], 'S_FALSE retains original binding');
assert.equal(batch.bindings[127], inputs[127], 'failed HRESULT retains original binding');
assert.deepEqual(Array.from(batch.replacedSlots), [0]);
assert.equal(batch.owned.length, 1);
releaseOwnedBindings(batch.owned, value => released.push(value));
releaseOwnedBindings(batch.owned, value => released.push(value));
assert.deepEqual(released, [replacement0], 'native hook and test share the same once-only owned release helper');

const exceptionReleased = [];
const replacementBeforeError = { id: 'before-error' };
assert.throws(() => resolveBindingBatch(0, [inputs[0], null, inputs[8]], (input, slot) => {
  if (slot === 0) return { hr: 0, value: replacementBeforeError };
  throw new Error('resolver fixture exception');
}, value => exceptionReleased.push(value), 128), /resolver fixture exception/);
assert.deepEqual(exceptionReleased, [replacementBeforeError],
  'a later resolver exception releases earlier S_OK-owned output before propagating');

const invalidOutBatch = resolveBindingBatch(127, [inputs[127]], () => ({ hr: 0, value: null }),
  value => released.push(value), 128);
assert.equal(invalidOutBatch.bindings[0], inputs[127], 'S_OK with null output retains original binding');
assert.equal(invalidOutBatch.owned.length, 0, 'S_OK with null output creates no owned reference');

for (const [label, pages] of [
  ['too many pages', Array.from({ length: 33 }, (_, i) => ({ ...valid[0], sourceSha256: i.toString(16).padStart(64, '0') }))],
  ['relative path', [{ ...valid[0], hdRawPath: 'hd.raw' }]],
  ['bad hash', [{ ...valid[0], sourceSha256: 'xyz' }]],
  ['wrong side', [{ ...valid[0], width: 256 }]],
  ['wrong format', [{ ...valid[0], format: 'R16_UNORM' }]],
  ['duplicate identity', [valid[0], { ...valid[0], hdRawPath: 'D:\\safe\\other.raw' }]],
]) assert.throws(() => validatePages(pages), label);

console.log('PASS: manifest bounds, batch slots 0/8/127, S_FALSE and failure preservation, once-only owned release, and exception cleanup. Native Frida APIs were not evaluated.');
