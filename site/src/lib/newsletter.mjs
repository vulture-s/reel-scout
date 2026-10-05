// 訂閱框的落點。
//
// 🔴 2026-10-05 的現實：**還沒有電子報服務**。
// `hevin-ai-os` 的 `references/backlog/brand-studio.md:24` 把「開 Substack/MailerLite
// 免費層」列為 🔴 最高優先，理由是 Act 階段（email 收件桶）是整條漏斗唯一的零引擎段
// —— Reach 端四個引擎的產出全從這裡漏光。
//
// 所以這裡**不假裝有**：ENDPOINT 空字串時，訂閱框退成一個 mailto 連結，
// 讓第一天就有一條真的（雖然弱的）收件路徑，而不是一個送不出去的表單。
// 開好服務之後把 ENDPOINT 填上即一行完成。
//
// ⚠️ 不要為了「看起來完整」填一個猜的網址。一個 POST 到不存在端點的表單，
//    使用者端看起來跟成功一模一樣（按了、頁面跳走了），而名單是空的。
export const ENDPOINT = '';

// 退路用的信箱。商務信箱的 SSOT 見 memory reference_vulture_business_email。
export const FALLBACK_MAILTO = 'info.vulture.studio@gmail.com';

export const hasEndpoint = () => ENDPOINT.trim().length > 0;
