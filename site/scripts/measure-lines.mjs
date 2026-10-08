/**
 * 行長上限 gate —— 量**渲染後**每個中文文字區塊最長那一行的字數。
 *
 * 🔴 為什麼不是靜態查 CSS：這個 regression 兩天內犯了兩次，兩次都不是「忘了寫
 * max-width」，而是**別的地方變寬之後，沒有上限的區塊跟著長**：
 *   #163 紙張 1080→1240 ⇒ `.sub p` / `footer p` 從 68 字/行變 80
 *   #168 改成流動寬度   ⇒ `.diffs p` 從 43 字/行變 48
 * 兩次都是改完重跑審計才發現。靜態查「某某 selector 有沒有 max-width」擋不住
 * 下一個新加的區塊；量渲染結果擋得住 —— 它不在乎是誰、為什麼變寬。
 *
 * 🔴 量的是**實際渲染出來最長那一行**，不是元素的框寬。第一版用框寬 ÷ 字級，
 * 被表格打爆：`<th>` 會被同列其他儲存格撐高撐寬，「給什麼」三個字的格子被算成
 * 105 字/行，一口氣報 24 筆全是假的。逐字取 client rect、依 top 分行，量每一行
 * 自己的左右界，才是讀者掃過的長度。
 *
 * ⚠️ 單位是「最長行寬 ÷ 字級」≈ 中文字/行。CJK 全形字寬 ≈ 1em，所以在中文段落
 * 上幾乎等於實際字數；英數混排會低估，而那正好是不想擋的方向（英文行長的舒適區
 * 本來就比中文寬）。單行區塊不在射程內 —— 它們不換行，行長對閱讀沒有意義。
 */
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const DIST = new URL('../dist/', import.meta.url).pathname;
const BASE = '/reel-scout/';
const PAGES = ['', 'how-it-works.html', 'limits.html', 'install.html', 'demo.html', 'docs.html'];
const WIDTHS = [390, 768, 1024, 1440, 1512, 1920];

// 目前實測最長 44 字/行（1920 的四欄差異化）。46 是 +2 的餘裕：
// 夠緊，任何「某一塊忘了上限」都會超過；夠鬆，不會因字體 metric 的微小差異抖動。
const LIMIT = 46;

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.webp': 'image/webp',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.ico': 'image/x-icon',
};

const server = createServer(async (req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p.startsWith(BASE)) p = p.slice(BASE.length);
  // 🔴 index 的預設檔要在 normalize **之前**補。`normalize('')` 在 Node 回 `'.'`
  //    ——不是 `''`——所以 `p === ''` 判不到，首頁一路變成 readFile(dist/.) → EISDIR
  //    → 404。第一版就是這樣：gate 靜靜地只量了五頁，而 `.diffs` 只在首頁上，
  //    於是「拔掉 .diffs 上限」的負向測試照樣綠。前提沒成立，長得跟通過一模一樣。
  if (p === '' || p.endsWith('/')) p += 'index.html';
  p = normalize(p).replace(/^(\.\.[/\\])+/, '');
  try {
    const body = await readFile(join(DIST, p));
    res.writeHead(200, { 'content-type': MIME[extname(p)] ?? 'application/octet-stream' });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end('nope');
  }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}${BASE}`;

const EXTRACT = (limit) => {
  const CJK = /[一-鿿]/;
  const out = [];
  for (const el of document.querySelectorAll('h1,h2,h3,p,li,td,th,blockquote')) {
    if (!el.offsetParent) continue;
    const txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!CJK.test(txt)) continue;
    // 連上限都塞不滿的短字串不可能超標，先擋掉 —— 逐字取 rect 很貴。
    if (txt.length <= limit) continue;

    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const lines = [];
    let cur = null;
    let node;
    while ((node = walker.nextNode())) {
      const t = node.nodeValue;
      for (let i = 0; i < t.length; i++) {
        if (/\s/.test(t[i])) continue;
        const r = document.createRange();
        r.setStart(node, i);
        r.setEnd(node, i + 1);
        const b = r.getBoundingClientRect();
        if (!b.width && !b.height) continue;
        const top = Math.round(b.top);
        if (!cur || Math.abs(top - cur.top) > 4) {
          cur = { top, l: b.left, r: b.right };
          lines.push(cur);
        } else {
          cur.l = Math.min(cur.l, b.left);
          cur.r = Math.max(cur.r, b.right);
        }
      }
    }
    // 🔴 **不**要求「≥2 行」。第一版有這個過濾，結果 `.sub p` 的負向測試恆綠：
    //    那段只有 61 個字，上限一拿掉就整段擠進**一行**——而一行 80 單位長
    //    正是 #163 弄出來的病。行數不是判準，長度才是。
    if (!lines.length) continue;

    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize);
    const widest = Math.max(...lines.map((x) => x.r - x.l));
    out.push({
      measure: Math.round(widest / fs),
      lines: lines.length,
      cap: cs.maxWidth,
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 24),
      head: txt.slice(0, 30),
    });
  }
  return out;
};

const browser = await chromium.launch();
const bad = [];
let seen = 0;
let worst = 0;
for (const w of WIDTHS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 1200 } });
  const page = await ctx.newPage();
  for (const path of PAGES) {
    const resp = await page.goto(origin + path, { waitUntil: 'networkidle' });
    // 🔴 頁面沒載到要當場炸，不能讓它靜靜地少量一頁。量測工具最危險的失敗
    //    不是算錯，是**少算**——那跟「全部合格」在輸出上完全同形。
    if (!resp || resp.status() !== 200) {
      throw new Error(`頁面載不到（HTTP ${resp ? resp.status() : '無回應'}）：${origin}${path}`);
    }
    const blocks = await page.evaluate(EXTRACT, LIMIT);
    if (!blocks.length) {
      throw new Error(`這一頁量到 0 個中文文字區塊，不正常：${path || 'index'} @ vw ${w}`);
    }
    for (const b of blocks) {
      seen++;
      worst = Math.max(worst, b.measure);
      if (b.measure > LIMIT) bad.push({ w, path: path || 'index', ...b });
    }
  }
  await ctx.close();
}
await browser.close();
server.close();

console.log(
  `量了 ${seen} 個中文文字區塊（${PAGES.length} 頁 × ${WIDTHS.length} 種寬度），` +
    `最長 ${worst} 字/行，上限 ${LIMIT}`,
);
if (bad.length) {
  console.error(`\n🔴 ${bad.length} 個區塊超過 ${LIMIT} 字/行：\n`);
  for (const b of bad) {
    console.error(`  ${String(b.measure).padStart(3)} 字/行 ×${b.lines} 行  vw ${String(b.w).padStart(4)}  ${b.path}`);
    console.error(`       <${b.tag}${b.cls ? ` class="${b.cls}"` : ''}>  max-width: ${b.cap}`);
    console.error(`       「${b.head}…」`);
  }
  console.error('\n多半是這一塊沒有 max-width，而別的地方變寬了（紙張、欄數、字級）。');
  console.error('補一個跟站上其他本文一致的上限（68ch），或在那個區塊明寫豁免理由。');
  process.exit(1);
}
console.log('✅ 全部在上限內');
