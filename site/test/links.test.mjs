// 文件頁連結解析與標題降級的 case 表。
//
// 🔴 為什麼有這支：官網第一版上線之後，`commands.html` 線上實測有兩個問題，
//    兩個都是**建構成功、CI 全綠**的狀態下存在的：
//      ① `../prompts/signal-reliability-cheatsheet.md` 回 404
//         —— 改寫器只認同層的 .md，其餘「原樣留著」。原樣留著不是中立，是保證 404。
//      ② 頁面有兩個 `<h1>`：版面給的短標題，加上 md 自己那個長標題。
//
// 兩個都不是 code 讀得出來的，是開頁面看出來的。所以把判斷釘成可執行的。
//
// 跑法：`node --test site/test/`（site/package.json 的 `npm test`）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveDocHref } from '../src/lib/rewrite-doc-links.mjs';

const BLOB = 'https://github.com/vulture-s/reel-scout/blob/master/';

test('本站有發佈的同層 .md → 站內 .html', () => {
  assert.equal(resolveDocHref('./crv-vs-reel-scout.md'), 'crv-vs-reel-scout.html');
  assert.equal(resolveDocHref('roadmap.md'), 'roadmap.html');
  assert.equal(resolveDocHref('roadmap.md#phase-6'), 'roadmap.html#phase-6');
});

test('repo 內但本站沒發佈的 .md → GitHub 上那一份（不是留著 404）', () => {
  assert.equal(resolveDocHref('../prompts/signal-reliability-cheatsheet.md'),
    BLOB + 'prompts/signal-reliability-cheatsheet.md');
  assert.equal(resolveDocHref('../SKILL.md'), BLOB + 'SKILL.md');
  assert.equal(resolveDocHref('../README.md'), BLOB + 'README.md');
  // docs/ 底下的子目錄也要正規化對
  assert.equal(resolveDocHref('notes/internal.md'), BLOB + 'docs/notes/internal.md');
});

test('同層但本站沒發佈的 .md 不得被當成已發佈', () => {
  // 這條是誤報防護：若 PUBLISHED 判斷壞掉，它會變成一個指向不存在頁面的站內連結
  // —— 而站內 404 比指到 GitHub 更糟，因為它看起來像是這個站該有的東西。
  assert.equal(resolveDocHref('./no-such-doc.md'), BLOB + 'docs/no-such-doc.md');
});

test('外部網址、錨點、非 .md 一律不動', () => {
  for (const href of [
    'https://example.com/a.md', 'http://example.com/b.md',
    'mailto:x@y.z', '#anchor', '//cdn.example/c.md',
    'commands.html', '../assets/inspector.jpg', '',
  ]) assert.equal(resolveDocHref(href), href);
});
