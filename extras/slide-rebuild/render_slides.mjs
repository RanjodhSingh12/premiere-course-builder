// Render an HTML timeline page (window.render(t) / window.SCENES / window.DURATION) to video,
// one MP4 per scene, frame by frame in headless Chromium. Nothing appears on screen.
//
//   node tools/render_slides.mjs <slides.html> <outdir> video [fps]
//   node tools/render_slides.mjs <slides.html> <outdir> stills 12.5 30 ...
//
// Static frames are reused (only frames where something moves are re-captured).
import { createRequire } from 'module';
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';

const require = createRequire(import.meta.url);
// PLAYWRIGHT_CORE=/path/to/node_modules/playwright-core reuses an existing install (and its cached Chromium).
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

const [, , html, outdir, mode, ...rest] = process.argv;
fs.mkdirSync(outdir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto('file://' + path.resolve(html));
await page.evaluate(() => Promise.all(['400', '500', '600', '700'].map(w => document.fonts.load(`${w} 20px "IBM Plex Sans"`))));
await page.evaluate(() => document.fonts.ready);
const fontOk = await page.evaluate(() => document.fonts.check('700 40px "IBM Plex Sans"') && document.fonts.check('400 20px "IBM Plex Sans"'));
if (!fontOk) { console.error('IBM Plex Sans did not load'); process.exit(2); }
await page.evaluate(() => Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))));

const shot = () => page.screenshot({ type: 'jpeg', quality: 93 });

if (mode === 'stills') {
  for (const t of rest) {
    await page.evaluate(t => window.render(t), +t);
    fs.writeFileSync(path.join(outdir, `still_${t}.jpg`), await shot());
  }
} else {
  const fps = +(rest[0] || 30);
  const scenes = await page.evaluate(() => window.SCENES);
  const dur = await page.evaluate(() => window.DURATION);
  const manifest = [];
  let total = 0, captured = 0;
  for (let i = 0; i < scenes.length; i++) {
    const from = Math.round(scenes[i].start * fps);
    const to = i + 1 < scenes.length ? Math.round(scenes[i + 1].start * fps) : Math.round(dur * fps);
    const file = path.join(outdir, `scene_${String(i).padStart(2, '0')}.mp4`);
    const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '14', '-pix_fmt', 'yuv420p', '-r', String(fps), file],
      { stdio: ['pipe', 'inherit', 'inherit'] });
    let last = null;
    for (let f = from; f < to; f++) {
      const moving = await page.evaluate(t => window.render(t), f / fps);
      if (moving || !last) { last = await shot(); captured++; }
      if (!ff.stdin.write(last)) await new Promise(r => ff.stdin.once('drain', r));
      total++;
    }
    ff.stdin.end();
    await new Promise((res, rej) => ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg ' + c))));
    manifest.push({ file, start: from / fps, end: to / fps, frames: to - from });
    process.stdout.write(`scene ${i}: ${(from / fps).toFixed(2)}-${(to / fps).toFixed(2)}s\n`);
  }
  fs.writeFileSync(path.join(outdir, 'scenes.json'), JSON.stringify({ fps, duration: dur, scenes: manifest }, null, 1));
  console.log(`frames ${total}, captured ${captured}`);
}
await browser.close();
