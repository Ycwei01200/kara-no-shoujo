"""Turn verified decision paths into data/routes.json for the overlay."""
import json
import re
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ast_parser as A  # noqa: E402
import sim  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

AFFECTION = {'100': '史黛拉', '101': '夏目', '102': '佐東步', '103': '時坂紫', '104': '雨宮初音',
             '105': '葉月杏子', '106': '朽木冬子', '107': '水原透子', '108': '四十宮綴子',
             '109': '朱崎寧寧', '110': '月島織姬'}

# Names checked against each ending's last scene and the route's deciding choices.
ENDINGS_FIXED = {   # who dies, read from each ending's last scene; act = window title chapter
    0: 'BAD・act06：玲人、織姬被殺',
    1: 'BAD・act11：紫死亡，玲人殺了高城秋五',
    2: 'BAD・act11：紫死亡（井之頭公園＋等待魚住）',
    3: 'act11：紫獲救，玲人精神崩潰（石神井公園＋等待魚住）',
    4: 'BAD・act17：玲人被殺（去追透子）',
    5: 'BAD・act19：玲人、冬子被殺（指認村瀨直己）',
    6: 'act22：冬子死亡（獨自行動）',
    7: 'act23：冬子獲救、失去雙手（和八木沼一起行動）',
    8: 'act25：兇手心爾找到「殼中少女」（前往倉敷 A）',
    9: 'act25：兇手心爾投湖（前往倉敷 B）',
    10: 'act26：沒能為由記子報仇，和紫回家（扣動扳機）',
    11: '真結局（不扣動扳機）',
    12: '真結局＋冬子後日談（等到冬子回來）',
    13: '真結局＋冬子後日談（去看畫）',
    14: '最終結局：冬子後日談之後（中途選「追踪日下」，不能選「去上野」）',
}


_ACT_STARTS = None


def block_line(W, f, b):
    blk = W.files.get(f, {}).get(b) if b else None
    ln = blk.get('line') if blk is not None else None
    return ln if isinstance(ln, int) else 0


def act_of(W, f, b=None):
    """Act in effect at block b of file f: the last savetitle before it in story order
    (script names sort in story order; inside a file, by line)."""
    global _ACT_STARTS
    if _ACT_STARTS is None:
        _ACT_STARTS = []
        for g, d in W.files.items():
            for bb, blk in d.map.items():
                if bb == 'label':
                    continue
                for x in blk.arr:
                    if x.arr[0] == 'savetitle' and re.fullmatch(r'act\d+', str(x.map.get('text'))):
                        _ACT_STARTS.append(((g, block_line(W, g, bb)), x.map['text']))
        _ACT_STARTS.sort()
    me = (f, block_line(W, f, b))
    best = None
    for pos, a in _ACT_STARTS:
        if pos <= me:
            best = a
    return best


def ending_title(W, n, files):
    if n in ENDINGS_FIXED:
        return ENDINGS_FIXED[n]
    act = None
    for f in files:
        d = W.files.get(f)
        if not d:
            continue
        for b, blk in d.map.items():
            if b == 'label':
                continue
            for x in blk.arr:
                if x.arr[0] == 'savetitle':
                    act = x.map.get('text', act)
    return f'結局 {n:02d}（{act}）' if act else f'結局 {n:02d}'


def trace(W, decs, target):
    """Replay decisions; return [(dec, flags_before, flags_after_until_next)]"""
    pos = W.start_of('00a_0000_0000')
    st = sim.mkstate({}, (), {}, None, {})
    out = []
    k = 0
    enter = False
    seg = []
    while True:
        nxt = None
        vis = []
        for dec, np, ns, ev in sim.successors(W, pos, st, enter_search=enter, visit=vis):
            if ev is not None:
                if ev[0] == 'SEARCH':
                    pos, st = ev[1], ev[2]
                    nxt = 'search'
                    break
                if ev[0] != 'END':
                    raise RuntimeError('unexpected event %r' % (ev[:2],))
                if ev[1] != target:
                    continue
                if out:
                    out[-1][2] = dict(ns[0])
                seg.extend(f for f in vis if not seg or seg[-1] != f)
                out.append(['__end__', seg, None])
                return out
            if k < len(decs) and dec == decs[k]:
                pre = dict(ns[0])
                if dec[0] in ('deduc', 'deduc3'):       # ns already contains the answer's effect
                    old = dict(st[0])
                    keys = [''] if dec[0] == 'deduc' else [sim.HANDWRITING[c] for c in dec[4]]
                    for key in keys:
                        if key in old:
                            pre[key] = old[key]
                        else:
                            pre.pop(key, None)
                if out:
                    out[-1][2] = pre
                seg.extend(f for f in vis if not seg or seg[-1] != f)
                out.append([dec, pre, None, seg])
                seg = []
                nxt = (np, ns)
                break
        if nxt == 'search':
            seg.extend(f for f in vis if not seg or seg[-1] != f)
            enter = True
            continue
        enter = False
        if nxt is None:
            raise RuntimeError('replay mismatch at %d' % k)
        pos, st = nxt
        k += 1


