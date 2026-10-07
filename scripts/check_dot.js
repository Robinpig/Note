#!/usr/bin/env node
/**
 * 校验 Markdown 文件中的 ```dot 图能否被站点实际使用的 viz.js 渲染。
 *
 * 背景：index.html 以 `<script src="//cdn.jsdelivr.net/npm/viz.js@1.8.0/viz.js">`
 * 加载 viz.js（实际 1.7.1，内含 Graphviz 2.40.1），并在渲染钩子里以
 * `Viz(code, "SVG")` 同步调用。viz.js 1.x 的渲染函数**同步返回字符串或抛异常**，
 * 没有 status 字段。因此本脚本用 vm 加载真实 viz.js 来复现浏览器行为，而不是用
 * @viz-js/viz v3（API 不同，测不出问题）。
 *
 * viz.js 的来源按以下顺序解析（站点依赖必须全部挂 jsdelivr，见 AGENTS.md）：
 *   1. 环境变量 VIZ_JS —— 离线机器上手工放一份本地文件的路径；
 *   2. 从 index.html 里现读 `<script src=...viz.js...>`，保证与站点实际加载的
 *      是同一份资源（改 CDN 不必再回来同步这个脚本）；
 *   3. 内置默认地址：jsdelivr → unpkg → npmmirror（国内直连前两个常超时，
 *      留一个可用的镜像作最后退路；版本号一致，仍是 viz.js@1.8.0 里的 1.7.1 构建）。
 *   下载成功还会校验首行不是 `<!DOCTYPE html>`——CDN 被拦截时可能返回 200 + HTML
 *   错误页，只看状态码会误判成"拿到了源码"。
 *
 * 已知坑：Graphviz 2.40 不支持 `subgraph ID [显示标签]` 语法（会报
 * "syntax error near '['"），必须写 `subgraph cluster_xxx { label="..." }`。
 * 该异常会中断整个页面的渲染，导致 README「打不开」。
 *
 * 用法：
 *   node scripts/check_dot.js docs/CS/MQ            # 检查目录
 *   node scripts/check_dot.js docs/CS/MQ/README.md  # 检查单文件
 *   node scripts/check_dot.js docs --verbose        # 逐块打印
 *   VIZ_JS=/path/to/viz.js node scripts/check_dot.js docs   # 离线：用本地副本
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = path.resolve(__dirname, '..');   // 仓库根（脚本在 scripts/ 下）
const VIZ_LOCAL = process.env.VIZ_JS || path.join(require('os').tmpdir(), 'viz.js');
const VIZ_FALLBACK_URLS = [
  'https://cdn.jsdelivr.net/npm/viz.js@1.8.0/viz.js',
  'https://unpkg.com/viz.js@1.8.0/viz.js',
  // 国内机器上前两个常连不上，npmmirror 的 files 路径可直接拿到原始 js
  'https://registry.npmmirror.com/viz.js/1.8.0/files/viz.js',
];

/** 从 index.html 取站点实际加载的 viz.js 地址，作为下载首选源。 */
function vizUrls() {
  const urls = [];
  try {
    const html = fs.readFileSync(path.join(REPO, 'index.html'), 'utf8');
    const m = html.match(/<script[^>]+src=["']([^"']*viz\.js[^"']*)["']/i);
    if (m) urls.push(m[1].startsWith('//') ? 'https:' + m[1] : m[1]);
  } catch (e) { /* index.html 读不到就用回退地址 */ }
  return urls.concat(VIZ_FALLBACK_URLS.filter((u) => !urls.includes(u)));
}

/** 取 viz.js 源码：优先本地缓存 / VIZ_JS，其次按地址清单下载。 */
function readVizCode() {
  if (fs.existsSync(VIZ_LOCAL)) {
    const cached = fs.readFileSync(VIZ_LOCAL, 'utf8');
    // 缓存里可能是 HTML 错误页，或 curl 失败时留下的空文件（真实体积约 2.4MB）
    if (!/^\s*<!DOCTYPE html>/i.test(cached) && cached.length > 100000) return cached;
    fs.unlinkSync(VIZ_LOCAL);   // 只清理本脚本自己写的这份缓存，重下
  }
  const { execSync } = require('child_process');
  const tried = [];
  for (const url of vizUrls()) {
    tried.push(url);
    try {
      execSync(`curl -sL --fail --connect-timeout 8 --max-time 30 "${url}" -o "${VIZ_LOCAL}"`, { stdio: 'pipe' });
    } catch (e) {
      continue;   // 网络不通 / 404，换下一个源
    }
    if (!fs.existsSync(VIZ_LOCAL)) continue;
    const code = fs.readFileSync(VIZ_LOCAL, 'utf8');
    if (/^\s*<!DOCTYPE html>/i.test(code) || code.length < 100000) {
      fs.unlinkSync(VIZ_LOCAL);
      continue;   // 200 但内容是 HTML 错误页 / 空文件，不算拿到源码
    }
    return code;
  }
  throw new Error(
    '无法获取 viz.js：本地无 ' + VIZ_LOCAL + ' 且下载失败。\n' +
    '已尝试: ' + tried.join(' , ') + '\n' +
    '离线机器请手工下载一份后设 VIZ_JS=<路径>，或直接执行：\n' +
    '  curl -sL "' + tried[0] + '" -o ' + VIZ_LOCAL
  );
}

/** 惰性加载站点同版本 viz.js，返回同步渲染函数 Viz(code, "SVG")。 */
let Viz = null;
function loadViz() {
  if (Viz) return Viz;
  const code = readVizCode();
  const sandbox = { console, TextDecoder, TextEncoder, WebAssembly, ArrayBuffer, Uint8Array };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { timeout: 60000 });
  if (typeof sandbox.Viz !== 'function') throw new Error('viz.js 加载成功但未暴露 Viz 函数');
  Viz = sandbox.Viz;
  return Viz;
}

