// 把 docs/*.md 裡的相對連結改寫成**真的解得開的**位址。
//
// 文件頁直接讀 repo 的 `docs/*.md` 與 `CHANGELOG.md` 渲染（唯一真相還是那些檔，
// 官網只是另一個 surface）。那些 md 裡寫的是 repo 內相對路徑，原樣輸出會 404。
//
// 🔴 第一版只改寫「同層的 .md」，其餘**原樣留著** —— 註解當時寫的理由是
// 「改寫看不懂的東西就是製造壞連結」。那個理由對，但結論錯了：
// 原樣留著不是中立，是**保證 404**。`docs/commands.md` 裡的
// `../prompts/signal-reliability-cheatsheet.md` 線上實測回 404。
//
// 現在分三類，每一類都有落點：
//   ① 本站有發佈的那幾份 → `<slug>.html`
//   ② 其他 repo 內的 .md（含 `../` 出 docs/ 的）→ GitHub 上的那一份
//   ③ 外部網址、錨點、非 .md → 不動
//
// ② 選 GitHub 而不是「拿掉連結」，因為那些檔**是真的存在**，只是不在這個站上。
// 把它變成不可點，讀者就失去了唯一能到那裡的路。
const REPO_BLOB = 'https://github.com/vulture-s/reel-scout/blob/master/';

// 本站發佈的 slug。與 published-docs.mjs 同一份來源，避免兩邊各自漂。
import { DOCS } from './published-docs.mjs';
const PUBLISHED = new Set([...DOCS.map((d) => d.slug), 'changelog']);

export function rewriteDocLinks() {
  return (tree) => {
    demoteLeadingH1(tree);
    visit(tree, (node) => {
      if (node.tagName !== 'a') return;
      const href = node.properties?.href;
      if (typeof href !== 'string') return;
      node.properties.href = resolveDocHref(href);
    });
  };
}

/** 這些 md 自己開頭就有一個 `# ...`，而頁面已經給了一個 h1 —— 把它降成 h2。
 *
 * 🔴 第一版是用 CSS 把它「看起來像 h2」。那只改外觀：`<h1>` 還是兩個，
 *    而螢幕閱讀器讀的是標籤不是樣式 —— 當時寫在註解裡的「標題階層才合法」
 *    是一句**不成立的主張**。改在這裡才真的成立。
 *
 * 當時不在這裡做的理由是「網站不該為了版面去改資料」。那個顧慮本身對，
 * 但指錯了對象：rehype 動的是**渲染出來的那棵樹**，`docs/*.md` 一個位元都沒變，
 * 在 GitHub 上讀的時候那個 h1 仍然是 h1。
 */
function demoteLeadingH1(tree) {
  for (const node of tree.children ?? []) {
    if (node.type !== 'element') continue;
    if (node.tagName === 'h1') { node.tagName = 'h2'; node.properties = { ...node.properties, 'data-demoted': 'true' }; }
    return;   // 只看第一個元素；後面的 h1（如果有）是作者刻意的分節
  }
}

/** 匯出給測試用：一個純函式，輸入 href、輸出 href。 */
export function resolveDocHref(href) {
  // ③ 外部網址、協定連結、純錨點 —— 不動
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('#') || href.startsWith('//')) return href;
  const m = /^([^#?]*\.md)(#.*)?$/i.exec(href);
  if (!m) return href;                       // ③ 不是 .md
  const [, path, hash = ''] = m;

  // ① 同層、且本站有發佈
  const same = /^\.?\/?([A-Za-z0-9._-]+)\.md$/.exec(path);
  if (same && PUBLISHED.has(same[1])) return `${same[1]}.html${hash}`;

  // ② 其餘 repo 內的 .md → GitHub。`../` 是相對於 docs/，所以先把它正規化掉。
  const normalised = normaliseFromDocs(path);
  return `${REPO_BLOB}${normalised}${hash}`;
}

/** `../prompts/x.md` → `prompts/x.md`；`./y.md` / `y.md` → `docs/y.md` */
function normaliseFromDocs(path) {
  const parts = ('docs/' + path.replace(/^\.\//, '')).split('/');
  const out = [];
  for (const seg of parts) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') out.pop();
    else out.push(seg);
  }
  return out.join('/');
}

// 極小的 hast walker。拉 unist-util-visit 進來只為了這一個用途不值得 ——
// 本站的依賴刻意只有 astro 與 markdown-remark 兩個。
function visit(node, fn) {
  fn(node);
  for (const child of node.children ?? []) visit(child, fn);
}