def load_names():
    n = json.load(open(os.path.join(DATA, 'names.json'), encoding='utf-8'))
    sel = A.load(os.path.join(DATA, 'img', 'pc', 'tw', 'game', 'note', 'notesel.ipt'))['note']
    kinds = {k: v for k, v in sel.map.items() if isinstance(k, int)}
    return n, kinds


def ask_blocks(W, f, b, depth=3):
    """Blocks shown just before a deduction opens (its question), via linkback."""
    out = []
    d = W.files[f]
    cur = d.get(b)
    for _ in range(depth):
        prev = cur.get('linkback') if cur is not None else None
        if not prev or prev not in d:
            break
        out.append(prev)
        cur = d.get(prev)
    return out


def describe(dec, names, kinds, W):
    kind = dec[0]
    if kind == 'select':
        _, f, b, nm, k, text = dec
        blk = W.files[f][b]
        opts = list(blk['select']['tw'].arr)
        return {'kind': 'select', 'id': f'sel:{f}:{b}', 'file': f, 'block': b, 'name': nm,
                'choice': k, 'choice_text': text, 'options': opts}
    if kind == 'map':
        _, f, b, nm, no, place = dec
        opts = [names['places'][str(p)] for p in W.maps[nm]]
        return {'kind': 'map', 'id': f'map:{nm}:{no}', 'file': f, 'block': b, 'map': nm, 'visit': no + 1,
                'choice': place, 'choice_text': names['places'][str(place)], 'options': opts}
    if kind == 'deduc':
        _, f, b, no, v = dec
        k = kinds.get(no, 1)
        if v == -1:
            txt = '（答錯）'
        elif k == 1:
            txt = names['person'].get(str(v), f'人物#{v}')
        else:
            txt = names['evidence'].get(str(v), f'證據#{v}')
        right = None
        for x in W.files[f][b].arr:
            if x.arr[0] == 'user' and x.map.get('mode') == 'deduc_chk' and x.map['no'] == v:
                st = W.start_of(f, x.map['label'])
                right = st[1] if st else None
        return {'kind': 'deduc', 'id': f'deduc:{f}:{b}', 'file': f, 'no': no,
                'list': '人物' if k == 1 else '證據', 'choice': v, 'choice_text': txt,
                'wrong_block': b, 'right_block': right, 'ask_blocks': ask_blocks(W, f, b),
                'photo': f'note_photo{v:02d}.png' if k == 1 and v >= 0 else None}
    if kind == 'deduc3':
        _, f, b, no, combo = dec
        return {'kind': 'deduc3', 'id': f'deduc3:{f}:{b}', 'file': f, 'no': no, 'list': '人物',
                'ask_blocks': ask_blocks(W, f, b),
                'choice': list(combo), 'choice_text': '、'.join(names['person'][str(c)] for c in combo),
                'photo': [f'note_photo{c:02d}.png' for c in combo]}
    if kind == 'search':
        _, f, b, inve, k = dec
        base = W.search_base.get(f, f)
        hint = '離開搜查'
        if k == 'Z':
            hint = '再點一次第一個調查點（放大）'
        elif k == 'R':
            hint = '按「返回」離開放大畫面'
        elif k:
            st = W.start_of(base + 's', '%02d' % k)
            hint = f'熱點 {k}'
            if st:
                blk = W.files[st[0]]
                bname = st[1]
                for _ in range(30):
                    t = blk.get(bname)
                    if t is None:
                        break
                    tx = t.get('text')
                    if tx is not None and 'tw' in tx:
                        line = ''.join(x for e in tx['tw'].arr if isinstance(e, A.Table) for x in e.arr if isinstance(x, str))
                        if line.strip():
                            hint = f'會出現「{line.strip()[:30]}」的地方'
                            break
                    bname = t.get('linknext')
        return {'kind': 'search', 'id': f'search:{base}', 'file': f, 'choice': k, 'choice_text': hint,
                'inve': inve, 'block': b}
    raise ValueError(dec)


