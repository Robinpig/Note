#!/usr/bin/env node
/**
 * 校验 Markdown 文件中的 ```dot 图能否被站点实际使用的 viz.js 1.7.1 渲染。
 *
 * 背景：index.html:270 加载 //unpkg.com/viz.js@1.8.0/viz.js（实际 1.7.1，内含
 * Graphviz 2.40.1），index.html:158 以 `Viz(code, "SVG")` 调用。viz.js 1.x 的
 * 渲染函数**同步返回字符串或抛异常**，没有 status 字段。因此本脚本用 vm 加载真实
 * viz.js 来复现浏览器行为，而不是用 @viz-js/viz v3（API 不同，测不出问题）。
 *
 * 已知坑：Graphviz 2.40 不支持 `subgraph ID [显示标签]` 语法（会报
 * "syntax error near '['"），必须写 `subgraph cluster_xxx { label="..." }`。
 * 该异常会中断整个页面的渲染，导致 README「打不开」。
 *
 * 用法：
 *   node scripts/check_dot.js docs/CS/MQ            # 检查目录
 *   node scripts/check_dot.js docs/CS/MQ/README.md  # 检查单文件
 *   node scripts/check_dot.js docs --verbose        # 逐块打印
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = path.resolve(__dirname, '..');   // 仓库根（脚本在 scripts/ 下）
const VIZ_LOCAL = path.join(require('os').tmpdir(), 'viz.js');
const VIZ_URL = 'https://unpkg.com/viz.js@1.8.0/viz.js';

/** 惰性加载站点同版本 viz.js，返回同步渲染函数 Viz(code, "SVG")。 */
let Viz = null;
function loadViz() {
  if (Viz) return Viz;
  let code;
  if (fs.existsSync(VIZ_LOCAL)) {
    code = fs.readFileSync(VIZ_LOCAL, 'utf8');
  } else {
    // 现场下载到 tmp（无网络时给出可操作的提示）
    const { execSync } = require('child_process');
    try {
      execSync(`curl -sL --max-time 60 "${VIZ_URL}" -o "${VIZ_LOCAL}"`, { stdio: 'pipe' });
    } catch (e) {
      throw new Error(
        '无法获取 viz.js：本地无 ' + VIZ_LOCAL + ' 且下载失败。\n' +
        '请先执行： curl -sL "' + VIZ_URL + '" -o ' + VIZ_LOCAL
      );
    }
    code = fs.readFileSync(VIZ_LOCAL, 'utf8');
  }
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
