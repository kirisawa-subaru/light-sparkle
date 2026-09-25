// Record one full performance of index.html (picture + sound) with headless Chrome.
//
//   node tools/record.mjs [--out clawd-lullaby.webm] [--lights-off 10] [--chrome /path/to/chrome]
//
// Timeline: 0.5 s of the sleeping cat, then the performance starts; the lamp goes off at
// --lights-off seconds (omit or pass -1 to keep the light on). Recording stops just before
// the piece loops. Misses and meows are random, so every take is different.
// Needs Node 22+ (global WebSocket) and a Chrome/Chromium binary.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith('--') ? a.concat([[v.slice(2), all[i + 1]]]) : a), []));
const out = path.resolve(args.out || 'clawd-lullaby.webm');
const lightsOff = args['lights-off'] === undefined ? 10 : +args['lights-off'];
const chrome = args.chrome || process.env.CHROME || ['google-chrome', 'chromium', 'chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(c => c.includes('/') ? fs.existsSync(c) : true);
const port = 9300 + Math.floor(Math.random() * 500);

// A temporary copy of the page whose audio output is also routed into a MediaStream for the recorder.
const here = path.dirname(fileURLToPath(import.meta.url));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'clawd-rec-'));
const page = fs.readFileSync(path.join(here, '..', 'index.html'), 'utf8');
const tap = 'comp.connect(actx.destination);';
if (!page.includes(tap)) throw new Error('audio tap point not found in index.html');
fs.writeFileSync(path.join(tmp, 'index.html'), page.replace(tap, tap + ' window.__recDest = actx.createMediaStreamDestination(); comp.connect(window.__recDest);'));

const proc = spawn(chrome, ['--headless=new', '--no-sandbox', '--autoplay-policy=no-user-gesture-required', `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(tmp, 'profile')}`, 'about:blank'], { stdio: 'ignore' });
proc.on('error', e => { console.error(`cannot start Chrome (${chrome}): ${e.message}\npass --chrome /path/to/chrome or set CHROME`); process.exit(1); });
const cleanup = () => { try { proc.kill(); } catch {} setTimeout(() => fs.rmSync(tmp, { recursive: true, force: true }), 500); };

try {
  let list;
  for (let i = 0; i < 50 && !list; i++) { try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { await new Promise(r => setTimeout(r, 200)); } }
  const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl);
  let id = 0; const pend = {};
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend[m.id]) pend[m.id](m); };
  await new Promise(r => ws.onopen = r);
  const ev = async expression => {
    const r = (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, timeout: 180000 })).result;
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  await send('Emulation.setDeviceMetricsOverride', { width: 760, height: 760, deviceScaleFactor: 2, mobile: false });  // 1280x1280 canvas
  await send('Page.navigate', { url: 'file://' + path.join(tmp, 'index.html') });
  await new Promise(r => setTimeout(r, 2000));

  console.log('recording…');
  console.log(await ev(`new Promise(res => {
    const LIGHTS_OFF = ${lightsOff};
    // init audio, pause it so the recorder can grab the audio track, then roll
    toggle();
    actx.suspend().then(() => {
      const stream = new MediaStream([...cv.captureStream(60).getVideoTracks(), window.__recDest.stream.getAudioTracks()[0]]);
      const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus', videoBitsPerSecond: 10e6, audioBitsPerSecond: 192000 });
      const chunks = [];
      rec.ondataavailable = e => chunks.push(e.data);
      rec.onstop = async () => {
        const buf = new Uint8Array(await new Blob(chunks).arrayBuffer());
        let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        window.__b64 = btoa(bin); res('recorded ' + buf.length + ' bytes');
      };
      rec.start(1000);
      setTimeout(() => actx.resume(), 500);
      if (LIGHTS_OFF >= 0) setTimeout(() => toggleLight(), LIGHTS_OFF * 1000);
      setTimeout(() => rec.stop(), 500 + (CAT_READY + LOOP * SPB) * 1000 - 100);  // stop right before the piece loops
    });
  })`));
  const len = await ev('window.__b64.length'), parts = [];
  for (let i = 0; i < len; i += 4e6) parts.push(await ev(`window.__b64.slice(${i}, ${i + 4e6})`));
  fs.writeFileSync(out, Buffer.from(parts.join(''), 'base64'));
  console.log('written', out);
} finally {
  cleanup();
}