def effects(before, after):
    out = []
    for k in sorted(set(before) | set(after), key=lambda x: (len(x), x)):
        if k.isdigit() and int(k) >= 111 and before.get(k, 0) != after.get(k, 0):
            out.append(f'路線旗標 f.s{k}: {before.get(k, 0)}→{after.get(k, 0)}')
    for k, nm in AFFECTION.items():
        d = after.get(k, 0) - before.get(k, 0)
        if d:
            out.append(f'{nm}好感 {"+" if d > 0 else ""}{d}')
    return out


IMG = os.path.join(DATA, 'img', 'pc', 'tw')
HINTS = os.path.join(DATA, 'hints')


def inve_table():
    for p in ('system/list_windows.tbl', 'system/table/list_windows.tbl'):
        fp = os.path.join(DATA, p)
        if os.path.exists(fp):
            t = A.load(fp)
            iv = t.get('inve') or next(v.map['inve'] for v in t.values()
                                       if isinstance(v, A.Table) and 'inve' in v.map)
            out = {}
            for k, v in iv.map.items():
                a = v.arr
                out[int(k[2:])] = {'mask': a[2], 'zoom': a[3] if len(a) > 3 and isinstance(a[3], str) else None}
            return out
    return {}


_CENTER = {}


def hotspot_center(mask, k):
    key = (mask, k)
    if key not in _CENTER:
        from PIL import Image
        p = os.path.join(IMG, 'game', 'inve', 'msk', f'{mask}_{k:02d}.png')
        c = None
        if os.path.exists(p):
            a = Image.open(p).getchannel('A')
            bb = a.getbbox()
            if bb:
                c = ((bb[0] + bb[2]) / 2 / a.width, (bb[1] + bb[3]) / 2 / a.height)
        _CENTER[key] = c
    return _CENTER[key]


def search_thumb(inv, clicks):
    """Picture of the search scene(s) with the clicks numbered in order. -> file name or None."""
    from PIL import Image, ImageDraw, ImageFont
    if not inv:
        return None
    W_, H_ = 320, 180
    views = [[inv['mask'], []]]
    n = 0
    for k in clicks:
        if k == 'Z':
            n += 1
            views[-1][1].append((n, 1, '放大'))
            views.append([inv['zoom'], []])
        elif k == 'R':
            views.append([inv['mask'], []])
        elif k == 0:
            continue
        else:
            n += 1
            views[-1][1].append((n, k, ''))
    views = [v for v in views if v[1]]
    if not views:
        return None
    try:
        font = ImageFont.truetype('msjhbd.ttc', 15)
    except Exception:
        font = ImageFont.load_default()
    out = Image.new('RGB', (W_ * len(views) + 6 * (len(views) - 1), H_), (20, 20, 20))
    for vi, (name, marks) in enumerate(views):
        bgp = [os.path.join(IMG, 'user', 'search', name + '.png'), os.path.join(IMG, 'game', 'inve', name + '.png')]
        bgp = next((p for p in bgp if os.path.exists(p)), None)
        im = Image.open(bgp).convert('RGB').resize((W_, H_)) if bgp else Image.new('RGB', (W_, H_), (60, 60, 60))
        d = ImageDraw.Draw(im)
        spots = {}                                   # same hotspot clicked again -> one label '5·7'
        for num, k, _ in marks:
            spots.setdefault(k, []).append(num)
        for k, nums in spots.items():
            c = hotspot_center(name, k)
            if not c:
                continue
            x, y = c[0] * W_, c[1] * H_
            label = '·'.join(map(str, nums))
            w = max(20, d.textlength(label, font=font) + 10)
            d.rounded_rectangle((x - w / 2, y - 10, x + w / 2, y + 10), 10, fill=(220, 30, 30),
                                outline=(255, 255, 255), width=2)
            d.text((x, y), label, fill=(255, 255, 255), font=font, anchor='mm')
        out.paste(im, (vi * (W_ + 6), 0))
    os.makedirs(HINTS, exist_ok=True)
    import hashlib
    key = json.dumps([inv['mask'], inv['zoom'], clicks])
    fn = f"search_{inv['mask']}_{hashlib.md5(key.encode()).hexdigest()[:10]}.png"
    out.save(os.path.join(HINTS, fn))
    return fn


