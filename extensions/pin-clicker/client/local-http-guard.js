/* Native loopback clients only; browser pages must never drive AE or input. */
(function (root) {
    'use strict';
    root.AeLocalHttp = {
        trusted: function (req, port) {
            const headers = req.headers || {};
            const raw = req.rawHeaders || [];
            let hosts = 0;
            for (let i = 0; i < raw.length; i += 2) {
                if (raw[i].toLowerCase() === 'host') hosts++;
            }
            const host = (headers.host || '').toLowerCase();
            return hosts === 1 &&
                (host === '127.0.0.1:' + port || host === 'localhost:' + port) &&
                !Object.prototype.hasOwnProperty.call(headers, 'origin') &&
                !Object.prototype.hasOwnProperty.call(headers, 'sec-fetch-site');
        },
        readBody: function (req, maximum) {
            return new Promise(function (resolve, reject) {
                const chunks = [];
                let size = 0, failed = false;
                req.on('data', function (chunk) {
                    if (failed) return;
                    size += chunk.length;
                    if (size > maximum) {
                        failed = true; chunks.length = 0;
                        reject(new Error('request_too_large'));
                        return;
                    }
                    chunks.push(chunk);
                });
                req.on('end', function () {
                    if (failed) return;
                    try {
                        const text = Buffer.concat(chunks).toString('utf8');
                        const body = text ? JSON.parse(text) : {};
                        if (!body || Array.isArray(body) || typeof body !== 'object') throw new Error('body_must_be_object');
                        resolve(body);
                    } catch (error) { reject(error); }
                });
                req.on('error', reject);
                req.on('aborted', function () { reject(new Error('request_aborted')); });
            });
        }
    };
})(typeof window === 'undefined' ? globalThis : window);
