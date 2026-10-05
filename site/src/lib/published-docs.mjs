// 哪些 docs/*.md 會被發佈成網頁。
//
// 🔴 **白名單，不是 glob**。這些檔已經在公開 repo 裡，所以發佈它們沒有新增曝光；
// 但 glob 的語意是「未來任何放進 docs/ 的東西都自動上線」，而那個預設是錯的
// —— 下一份放進 docs/ 的筆記可能是給自己看的。要上線就來這裡加一行。
//
// `title` 是導覽與頁標用的名字，不從 md 的第一個標題抓 —— 那些標題是給 repo 讀者看的
// （例如「Reel Scout — Roadmap」），在網站的側欄裡會四個字重複三次。
export const DOCS = [
  { slug: 'commands',                 title: '指令全表',        blurb: '每一個 CLI 指令與參數，以及 MCP 的 19 個工具。' },
  { slug: 'roadmap',                  title: '開發路線',        blurb: '做到哪、下一步是什麼，以及刻意不做的東西與理由。' },
  { slug: 'crv-vs-reel-scout',        title: '對標：crv',       blurb: '跟 claude-real-video 的差異，以及從它身上學到什麼。' },
  { slug: 'vibe-reader-vs-reel-scout',title: '對標：vibe-reader', blurb: '舉證護欄這個切角的來源。' },
  { slug: 'video-analyzer-research',  title: '選型研究',        blurb: '當初為什麼不直接用現成的影片分析服務。' },
  { slug: 'gui-evaluation',           title: 'GUI 選型',        blurb: '檢視介面為什麼是自包含 HTML 而不是一個 app。' },
];

export const CHANGELOG = { slug: 'changelog', title: '更新紀錄' };