/** 收集目标下所有 .md（跳过 img/ 与 node_modules）。 */
function collect(target) {
  const st = fs.statSync(target);
  if (st.isFile()) return [target];
  const out = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'img' || e.name === 'node_modules' || e.name.startsWith('.')) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith('.md')) out.push(p);
    }
  })(target);
  return out;
}

function main() {
  const args = process.argv.slice(2);
  const verbose = args.includes('--verbose');
  const targets = args.filter((a) => !a.startsWith('--'));
  if (targets.length === 0) targets.push(path.join(REPO, 'docs'));

  const viz = loadViz();
  let fileFail = 0;
  let blockFail = 0;
  let blockOk = 0;
  const failures = [];

  for (const t of targets) {
    const abs = path.isAbsolute(t) ? t : path.join(REPO, t);
    let files = [];
    try {
      files = collect(abs);
    } catch (e) {
      console.error('跳过（不存在）: ' + t);
      continue;
    }
    for (const f of files) {
      const md = fs.readFileSync(f, 'utf8');
      const blocks = [...md.matchAll(/```dot\n([\s\S]*?)```/g)];
      if (blocks.length === 0) continue;
      let bad = 0;
      blocks.forEach((m, i) => {
        const src = m[1];
        // 跳过脚本/HTML 里的 fenced dot（本工具只校验笔记正文中的图）
        try {
          const svg = viz(src, 'SVG');
          blockOk++;
          if (verbose) console.log('  OK   ' + path.relative(REPO, f) + ' #' + i + ' len=' + svg.length);
        } catch (e) {
          bad++;
          blockFail++;
          const firstLine = String(e.message).split('\n')[0];
          failures.push({ file: path.relative(REPO, f), idx: i, msg: firstLine, src: src.split('\n') });
        }
      });
      if (bad > 0) fileFail++;
    }
  }

  if (verbose) console.log('');
  if (failures.length) {
    console.log('dot 图渲染失败 ' + blockFail + ' 处（涉及 ' + fileFail + ' 个文件）：\n');
    for (const f of failures) {
      console.log('  ✗ ' + f.file + ' 第 ' + (f.idx + 1) + ' 个 dot 块');
      console.log('    错误: ' + f.msg);
      const badLine = f.src.find((l) => /\[[^\]]*\]\s*;?\s*$/.test(l.trim()) && l.includes('subgraph')) || f.src.find(l => l.includes('subgraph'));
      if (badLine) console.log('    可疑行: ' + badLine.trim());
      console.log('');
    }
    console.log('修复：subgraph 不能带显示标签。Graphviz 2.40 需写成');
    console.log('      subgraph cluster_xxx {');
    console.log('          label="显示名";');
    console.log('          ...');
    console.log('      }');
  }
  console.log(
    'checked ' + blockOk + ' ok, ' + blockFail + ' failed' +
    (blockFail ? '（退出码 1）' : '（全部通过）')
  );
  process.exit(blockFail ? 1 : 0);
}

main();
