"""Turn verified decision paths into data/routes.json for the overlay."""
import json
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

# 11-14 verified from 19a_0418_0320end.ast (ep01 / sel68 stay・go / 09c -> 99a); 0-10 named by act
ENDINGS_FIXED = {
    11: '真結局（一般）', 12: '真結局＋冬子後日談（等她回來）', 13: '真結局＋冬子後日談（去看畫）',
    14: '最終結局（冬子後日談後，f.s132==0）',
}


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
        return {'kind': 'map', 'id': f'map:{nm}:{no}', 'file': f, 'map': nm, 'visit': no + 1,
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
                'wrong_block': b, 'right_block': right,
                'photo': f'note_photo{v:02d}.png' if k == 1 and v >= 0 else None}
    if kind == 'deduc3':
        _, f, b, no, combo = dec
        return {'kind': 'deduc3', 'id': f'deduc3:{f}:{b}', 'file': f, 'no': no, 'list': '人物',
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
        return {'kind': 'search', 'id': f'search:{base}', 'file': f, 'choice': k, 'choice_text': hint}
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


def main():
    W = sim.World()
    names, kinds = load_names()
    routes = pickle.load(open(os.path.join(DATA, 'routes_verified.pkl'), 'rb'))
    out = {'endings': {}, 'points': {}}
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
        occ = {}
        for s_ in steps:
            occ[s_['id']] = occ.get(s_['id'], 0) + 1
            s_['occ'] = occ[s_['id']]
            s_['pid'] = f"{s_['id']}#{s_['occ']}"
        allfiles = [f for s_ in steps for f in s_['files_before']] + tail
        out['endings'][n] = {'title': ending_title(W, n, allfiles), 'steps': steps, 'files_after': tail,
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
