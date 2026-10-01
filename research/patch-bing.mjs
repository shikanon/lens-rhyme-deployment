import { readFileSync, writeFileSync } from 'node:fs';
// Upstream fixes Bing to the China endpoint and Chinese results. This service researches English content.
const path = 'src/engines/bing/bing.ts';
let source = readFileSync(path, 'utf8');
for (const [before, after] of [
  ["const BING_BASE_URL = 'https://cn.bing.com/search';", "const BING_BASE_URL = 'https://www.bing.com/search';"],
  ["url.searchParams.set('setlang', 'zh-CN');", "url.searchParams.set('setlang', 'en-US');\n    url.searchParams.set('mkt', 'en-US');"],
  ["url.searchParams.set('ensearch', '0');", "url.searchParams.set('ensearch', '1');"],
]) {
  if (!source.includes(before)) throw new Error('Pinned Bing patch no longer matches upstream');
  source = source.replace(before, after);
}
writeFileSync(path, source);
