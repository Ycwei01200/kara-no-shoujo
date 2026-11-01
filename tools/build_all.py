"""Rebuild everything under data/ from the installed game.

usage: python -X utf8 tools/build_all.py ["D:\\Steam\\steamapps\\common\\The Shell Part I"]
Takes about 5 minutes (route search is the slow part).
"""
import fnmatch
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
sys.path.insert(0, HERE)
import pf8  # noqa: E402

GAME = sys.argv[1] if len(sys.argv) > 1 else r'D:\Steam\steamapps\common\The Shell Part I'
# Artemis loads the base archive first, numbered patches override it in order
ARCHIVES = ['TheShell.pfs', 'TheShell.pfs.000', 'TheShell.pfs.040', 'TheShell.pfs.060', 'TheShell.pfs.065']
WANT = ['script\\*.ast', 'system\\*.lua', 'system\\*.tbl', 'pc\\tw\\*', 'ui\\game\\note\\icon\\*']


def extract():
    for a in ARCHIVES:
        p = os.path.join(GAME, a)
        if not os.path.exists(p):
            print('skip (missing)', a)
            continue
        f, key, ents = pf8.index(p)
        n = 0
        for name, off, size in ents:
            low = name.lower()
            if not any(fnmatch.fnmatchcase(low, w) for w in WANT):
                continue
            rel = name.replace('\\', '/')
            if rel.startswith('script/'):
                dst = os.path.join(DATA, 'script', os.path.basename(rel))
            elif rel.startswith('system/'):
                dst = os.path.join(DATA, rel)
            elif rel.startswith('ui/game/note/icon/'):
                dst = os.path.join(DATA, 'img', 'pc', 'tw', 'game', 'note', 'icon', os.path.basename(rel))
            else:
                dst = os.path.join(DATA, 'img', rel)
            f.seek(off)
            d = bytearray(f.read(size))
            if key:
                for i in range(len(d)):
                    d[i] ^= key[i % 20]
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as out:
                out.write(d)
            n += 1
        print(f'{a}: {n} files')
    tbl = os.path.join(DATA, 'system', 'table', 'list_windows.tbl')
    if os.path.exists(tbl):
        shutil.copy(tbl, os.path.join(DATA, 'system', 'list_windows.tbl'))


def run(script, *args):
    print('==>', script, *args, flush=True)
    subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, script), *args], check=True)


def main():
    if not os.path.isdir(GAME):
        sys.exit(f'找不到遊戲目錄：{GAME}')
    extract()
    run('build_index.py')
    run('fix_names.py')
    run('run_concrete.py')
    run('run_max.py', '106')
    run('replay.py')
    run('build_routes.py')
    print('完成：data/routes.json')


if __name__ == '__main__':
    main()
