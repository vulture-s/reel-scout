// @ts-check
import { defineConfig } from 'astro/config';
import { rewriteDocLinks } from './src/lib/rewrite-doc-links.mjs';

// GitHub Pages project site: https://vulture-s.github.io/reel-scout/
//
// `format: 'file'` (so pages end in .html) matches the arkiv site rather than
// being required here — reel-scout has no previously published URLs to keep.
// The reason is cross-site consistency: the two tools are linked from the same
// posts and the same course material, and a reader who learns one link shape
// should not have to learn a second.
export default defineConfig({
  site: 'https://vulture-s.github.io',
  base: '/reel-scout',
  build: { format: 'file' },
  // Off on purpose, same finding as the arkiv site: the compressor drops the
  // whitespace between inline elements, so "English ｜ 繁體中文" renders joined.
  compressHTML: false,
  markdown: { rehypePlugins: [rewriteDocLinks] },
});
