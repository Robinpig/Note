"""docsify 站内链接 / 锚点 / 乱码校验。

用法:
    python3 validate_links.py file1.md [file2.md ...]
    python3 validate_links.py --dir docs/CS/Framework/Spring

检查项:
    DEAD       - 站内链接指向的 .md 文件不存在（致命）
    BAD ANCHOR - ?id=slug 在目标文件的标题里找不到（致命）
    RELATIVE   - 使用了相对链接(规范要求 /docs/ 绝对路径)（致命）
    CYRILLIC   - 中文文本中出现西里尔字母（致命）
    GARBLED    - 中英夹杂乱码（低置信度告警，默认不阻断，除非 --strict）

选项:
    --verbose  逐行打印 GARBLED 告警（默认只汇总计数）
    --strict   将 GARBLED 也视为致命问题（用于要求零乱码的目录）
"""

import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（脚本在 scripts/ 下）

MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*$', re.M)
GARBLED_RE = re.compile(r'[\u4e00-\u9fff][A-Za-z\u0400-\u04ff]{1,12}[\u4e00-\u9fff]')
CYRILLIC_RE = re.compile(r'[\u0400-\u04ff]')


def slugify(text: str) -> str:
    s = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    s = re.sub(r'[A-Z]+', lambda m: m.group(0).lower(), s)
    s = re.sub(r'[\u2000-\u206f\u2e00-\u2e7f\\\'!"#$%&()*+,./:;<=>?@\[\]^`{|}~]', '', s)
    s = re.sub(r'\s', '-', s)
    if re.match(r'^\d', s):
        s = '_' + s
    return s


def anchors_of(path: str):
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return None
    seen, out = {}, set()
    for level, title in HEADING_RE.findall(text):
        s = slugify(title)
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else '%s-%d' % (s, n))
    return out


def check(path: str):
    problems = []

    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')

    cache = {}
    in_fence = False
    for lineno, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # 代码块内的中英混排与示例代码链接不计入校验
        for m in GARBLED_RE.finditer(line):
            problems.append('GARBLED   %s:%d  %s' % (path, lineno, m.group(0)))
        for m in CYRILLIC_RE.finditer(line):
            problems.append('CYRILLIC  %s:%d  %s' % (path, lineno, m.group(0)))

        for text, target in MD_LINK_RE.findall(line):
            if target.startswith(('http://', 'https://', 'mailto:', '#', '?id=')):
                continue
            if target.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                continue  # 配图用相对路径是本站惯例
            if not target.startswith('/docs/'):
                problems.append('RELATIVE  %s:%d  %s' % (path, lineno, target))
                continue

            url = target.split('?')[0]
            anchor = ''
            if '?id=' in target:
                anchor = urllib.parse.unquote(target.split('?id=')[1].split('&')[0])

            fs_path = os.path.join(ROOT, urllib.parse.unquote(url.lstrip('/')))
            if not os.path.exists(fs_path):
                problems.append('DEAD      %s:%d  %s' % (path, lineno, url))
                continue
            if not anchor:
                continue
            if fs_path not in cache:
                cache[fs_path] = anchors_of(fs_path) or set()
            if anchor not in cache[fs_path]:
                problems.append('BAD ANCHOR %s:%d  %s -> %s'
                                % (path, lineno, target, anchor))
    return problems


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, _, files in os.walk(p):
                out += [os.path.join(dirpath, f) for f in files if f.endswith('.md')]
        else:
            out.append(p)
    return sorted(out)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    verbose = '--verbose' in args
    strict = '--strict' in args
    args = [a for a in args if a not in ('--verbose', '--strict')]
    paths = collect(args)

    fatal_total = 0
    garbled_total = 0
    for p in paths:
        for line in check(p):
            kind = line.split()[0]
            if kind == 'GARBLED':
                garbled_total += 1
                if verbose or strict:
                    print(line.replace(ROOT + '/', ''))
            else:
                fatal_total += 1
                print(line.replace(ROOT + '/', ''))

    print('\nchecked %d files, %d fatal, %d garbled(warn)'
          % (len(paths), fatal_total, garbled_total))
    return 1 if (fatal_total or (strict and garbled_total)) else 0


if __name__ == '__main__':
    sys.exit(main())
