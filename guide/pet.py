"""殼之少女 攻略桌寵：平常只是一個小頭像，偵測到選項/地圖/推理畫面時才彈出提示。"""
import json
import os
import queue
import sys
import tkinter as tk
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import PHOTO, GuideData, Tracker, Watcher, default_ending, hint_text  # noqa: E402

SETTINGS = os.path.join(HERE, 'pet_settings.json')
KEY = '#010203'            # transparent colour key
BUBBLE, BFG, DIM, ACC, WARN, GREY = '#fffaf0', '#2b2b2b', '#6b6b6b', '#3a7bd5', '#e07b00', '#9a9a9a'
F_BIG = ('Microsoft JhengHei UI', 13, 'bold')
F_SM = ('Microsoft JhengHei UI', 9)
ICON = 64
LINGER_MS = 1500           # keep bubble shortly after the screen disappears
EXCL_W, EXCL_H = 380, 300  # fixed area (left/up of the anchor) never read by OCR


class Pet:
    def __init__(self, root):
        self.root = root
        self.gd = GuideData()
        self.cfg = self.load()
        ending = default_ending(self.gd, self.cfg.get('ending', '11'))
        self.tr = Tracker(self.gd, ending, self.cfg.get('ptr', {}).get(ending, 0))
        self.q = queue.Queue()
        self.watcher = Watcher(self.q)
        self.active = None          # (kind, step index) currently hinted
        self.hide_job = None
        self.photos = []
        self.problem = None         # last OCR status/error text

        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.configure(bg=KEY)
        root.wm_attributes('-transparentcolor', KEY)

        self.bubble = tk.Frame(root, bg=BUBBLE, highlightbackground='#c9c2b5', highlightthickness=1)
        self.b_main = tk.Label(self.bubble, bg=BUBBLE, fg=BFG, font=F_BIG, justify='left', wraplength=320)
        self.b_main.pack(anchor='w', padx=10, pady=(8, 0))
        self.b_photo = tk.Frame(self.bubble, bg=BUBBLE)
        self.b_photo.pack(anchor='w', padx=10)
        self.b_sub = tk.Label(self.bubble, bg=BUBBLE, fg=DIM, font=F_SM, justify='left', wraplength=320)
        self.b_sub.pack(anchor='w', padx=10, pady=(2, 8))

        self.icon = tk.Canvas(root, width=ICON + 8, height=ICON + 8, bg=KEY, highlightthickness=0)
        self.icon.pack(side='bottom', anchor='e')
        self.draw_icon()

        for w in (self.icon, self.bubble, self.b_main, self.b_sub):
            w.bind('<ButtonPress-1>', self.drag_start)
            w.bind('<B1-Motion>', self.drag_move)
            w.bind('<ButtonRelease-1>', self.drag_end)
            w.bind('<Button-3>', self.menu)
        self.icon.bind('<Enter>', lambda e: self.peek(True))
        self.icon.bind('<Leave>', lambda e: self.peek(False))

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.ax, self.ay = self.cfg.get('anchor', (sw - 40, sh - 120))   # bottom-right of the icon
        vx, vy = root.winfo_vrootx(), root.winfo_vrooty()                 # monitor may be gone
        vw, vh = root.winfo_vrootwidth() or sw, root.winfo_vrootheight() or sh
        if not (vx + ICON <= self.ax <= vx + vw and vy + ICON <= self.ay <= vy + vh):
            self.ax, self.ay = sw - 40, sh - 120
        self.place()
        self.watcher.start()
        root.after(200, self.poll)

    # ---------------- persistence
    def load(self):
        try:
            return json.load(open(SETTINGS, encoding='utf-8'))
        except Exception:
            return {}

    def save(self):
        self.cfg['ending'] = self.tr.ending
        self.cfg.setdefault('ptr', {})[self.tr.ending] = self.tr.ptr
        self.cfg['anchor'] = (self.ax, self.ay)
        try:
            json.dump(self.cfg, open(SETTINGS, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass

    # ---------------- drawing
    def ring_color(self):
        if self.watcher.paused or self.problem:
            return GREY
        return WARN if self.tr.offroute else ACC

    def draw_icon(self):
        c = self.icon
        c.delete('all')
        c.create_oval(2, 2, ICON + 6, ICON + 6, fill=BUBBLE, outline=self.ring_color(), width=3)
        try:
            from PIL import Image, ImageDraw, ImageTk
            im = Image.open(os.path.join(PHOTO, 'note_photo06.png')).convert('RGBA')
            side = min(im.size)
            im = im.crop(((im.width - side) // 2, 0, (im.width + side) // 2, side)).resize((ICON - 4, ICON - 4))
            mask = Image.new('L', im.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, im.width - 1, im.height - 1), fill=255)
            bg = Image.new('RGBA', im.size, (1, 2, 3, 0))
            bg.paste(im, (0, 0), mask)
            self.icon_img = ImageTk.PhotoImage(bg)
            c.create_image(ICON // 2 + 4, ICON // 2 + 4, image=self.icon_img)
        except Exception:
            c.create_text(ICON // 2 + 4, ICON // 2 + 4, text='攻略', font=F_BIG, fill=BFG)

    def place(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.geometry(f'+{self.ax - w}+{self.ay - h}')
        # fixed footprint (largest bubble), so the blanked area never changes size
        self.watcher.exclude = (self.ax - EXCL_W, self.ay - EXCL_H, EXCL_W, EXCL_H)

    def show(self, main, sub='', photos=None, color=BFG):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        self.b_main.configure(text=main, fg=color)
        self.b_sub.configure(text=sub)
        for w in self.b_photo.winfo_children():
            w.destroy()
        self.photos.clear()
        for f in photos or []:
            p = os.path.join(PHOTO, f)
            try:
                from PIL import Image, ImageTk
                im = Image.open(p).convert('RGBA')
                im.thumbnail((48, 48))
                ph = ImageTk.PhotoImage(im)
            except Exception:
                continue
            self.photos.append(ph)
            tk.Label(self.b_photo, image=ph, bg=BUBBLE).pack(side='left', padx=(0, 4), pady=2)
        if not self.bubble.winfo_ismapped():
            self.bubble.pack(side='top', anchor='e', before=self.icon, pady=(0, 4))
        self.place()

    def hide(self, delay=0):
        def do():
            self.hide_job = None
            if self.bubble.winfo_ismapped():
                self.bubble.pack_forget()
                self.place()
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if delay:
            self.hide_job = self.root.after(delay, do)
        else:
            do()

    def peek(self, on):
        if self.active:
            return
        if on:
            n = len(self.tr.steps)
            s = f'目標：{self.tr.title}\n進度：第 {min(self.tr.ptr + 1, n)}/{n} 步'
            if self.problem:
                s += f'\n⚠ {self.problem}'
            elif self.tr.offroute:
                s += '\n⚠ 目前場景不在這條路線上'
            if self.watcher.paused:
                s += '\n（已暫停）'
            s += '\n提示：別把我放在遊戲的選項上方'
            self.show('攻略桌寵', s)
        else:
            self.hide()

    # ---------------- drag / menu
    def drag_start(self, e):
        self._d = (e.x_root, e.y_root, self.ax, self.ay, False)

    def drag_move(self, e):
        x0, y0, ax, ay, _ = self._d
        if abs(e.x_root - x0) + abs(e.y_root - y0) > 3:
            self._d = (x0, y0, ax, ay, True)
            self.ax, self.ay = ax + e.x_root - x0, ay + e.y_root - y0
            self.place()

    def drag_end(self, e):
        if getattr(self, '_d', None) and self._d[4]:
            self.save()

    def menu(self, e):
        m = tk.Menu(self.root, tearoff=0, font=F_SM)
        sub = tk.Menu(m, tearoff=0, font=F_SM)
        for k, v in sorted(self.gd.routes['endings'].items(), key=lambda x: int(x[0])):
            mark = '● ' if k == self.tr.ending else '　'
            sub.add_command(label=f'{mark}{k}：{v["title"]}', command=lambda k=k: self.set_ending(k))
        m.add_cascade(label='目標結局', menu=sub)
        m.add_command(label='完整路線…', command=self.open_route)
        m.add_command(label='繼續偵測' if self.watcher.paused else '暫停偵測', command=self.toggle)
        m.add_separator()
        m.add_command(label='結束', command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def set_ending(self, k):
        self.save()
        self.tr.set_ending(k, self.cfg.get('ptr', {}).get(k, 0))
        self.active = None
        self.draw_icon()
        self.show('目標已切換', self.tr.title)
        self.hide(2500)
        self.save()

    def toggle(self):
        self.watcher.paused = not self.watcher.paused
        self.draw_icon()

    def open_route(self):
        top = tk.Toplevel(self.root)
        top.title(f'完整路線：{self.tr.title}')
        top.attributes('-topmost', True)
        top.geometry('460x640')
        tk.Label(top, text='點一下 = 我現在在這步', font=F_SM, fg=DIM).pack(anchor='w', padx=8, pady=4)
        lb = tk.Listbox(top, font=('Microsoft JhengHei UI', 10), activestyle='none')
        lb.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        kinds = {'select': '選項', 'map': '地圖', 'deduc': '推理', 'deduc3': '推理', 'search': '搜查'}
        for i, s in enumerate(self.tr.steps):
            t = s['choice_text'] if s['kind'] != 'search' else f'{len(s["clicks"])} 次點擊'
            if s['kind'] == 'map':
                t = f'第 {s["visit"]} 次：{t}'
            lb.insert('end', f'{i + 1:3d}. [{kinds[s["kind"]]}] {t}')
        lb.insert('end', f'    ★ {self.tr.title}')
        lb.selection_set(self.tr.ptr)
        lb.see(self.tr.ptr)

        def pick(_):
            sel = lb.curselection()
            if sel:
                self.tr.ptr = min(sel[0], len(self.tr.steps))
                self.tr.offroute = False
                self.tr.pending_deduc = None
                self.draw_icon()
                self.save()
        lb.bind('<<ListboxSelect>>', pick)

    def quit(self):
        self.save()
        self.watcher.stop_flag = True
        self.root.destroy()

    # ---------------- OCR events
    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'ocr':
                    if self.problem:
                        self.problem = None
                        self.draw_icon()
                    self.on_ocr(*payload)
                elif kind in ('status', 'error'):
                    if payload != self.problem:
                        self.problem = payload
                        self.draw_icon()
                    if kind == 'error':
                        self.show('OCR 無法啟動', payload, color=WARN)
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        finally:
            self.root.after(200, self.poll)

    def on_ocr(self, rect, lines):
        ring = self.ring_color()
        kind, i = self.tr.classify(rect, lines)
        if kind in ('select', 'map', 'deduc') and i is not None:
            if self.active and self.active != (kind, i) and self.active[1] is not None:
                self.tr.leave(*self.active)
            self.tr.ptr = i
            self.tr.offroute = False
            if self.active != (kind, i):
                self.active = (kind, i)
                main, sub = hint_text(self.gd, self.tr, i)
                ph = self.tr.steps[i].get('photo')
                self.show(main, sub, ph if isinstance(ph, list) else ([ph] if ph else None))
        elif kind == 'offselect':
            self.active = ('off', None)
            self.show('這題不在目標路線上', '前面可能選錯了：讀取較早的存檔，\n或右鍵 →「完整路線」手動指定位置。', color=WARN)
        elif self.active:
            k, idx = self.active
            if k in ('select', 'map', 'deduc'):
                self.tr.leave(k, idx)
            self.active = None
            self.hide(LINGER_MS)
            self.save()
        if ring != self.ring_color():
            self.draw_icon()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = tk.Tk()
    root.title('殼之少女 攻略桌寵')
    Pet(root)
    root.mainloop()


if __name__ == '__main__':
    main()
