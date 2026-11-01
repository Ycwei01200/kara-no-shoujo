"""Drive the pet with fake OCR frames and screenshot each state (no game needed).
usage: python -X utf8 test_pet.py <outdir>"""
import ctypes
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pet  # noqa: E402

OUT = sys.argv[1]
pet.SETTINGS = os.path.join(OUT, 'pet_test_settings.json')
pet.Watcher.start = lambda self: None     # fake frames only, no real OCR
ctypes.windll.shcore.SetProcessDpiAwareness(2)
root = tk.Tk()
p = pet.Pet(root)
p.watcher.paused = True
p.tr.set_ending('11', 0)
RECT = (0, 0, 1280, 720)
steps = p.tr.steps
results = []


def shot(name):
    import mss
    from PIL import Image
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    s = mss.mss().grab({'left': x, 'top': y, 'width': w, 'height': h})
    Image.frombytes('RGB', s.size, s.bgra, 'raw', 'BGRX').save(os.path.join(OUT, name))


def frame(lines):
    p.on_ocr(RECT, [(t, (100, 600 if dlg else 200, 600, 640)) for t, dlg in lines])


# first select on the route
si = next(i for i, s in enumerate(steps) if s['kind'] == 'select')
sel = steps[si]


def t1():
    frame([(n, False) for n in steps[0]['options']])
    results.append(('map hint', p.b_main.cget('text'), p.tr.ptr))
    shot('pet_map.png')
    frame([('「嗯……應該只是貧血而已吧……」', True)])          # leave map screen
    results.append(('after map ptr', p.tr.ptr))
    p.tr.ptr = si - 1
    root.after(300, t2)


def t2():
    frame([(o, False) for o in sel['options']])
    results.append(('select hint', p.b_main.cget('text'), p.b_sub.cget('text'), p.tr.ptr))
    shot('pet_select.png')
    frame([('玲人', True)])
    results.append(('after select ptr', p.tr.ptr, 'expected', si + 1))
    root.after(1800, t3)


def t3():
    results.append(('bubble hidden', not p.bubble.winfo_ismapped()))
    shot('pet_idle.png')
    for r in results:
        print(r)
    p.quit()


root.after(800, t1)
root.mainloop()
