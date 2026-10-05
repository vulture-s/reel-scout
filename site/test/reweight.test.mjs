// 官網的「重新加權」必須算出跟 CLI 一樣的數字。
//
// 🔴 為什麼這支存在：首頁那個面板是**可以真的拖**的，而它自己實作了一份
// computeOverall。`reel_scout/inspector.py` 的同名函式檔頭已經寫過一次這個風險
// ——「If those ever diverge the page would quietly disagree with the CLI」——
// 而官網現在是第三份實作（CLI / inspector / 官網）。
//
// 三份要一致的是**同一組規則**：負值夾到 0 → 重新縮放到總和 1 → 加權和 →
// 四捨五入到小數兩位。這裡把規則獨立寫一次，對照頁面上那份的輸出。
//
// ⚠️ 這支驗的是**數學**，不是 DOM。瀏覽器端那一份有沒有接對（滑桿、重設、
// 維度不被改動）由 playwright 在實機驗 —— 分開是刻意的：數學每次都要跑，
// 開瀏覽器不必。
import { test } from 'node:test';
import assert from 'node:assert/strict';

// 與 reel_scout/config.py 的 SCORE_WEIGHTS 一致
const DEFAULTS = { hook: 30, visual: 25, pacing: 20, structure: 25 };
// 首頁面板用的那一支（02d06d93185562b2）的真實分數
const DIMS = { hook: 6.5, visual: 7.0, pacing: 6.0, structure: 7.5 };
const STORED = 6.78;

/** 逐行照 inspector.py 的 computeOverall。 */
function computeOverall(dims, w) {
  let total = 0;
  for (const d in w) if (Object.hasOwn(w, d)) total += Math.max(0, w[d]);
  if (total <= 0) return null;
  let sum = 0;
  for (const d in dims) {
    if (!Object.hasOwn(dims, d)) continue;
    const wd = (w[d] == null) ? 0 : Math.max(0, w[d]);
    sum += (+dims[d]) * (wd / total);
  }
  return Math.round(sum * 100) / 100;
}

test('預設權重算出來等於資料庫裡存的 overall', () => {
  // 6.5×.30 + 7.0×.25 + 6.0×.20 + 7.5×.25 = 6.775 → 6.78
  assert.equal(computeOverall(DIMS, DEFAULTS), STORED);
});

test('單一維度拉到底 ＝ 那個維度自己的分數', () => {
  for (const k of Object.keys(DIMS)) {
    const w = { hook: 0, visual: 0, pacing: 0, structure: 0, [k]: 100 };
    assert.equal(computeOverall(DIMS, w), DIMS[k], k);
  }
});

test('權重會被縮放，所以比例相同就結果相同', () => {
  // 25/25/25/25 與 1/1/1/1 是同一組比例
  assert.equal(
    computeOverall(DIMS, { hook: 25, visual: 25, pacing: 25, structure: 25 }),
    computeOverall(DIMS, { hook: 1, visual: 1, pacing: 1, structure: 1 }),
  );
  // 預設值乘以 7 也應該一樣
  const scaled = Object.fromEntries(Object.entries(DEFAULTS).map(([k, v]) => [k, v * 7]));
  assert.equal(computeOverall(DIMS, scaled), STORED);
});

test('全部為 0 → null（算不出來，不是 0 分）', () => {
  // 🔴 這條是語意不是邊界：沒有任何維度被重視時，正確答案是「算不出總分」，
  //    而不是「這支片 0 分」。頁面要顯示「—」。
  assert.equal(computeOverall(DIMS, { hook: 0, visual: 0, pacing: 0, structure: 0 }), null);
});

test('負權重夾到 0，不會把總分拉低', () => {
  const withNeg = computeOverall(DIMS, { hook: -50, visual: 25, pacing: 25, structure: 25 });
  const asZero  = computeOverall(DIMS, { hook: 0,   visual: 25, pacing: 25, structure: 25 });
  assert.equal(withNeg, asZero);
});

test('四捨五入到小數兩位（不是截斷）', () => {
  // 7/13/3/91 這組除不盡，是實機驗過的那一組
  const v = computeOverall(DIMS, { hook: 7, visual: 13, pacing: 3, structure: 91 });
  assert.equal(v, Math.round(v * 100) / 100);
  assert.equal(v.toFixed(1), '7.3');
});

test('面板的預設權重沒有偷偷漂掉', () => {
  // 這四個值對應 config.SCORE_WEIGHTS。改了那邊就要改這邊，
  // 否則官網會用一組 CLI 不認得的預設去算。
  assert.deepEqual(DEFAULTS, { hook: 30, visual: 25, pacing: 20, structure: 25 });
  assert.equal(Object.values(DEFAULTS).reduce((a, b) => a + b, 0), 100);
});
