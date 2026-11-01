"""Build text index (tw) for OCR position matching -> data/textindex.json"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ast_parser as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', 'data')
PUNCT = re.compile(r'[\s　「」『』（）()、，,。．.…‥・·•！!？?：:；;“”"‘’\'\-—―～~〈〉《》【】\[\]]+')


def norm(s):
    return PUNCT.sub('', s)


def flatten(tw):
    """tw text entry -> (name, text)"""
    name, parts = None, []
    for ent in tw.arr:
        if not isinstance(ent, A.Table):
            continue
        nm = ent.get('name')
        if nm is not None and nm.arr:
            name = nm.arr[-1]
        for x in ent.arr:
            if isinstance(x, str):
                parts.append(x)
    return name, ''.join(parts)


def main():
    lines = []      # [file, block, name, text]
    selects = []    # [file, block, selname, [options]]
    for p in sorted(glob.glob(os.path.join(ROOT, 'script', '*.ast'))):
        f = os.path.basename(p)[:-4]
        d = A.load(p).get('ast')
        if d is None:
            continue
        for b, blk in d.map.items():
            if b == 'label':
                continue
            t = blk.get('text')
            if t is not None and 'tw' in t:
                name, text = flatten(t['tw'])
                if norm(text):
                    lines.append([f, b, name, text])
            s = blk.get('select')
            if s is not None and 'tw' in s:
                nm = next((x.map['name'] for x in blk.arr if x.arr[0] == 'select' and 'name' in x.map), None)
                selects.append([f, b, nm, list(s['tw'].arr)])
    out = {'lines': lines, 'selects': selects}
    with open(os.path.join(ROOT, 'textindex.json'), 'w', encoding='utf-8') as fp:
        json.dump(out, fp, ensure_ascii=False)
    print('lines', len(lines), 'selects', len(selects))


if __name__ == '__main__':
    main()
