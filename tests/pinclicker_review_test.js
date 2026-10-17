'use strict';

// Exercise the shipped CEP handlers and their generated JSX without Adobe or input.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.argv[2];
const source = fs.readFileSync(path.join(root, 'extensions/pin-clicker/client/main.js'), 'utf8');
const marker = '    // --- boot ----------------------------------------------------------------';
assert.ok(source.includes(marker));
const instrumented = source.replace(marker,
    '    globalThis.review = {handleEnsureViewer, evalJSXJson}; return;\n' + marker);

function fixture() {
    const state = { dispatches: 0, script: null, raw: undefined, opened: [], selected: [] };
    const app = { project: { activeItem: null, numItems: 0 },
        activeViewer: {setActive() {}}, toolName: 'Selection' };
    function CompItem(id, name) {
        this.id = id; this.name = name; this.width = 100; this.height = 100; this.time = 0;
        this.numLayers = 1;
        const layer = {index: 1, name: 'Layer', enabled: true, solo: false};
        Object.defineProperty(layer, 'selected', {set(value) { state.selected.push([id, value]); }});
        this.layer = () => layer;
        this.openInViewer = () => { state.opened.push(id); app.project.activeItem = this; };
    }
    const first = new CompItem(1, 'Active');
    const special = new CompItem(2, 'Path\\shot "one"\n\u2028');
    const items = [first, special];
    app.project.activeItem = first;
    app.project.numItems = items.length;
    app.project.item = i => items[i - 1];
    const scriptContext = vm.createContext({app, CompItem, JSON});
    const fakeFs = {readFileSync() { return '{"version":"test"}'; }, mkdirSync() {}, appendFileSync() {}, appendFile() {}};
    const context = vm.createContext({
        CSInterface: function () { return {
            getSystemPath() { return root; },
            evalScript(script, callback) {
                state.dispatches++; state.script = script;
                callback(state.raw !== undefined ? state.raw : vm.runInContext(script, scriptContext));
            }
        }; },
        SystemPath: {EXTENSION: 'extension'},
        document: {getElementById() { return null; }},
        cep_node: {require(name) { return name === 'fs' ? fakeFs : require(name); }},
        window: {}, process: {pid: 1}, console: {log() {}, warn() {}}
    });
    vm.runInContext(instrumented, context);
    return {review: context.review, state, special};
}

(async () => {
    let passed = 0;
    const failures = [];
    async function test(name, run) {
        try { await run(); passed++; }
        catch (error) { failures.push(name + ': ' + error.stack); }
    }
    await test('missing comp cannot select a layer in the active comp', async () => {
        const {review, state} = fixture();
        const result = await review.handleEnsureViewer({comp_id: 999, layer_index: 1});
        assert.equal(result.error, 'comp_not_found');
        assert.deepEqual(state.selected, []);
        assert.deepEqual(state.opened, []);
    });
    await test('invalid layer cannot report a successful target', async () => {
        const {review, state} = fixture();
        const result = await review.handleEnsureViewer({comp_id: 2, layer_index: 9});
        assert.equal(result.error, 'layer_index_out_of_range');
        assert.deepEqual(state.selected, []);
        assert.deepEqual(state.opened, []);
    });
    await test('composition names preserve quotes, backslashes and line separators', async () => {
        const {review, state, special} = fixture();
        const result = await review.handleEnsureViewer({comp_name: special.name, layer_index: 1});
        assert.equal(result.ok, true);
        assert.equal(result.comp.id, 2);
        assert.deepEqual(state.opened, [2]);
    });
    await test('nonintegral target IDs reject before dispatch', async () => {
        for (const body of [{comp_id: -1}, {comp_id: 1.5}, {comp_id: 'Infinity'}, {layer_index: 0}]) {
            const {review, state} = fixture();
            await assert.rejects(review.handleEnsureViewer(body), /bad_comp_id|bad_layer_index/);
            assert.equal(state.dispatches, 0);
        }
    });
    await test('JSX runtime errors reject instead of becoming normal data', async () => {
        const {review} = fixture();
        await assert.rejects(review.evalJSXJson('throw new Error("host failed");'), /host failed/);
    });
    await test('CEP evaluation failure rejects', async () => {
        const {review, state} = fixture();
        state.raw = 'EvalScript error.';
        await assert.rejects(review.evalJSXJson('return 1;'), /EvalScript error/);
    });
    await test('ordinary JSON and string values remain compatible', async () => {
        const {review} = fixture();
        assert.equal((await review.evalJSXJson('return {value:2};')).value, 2);
        assert.equal(await review.evalJSXJson('return "plain text";'), 'plain text');
    });
    if (failures.length) {
        console.error(failures.join('\n\n'));
        process.exitCode = 1;
    }
    console.log(JSON.stringify({passed, failed: failures.length}));
})().catch(error => { console.error(error); process.exitCode = 1; });
