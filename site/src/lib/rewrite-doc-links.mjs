// 把 docs/*.md 裡的相對連結改寫成本站的路由。
//
// 文件頁是直接讀 repo 的 `docs/*.md` 與 `CHANGELOG.md` 來渲染的（唯一真相還是那些檔，
// 官網只是另一個 surface）。那些 md 裡面寫的是 `./crv-vs-reel-scout.md` 這種
// repo 內相對路徑 —— 原樣輸出到網站上會 404。
//
// 只改寫**指向 docs/ 內 .md** 的連結。外部連結、錨點、指向 repo 其他地方的路徑
// 一律不動：改寫看不懂的東西就是製造壞連結，而壞連結比沒連結難查。
export function rewriteDocLinks() {
  return (tree) => {
    visit(tree, (node) => {
      if (node.tagName !== 'a') return;
      const href = node.properties?.href;
      if (typeof href !== 'string') return;
      const m = /^\.?\/?([A-Za-z0-9._-]+)\.md(#.*)?$/.exec(href);
      if (!m) return;
      node.properties.href = `${m[1]}.html${m[2] ?? ''}`;
    });
  };
}

// 極小的 hast walker。拉 unist-util-visit 進來只為了這一個用途不值得 ——
// 本站的依賴刻意只有 astro 與 markdown-remark 兩個。
function visit(node, fn) {
  fn(node);
  for (const child of node.children ?? []) visit(child, fn);
}
