'use strict';
const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const methods = [
    'sendInputClick', 'sendInputDrag', 'sendKeySequence', 'focusAEWindow',
    'enumerateAEWindows', 'enumerateAETopWindows', 'dismissAEScriptDialogs', 'getAEWindowRect'
];

module.exports = function createRuntime(extensionRoot, options) {
    const napi = options && options.napi != null ? options.napi : Number(process.versions.napi || 0);
    if (napi >= 8) {
        const native = require('./input-native.cjs')(require(path.join(extensionRoot, 'node_modules', 'koffi')));
        native.backend = 'in-process';
        return native;
    }
    const configPath = path.join(extensionRoot, 'input-runtime.json');
    if (!fs.existsSync(configPath)) {
        throw new Error('CEP N-API ' + napi + ' requires input-runtime.json with an absolute nodeExecutable (Node 18+).');
    }
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    const executable = config.nodeExecutable;
    if (typeof executable !== 'string' || !path.isAbsolute(executable) || !fs.existsSync(executable)) {
        throw new Error('input-runtime.json nodeExecutable must name an existing absolute executable.');
    }
    function call(method, args) {
        const result = childProcess.spawnSync(executable, [path.join(__dirname, 'input-worker.cjs')], {
            input: JSON.stringify({ method, args }), encoding: 'utf8', windowsHide: true,
            timeout: 30000, maxBuffer: 2 * 1024 * 1024,
            env: Object.assign({}, process.env, { NODE_OPTIONS: '', NODE_PATH: '' })
        });
        if (result.error) throw result.error;
        if (result.status !== 0) throw new Error('Input worker failed: ' + (result.stderr || 'exit ' + result.status).trim());
        let response;
        try { response = JSON.parse(result.stdout); }
        catch (_) { throw new Error('Input worker returned invalid JSON'); }
        if (!response.ok) throw new Error(response.error || 'Input worker operation failed');
        return response.result;
    }
    const probe = call('probe', []);
    if (!probe || probe.napi < 8 || probe.nodeMajor < 18) throw new Error('Input worker requires Node 18+ and N-API 8+.');
    const runtime = { backend: 'external-node' };
    methods.forEach(function (method) {
        runtime[method] = function () { return call(method, Array.prototype.slice.call(arguments)); };
    });
    return runtime;
};
