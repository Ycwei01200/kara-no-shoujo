"""Minimal Lua-table parser for Artemis .ast / .ipt files."""
import re

_tok = re.compile(r'''
    (?P<ws>\s+|--\[\[.*?\]\]|--[^\n]*)
  | (?P<lstr>\[(?P<eq>=*)\[.*?\](?P=eq)\])
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<num>-?0x[0-9a-fA-F]+|-?\d+(?:\.\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<p>[{}\[\]=,;])
''', re.S | re.X)

_esc = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"', "'": "'"}


def _unescape(s):
    return re.sub(r'\\(.)', lambda m: _esc.get(m.group(1), m.group(1)), s)


def tokenize(src):
    pos, out = 0, []
    while pos < len(src):
        m = _tok.match(src, pos)
        if not m:
            raise SyntaxError(f'bad token at {pos}: {src[pos:pos+30]!r}')
        pos = m.end()
        k = m.lastgroup
        if k == 'ws':
            continue
        v = m.group(k)
        if k == 'lstr':
            n = len(m.group('eq'))
            v = v[2 + n:-(2 + n)]
            if v.startswith('\n'):
                v = v[1:]
            out.append(('s', v))
        elif k == 'str':
            out.append(('s', _unescape(v[1:-1])))
        elif k == 'num':
            out.append(('n', int(v, 0) if re.fullmatch(r'-?(0x)?[0-9a-fA-F]+', v) and '.' not in v else float(v)))
        elif k == 'name':
            out.append(('id', v))
        else:
            out.append(('p', v))
    return out


class Table:
    __slots__ = ('arr', 'map')

    def __init__(self):
        self.arr, self.map = [], {}

    def get(self, k, d=None):
        return self.map.get(k, d)

    def __getitem__(self, k):
        if isinstance(k, int) and k not in self.map:
            return self.arr[k]
        return self.map[k]

    def __contains__(self, k):
        return k in self.map

    def __repr__(self):
        return f'T({self.arr!r}, {self.map!r})'


def _value(t, i):
    k, v = t[i]
    if k == 'p' and v == '{':
        return _table(t, i + 1)
    if k == 'id':
        return {'true': True, 'false': False, 'nil': None}.get(v, v), i + 1
    return v, i + 1


def _table(t, i):
    tb = Table()
    while True:
        k, v = t[i]
        if k == 'p' and v == '}':
            return tb, i + 1
        if k == 'p' and v in ',;':
            i += 1
            continue
        if k == 'p' and v == '[':
            key, i = _value(t, i + 1)
            assert t[i] == ('p', ']'), t[i]
            assert t[i + 1] == ('p', '='), t[i + 1]
            val, i = _value(t, i + 2)
            tb.map[key] = val
        elif k == 'id' and t[i + 1] == ('p', '='):
            val, i = _value(t, i + 2)
            tb.map[v] = val
        else:
            val, i = _value(t, i)
            tb.arr.append(val)


def parse(src):
    """Parse top-level `name = value` assignments."""
    t = tokenize(src)
    i, res = 0, {}
    while i < len(t):
        k, v = t[i]
        assert k == 'id' and t[i + 1] == ('p', '='), (t[i], t[i + 1])
        val, i = _value(t, i + 2)
        res[v] = val
    return res


def load(path):
    with open(path, encoding='utf-8-sig') as f:
        return parse(f.read())