def all_deductions(W, names, kinds):
    """Every deduction in the game with its accepted answers (a route may skip some)."""
    out = []
    for f, d in W.files.items():
        for b, blk in d.map.items():
            if b == 'label':
                continue
            cmds = blk.arr
            for j, x in enumerate(cmds):
                if not (x.arr[0] == 'user' and x.map.get('mode') == 'deductive'):
                    continue
                no = x.map.get('no')
                k = kinds.get(no, 1)
                ans = []
                for y in cmds[j + 1:]:
                    if y.arr[0] == 'user' and y.map.get('mode') == 'deduc_chk':
                        v = y.map['no']
                        nm = names['person' if k == 1 else 'evidence'].get(str(v), f'#{v}')
                        ans.append({'id': v, 'text': nm, 'label': y.map.get('label')})
                if ans:
                    out.append({'file': f, 'block': b, 'no': no, 'list': '人物' if k == 1 else '證據',
                                'ask_blocks': ask_blocks(W, f, b), 'answers': ans})
    return out


def main():
    W = sim.World()
    INV = inve_table()
    names, kinds = load_names()
    routes = pickle.load(open(os.path.join(DATA, 'routes_verified.pkl'), 'rb'))
    out = {'endings': {}, 'points': {}, 'deductions': all_deductions(W, names, kinds)}
    for n, decs in sorted(routes.items()):
        tr = trace(W, decs, int(n))
        tail = tr.pop()[1]
        steps = []
        for dec, before, after, seg in tr:
            d = describe(dec, names, kinds, W)
            d['files_before'] = seg
            d['effects'] = effects(before, after or before)
            # merge consecutive search clicks into one step
            if d['kind'] == 'search' and steps and steps[-1]['kind'] == 'search' and steps[-1]['id'] == d['id']:
                steps[-1]['clicks'].append(d['choice'])
                steps[-1]['click_texts'].append(d['choice_text'])
                steps[-1]['effects'] += d['effects']
                steps[-1]['files_before'] += [x for x in seg if x not in steps[-1]['files_before']]
                continue
            if d['kind'] == 'search':
                d['clicks'] = [d['choice']]
                d['click_texts'] = [d['choice_text']]
            steps.append(d)
        for s_ in steps:
            if s_['kind'] == 'search':
                s_['thumb'] = search_thumb(INV.get(s_.pop('inve', None)), s_['clicks'])
        occ = {}
        for s_ in steps:
            occ[s_['id']] = occ.get(s_['id'], 0) + 1
            s_['occ'] = occ[s_['id']]
            s_['pid'] = f"{s_['id']}#{s_['occ']}"
        # chapter shown in the game's window title -> first step index inside it.
        # Script names sort in story order, so a decision belongs to the last act whose
        # first file sorts at or before the decision's file.
        acts = {}
        for i, s_ in enumerate(steps):
            a = act_of(W, s_['file'], s_.get('block') or s_.get('wrong_block'))
            if a:
                acts.setdefault(a, i)
        for f in tail:
            a = act_of(W, f)
            if a:
                acts.setdefault(a, len(steps))
        allfiles = [f for s_ in steps for f in s_['files_before']] + tail
        out['endings'][n] = {'title': ending_title(W, n, allfiles), 'steps': steps, 'files_after': tail, 'acts': acts,
                             'affection': {AFFECTION[k]: v for k, v in tr[-1][2].items() if k in AFFECTION}
                             if tr[-1][2] else {}}
        for s in steps:
            if s['kind'] == 'search':
                continue
            p = out['points'].setdefault(s['pid'], {})
            p.setdefault(str(s['choice']), {'text': s['choice_text'], 'endings': []})['endings'].append(n)
    json.dump(out, open(os.path.join(DATA, 'routes.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for n, e in out['endings'].items():
        kinds_c = {}
        for s in e['steps']:
            kinds_c[s['kind']] = kinds_c.get(s['kind'], 0) + 1
        print(n, e['title'], kinds_c)


if __name__ == '__main__':
    main()
