/*
 * Claude Bridge — file-queue bridge between local scripts and Premiere's ExtendScript.
 *
 * No network listener: jobs arrive as files, so nothing outside this Mac user can reach it.
 *   inbox/<id>.jsx   ExtendScript to run (written as .tmp, then renamed — atomic)
 *   outbox/<id>.json result string returned by evalScript
 *   status.json      heartbeat, rewritten every 2 s while Premiere is running
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.join(os.homedir(), 'Library', 'Application Support', 'ClaudePremiereBridge');
const INBOX = path.join(ROOT, 'inbox');
const OUTBOX = path.join(ROOT, 'outbox');
[ROOT, INBOX, OUTBOX].forEach(d => fs.mkdirSync(d, { recursive: true, mode: 0o700 }));

const stateEl = document.getElementById('state');
const logEl = document.getElementById('log');
let busy = false;
let jobsRun = 0;

function log(msg) {
  const line = new Date().toLocaleTimeString() + '  ' + msg;
  logEl.textContent = (line + '\n' + logEl.textContent).slice(0, 2000);
}

function writeAtomic(file, text) {
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

function heartbeat() {
  writeAtomic(path.join(ROOT, 'status.json'), JSON.stringify({
    alive: true, ts: Date.now(), busy, jobsRun, pid: process.pid
  }));
}

function evalScript(code) {
  return new Promise(resolve => window.__adobe_cep__.evalScript(code, resolve));
}

async function poll() {
  if (busy) return;
  let files;
  try { files = fs.readdirSync(INBOX).filter(f => f.endsWith('.jsx')).sort(); }
  catch (e) { return; }
  if (!files.length) return;

  busy = true;
  const f = files[0];
  const id = f.replace(/\.jsx$/, '');
  const src = path.join(INBOX, f);
  try {
    const code = fs.readFileSync(src, 'utf8');
    fs.unlinkSync(src);
    stateEl.textContent = 'running ' + id;
    const t0 = Date.now();
    const result = await evalScript(code);
    writeAtomic(path.join(OUTBOX, id + '.json'), JSON.stringify({ id, raw: result, ms: Date.now() - t0 }));
    jobsRun++;
    log(id + ' done in ' + (Date.now() - t0) + ' ms');
  } catch (e) {
    try { writeAtomic(path.join(OUTBOX, id + '.json'), JSON.stringify({ id, bridgeError: String(e) })); } catch (_) {}
    log(id + ' failed: ' + e);
  } finally {
    busy = false;
    stateEl.textContent = 'ready';
    stateEl.className = 'ok';
  }
}

stateEl.textContent = 'ready';
stateEl.className = 'ok';
log('watching ' + INBOX);
heartbeat();
setInterval(heartbeat, 2000);
setInterval(poll, 250);
