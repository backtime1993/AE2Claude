'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const createRuntime = require('../extensions/pin-clicker/client/input-runtime.cjs');
const root = path.resolve(__dirname, '../extensions/pin-clicker');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pinclicker-config-'));
try {
    assert.throws(() => createRuntime(temporary, { napi: 7 }), /requires input-runtime.json/);
    fs.writeFileSync(path.join(temporary, 'input-runtime.json'), JSON.stringify({ nodeExecutable: 'node' }));
    assert.throws(() => createRuntime(temporary, { napi: 7 }), /existing absolute executable/);
    const native = createRuntime(root, { napi: 8 });
    fs.writeFileSync(path.join(temporary, 'input-runtime.json'), JSON.stringify({ nodeExecutable: process.execPath }));
    const external = createRuntime(temporary, { napi: 7 });
    assert.equal(native.backend, 'in-process');
    assert.equal(external.backend, 'external-node');
    assert.deepEqual(external.getAEWindowRect(), native.getAEWindowRect());
    assert.deepEqual(external.sendKeySequence([], {}), { ok: true, keys: 0 });
    console.log('PASS: missing/invalid configuration, native/external loading, window parity and empty key sequence');
} finally {
    fs.rmSync(temporary, { recursive: true, force: true });
}
