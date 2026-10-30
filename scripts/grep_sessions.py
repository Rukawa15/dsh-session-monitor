# -*- coding: utf-8 -*-
r"""在全部本机 DSH 会话存档中按正则搜索内容（只读）。

用法:
  python grep_sessions.py <regex> [--ctx 120]
  python grep_sessions.py "gitlab\.logicalqubit\S+" --ctx 80

对每个命中打印: 会话短ID · 事件序号 · 命中行(截断)。适合找回历史会话里
执行过的命令、URL、报错原文。
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor import find_sessions, load_events


def main():
    ap = argparse.ArgumentParser(description='按正则搜索全部 DSH 会话存档(只读)')
    ap.add_argument('pattern', help='正则表达式(python re 语法)')
    ap.add_argument('--ctx', type=int, default=120, help='命中行截断长度')
    ap.add_argument('--max', type=int, default=50, help='最多显示条数')
    args = ap.parse_args()

    pat = re.compile(args.pattern, re.IGNORECASE)
    shown = 0
    for group, sdir, path in find_sessions():
        try:
            events = load_events(path)
        except Exception:
            continue
        sid = sdir.replace('session-', '')[:8]
        for i, ev in enumerate(events):
            raw = str(ev.get('data', ''))
            if not pat.search(raw):
                continue
            for line in raw.replace('\\r', '').replace('\\n', '\n').splitlines():
                if pat.search(line):
                    print('%s [%d] %s' % (sid, i, line.strip()[:args.ctx]))
                    shown += 1
                    if shown >= args.max:
                        print('…已达 --max 上限')
                        return
    print('---- hits: %d ----' % shown)


if __name__ == '__main__':
    main()
