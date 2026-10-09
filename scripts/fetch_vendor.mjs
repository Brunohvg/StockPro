import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';

const url = 'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
const expected = '660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e';
const response = await fetch(url, { signal: AbortSignal.timeout(60000) });
if (!response.ok) throw new Error('Download de html5-qrcode falhou: HTTP ' + response.status);
const buffer = Buffer.from(await response.arrayBuffer());
const actual = createHash('sha256').update(buffer).digest('hex');
if (actual !== expected) throw new Error('Checksum divergente para html5-qrcode@2.3.8: ' + actual);
await mkdir('static/vendor', { recursive: true });
await writeFile('static/vendor/html5-qrcode-2.3.8.min.js', buffer);
console.log('html5-qrcode@2.3.8: hash SHA-256 validado.');
