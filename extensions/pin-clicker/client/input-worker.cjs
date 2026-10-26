'use strict';
const fs = require('fs');
const path = require('path');
const methods = new Set([
    'sendInputClick', 'sendInputDrag', 'sendKeySequence', 'focusAEWindow',
    'enumerateAEWindows', 'enumerateAETopWindows', 'dismissAEScriptDialogs', 'getAEWindowRect'
]);

async function main() {
    const input = fs.readFileSync(0, 'utf8');
    if (Buffer.byteLength(input) > 65536) throw new Error('Input request is too large');
    const request = JSON.parse(input);
    if (Number(process.versions.node.split('.')[0]) < 18 || Number(process.versions.napi || 0) < 8) {
        throw new Error('Input worker requires Node 18+ and N-API 8+');
    }
    if (request.method !== 'probe' && !methods.has(request.method)) throw new Error('Unknown input method');
    const koffi = require(path.join(__dirname, '..', 'node_modules', 'koffi'));
    const runtime = require('./input-native.cjs')(koffi);
    const result = request.method === 'probe'
        ? { napi: Number(process.versions.napi), nodeMajor: Number(process.versions.node.split('.')[0]) }
        : await runtime[request.method].apply(null, Array.isArray(request.args) ? request.args : []);
    process.stdout.write(JSON.stringify({ ok: true, result }));
}
main().catch(function (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error) }));
});
