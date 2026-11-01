"""殼之少女 攻略提示小視窗 (always-on-top, OCR-driven)."""
import json
import os
import queue
import sys
import tkinter as tk
import traceback
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from core import PHOTO, GuideData, Tracker, Watcher, alternatives, default_ending  # noqa: E402
SETTINGS = os.path.join(HERE, 'settings.json')

# ------------------------------------------------------------------ ui
BG, FG, DIM, ACC, WARN, OK = '#1b1d23', '#e8e8e8', '#9aa0a6', '#7cc4ff', '#ffb35c', '#8ee08e'
FONT = ('Microsoft JhengHei UI', 10)
FONT_B = ('Microsoft JhengHei UI', 12, 'bold')
FONT_BIG = ('Microsoft JhengHei UI', 15, 'bold')

KIND_LABEL = {'select': '對話選項', 'map': '地圖移動', 'deduc': '推理', 'deduc3': '推理（筆跡，選 3 人）',
              'search': '搜查'}


class App:
    def __init__(self, root):
        self.root = root
        self.gd = GuideData()
        self.settings = self.load_settings()
        ending = default_ending(self.gd, self.settings.get('ending', '11'))
        self.tr = Tracker(self.gd, ending, self.settings.get('ptr', {}).get(ending, 0))
        self.q = queue.Queue()
        self.watcher = Watcher(self.q)
        self.photo_refs = []

        root.title('殼之少女 攻略提示')
        root.configure(bg=BG)
        root.attributes('-topmost', True)
        root.attributes('-alpha', self.settings.get('alpha', 0.94))
        root.geometry(self.settings.get('geometry', '520x860+20+60'))
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.build()
        self.rebuild_route()
        self.watcher.start()
        root.after(200, self.poll)

    # ---------------- settings
    def load_settings(self):
        try:
            return json.load(open(SETTINGS, encoding='utf-8'))
        except Exception:
            return {}

    def save_settings(self):
        s = self.settings
        s['ending'] = self.ending
        s.setdefault('ptr', {})[self.ending] = self.ptr
        s['geometry'] = self.root.geometry()
        try:
            json.dump(s, open(SETTINGS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        except Exception:
            pass

    def on_close(self):
        self.save_settings()
        self.watcher.stop_flag = True
        self.root.destroy()

    # ---------------- layout
    def build(self):
        r = self.root
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground='#2a2d35', background='#2a2d35', foreground=FG,
                        arrowcolor=FG, bordercolor='#3b414d')
        style.map('TCombobox', fieldbackground=[('readonly', '#2a2d35')], foreground=[('readonly', FG)],
                  selectbackground=[('readonly', '#2a2d35')], selectforeground=[('readonly', FG)])
        r.option_add('*TCombobox*Listbox.background', '#2a2d35')
        r.option_add('*TCombobox*Listbox.foreground', FG)
        r.option_add('*TCombobox*Listbox.font', FONT)

        top = tk.Frame(r, bg=BG)
        top.pack(fill='x', padx=10, pady=(10, 4))
        tk.Label(top, text='目標結局', bg=BG, fg=DIM, font=FONT).pack(side='left')
        self.end_names = [f"{k}：{v['title']}" for k, v in sorted(self.gd.routes['endings'].items(), key=lambda x: int(x[0]))]
        self.cb = ttk.Combobox(top, values=self.end_names, state='readonly', font=FONT, width=30)
        self.cb.pack(side='left', padx=6, fill='x', expand=True)
        self.cb.bind('<<ComboboxSelected>>', self.on_ending)

        self.status = tk.Label(r, text='啟動中…', bg=BG, fg=DIM, font=FONT, anchor='w', justify='left', wraplength=400)
        self.status.pack(fill='x', padx=10)
        self.where = tk.Label(r, text='', bg=BG, fg=DIM, font=FONT, anchor='w', justify='left', wraplength=400)
        self.where.pack(fill='x', padx=10)

        card = tk.Frame(r, bg='#252a33', highlightbackground=ACC, highlightthickness=1)
        card.pack(fill='x', padx=10, pady=8)
        self.c_kind = tk.Label(card, text='', bg='#252a33', fg=ACC, font=FONT_B, anchor='w')
        self.c_kind.pack(fill='x', padx=10, pady=(8, 0))
        self.c_main = tk.Label(card, text='', bg='#252a33', fg=FG, font=FONT_BIG, anchor='w', justify='left', wraplength=390)
        self.c_main.pack(fill='x', padx=10, pady=4)
        self.c_photo = tk.Frame(card, bg='#252a33')
        self.c_photo.pack(fill='x', padx=10)
        self.c_info = tk.Label(card, text='', bg='#252a33', fg=DIM, font=FONT, anchor='w', justify='left', wraplength=390)
        self.c_info.pack(fill='x', padx=10, pady=(2, 8))

        def rewrap(e):
            w = max(200, e.width - 24)
            for lab in (self.c_main, self.c_info):
                lab.configure(wraplength=w)
            for lab in (self.status, self.where):
                lab.configure(wraplength=w)
        card.bind('<Configure>', rewrap)

        nav = tk.Frame(r, bg=BG)
        nav.pack(fill='x', padx=10)
        for txt, cmd in (('◀ 上一步', lambda: self.move(-1)), ('下一步 ▶', lambda: self.move(1)),
                         ('暫停 OCR', self.toggle_pause)):
            b = tk.Button(nav, text=txt, command=cmd, bg='#2f343e', fg=FG, relief='flat', font=FONT,
                          activebackground='#3b414d', activeforeground=FG)
            b.pack(side='left', padx=(0, 6))
            if txt == '暫停 OCR':
                self.pause_btn = b
        self.alpha = tk.Scale(nav, from_=40, to=100, orient='horizontal', bg=BG, fg=DIM, highlightthickness=0,
                              troughcolor='#2f343e', showvalue=False, length=80, command=self.on_alpha)
        self.alpha.set(int(self.settings.get('alpha', 0.94) * 100))
        self.alpha.pack(side='right')
        tk.Label(nav, text='透明', bg=BG, fg=DIM, font=FONT).pack(side='right')

        tk.Label(r, text='完整路線（點一下 = 我現在在這步）', bg=BG, fg=DIM, font=FONT, anchor='w').pack(fill='x', padx=10, pady=(8, 0))
        lf = tk.Frame(r, bg=BG)
        lf.pack(fill='both', expand=True, padx=10, pady=(2, 10))
        self.lb = tk.Listbox(lf, bg='#15171c', fg=FG, font=FONT, selectbackground='#34506e', relief='flat',
                             highlightthickness=0, activestyle='none')
        sb = tk.Scrollbar(lf, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.lb.bind('<<ListboxSelect>>', self.on_pick)

    # ---------------- route state (kept in the shared Tracker)
    @property
    def ending(self):
        return self.tr.ending

    @property
    def ptr(self):
        return self.tr.ptr

    @ptr.setter
    def ptr(self, v):
        self.tr.ptr = v

    @property
    def offroute(self):
        return self.tr.offroute

    @offroute.setter
    def offroute(self, v):
        self.tr.offroute = v

    @property
    def steps(self):
        return self.gd.routes['endings'][self.ending]['steps']

    def rebuild_route(self):
        e = self.gd.routes['endings'][self.ending]
        self.cb.set(f"{self.ending}：{e['title']}")
        self.lb.delete(0, 'end')
        for i, s in enumerate(self.steps):
            self.lb.insert('end', f'{i + 1:3d}. [{KIND_LABEL[s["kind"]]}] {self.short(s)}')
        self.lb.insert('end', f'    ★ {e["title"]}')
        self.ptr = max(0, min(self.ptr, len(self.steps)))
        self.render()

    def short(self, s):
        if s['kind'] == 'map':
            return f'第 {s["visit"]} 次：{s["choice_text"]}'
        if s['kind'] == 'search':
            return f'{len(s["clicks"])} 次點擊'
        return s['choice_text']

    def on_ending(self, _=None):
        self.save_settings()
        k = self.cb.get().split('：')[0]
        self.tr.set_ending(k, self.settings.get('ptr', {}).get(k, 0))
        self.rebuild_route()

    def on_pick(self, _=None):
        sel = self.lb.curselection()
        if sel:
            self.ptr = min(sel[0], len(self.steps))
            self.offroute = False
            self.tr.pending_deduc = None
            self.render(scroll=False)

    def move(self, d):
        self.ptr = max(0, min(len(self.steps), self.ptr + d))
        self.offroute = False
        self.render()

    def toggle_pause(self):
        self.watcher.paused = not self.watcher.paused
        self.pause_btn.configure(text='繼續 OCR' if self.watcher.paused else '暫停 OCR')
        self.status.configure(text='OCR 已暫停' if self.watcher.paused else 'OCR 執行中')

    def on_alpha(self, v):
        a = int(v) / 100
        self.root.attributes('-alpha', a)
        self.settings['alpha'] = a

    # ---------------- rendering
    def consequences(self, s):
        return [f'選「{t}」→ 結局 {", ".join(map(str, ends))}' for t, ends in alternatives(self.gd, s)]

    def render(self, scroll=True):
        steps = self.steps
        for w in self.c_photo.winfo_children():
            w.destroy()
        self.photo_refs.clear()
        if self.ptr >= len(steps):
            self.c_kind.configure(text='已無需要選擇的地方')
            self.c_main.configure(text=f'照劇情走到底：{self.gd.routes["endings"][self.ending]["title"]}')
            self.c_info.configure(text='')
        else:
            s = steps[self.ptr]
            self.c_kind.configure(text=f'第 {self.ptr + 1}/{len(steps)} 步 · {KIND_LABEL[s["kind"]]}')
            info = []
            if s['kind'] == 'select':
                opts = s['options']
                main = f'選第 {s["choice"] + 1} 個：「{s["choice_text"]}」'
                info.append('選項：' + ' ／ '.join(f'{i + 1}.{o}' for i, o in enumerate(opts)))
            elif s['kind'] == 'map':
                main = f'去「{s["choice_text"]}」'
                info.append(f'（這張地圖第 {s["visit"]} 次移動，共可選：{"、".join(s["options"])}）')
            elif s['kind'] == 'deduc':
                main = f'在{s["list"]}清單選：「{s["choice_text"]}」'
                info.append('答錯只會重來，不影響結局。')
            elif s['kind'] == 'deduc3':
                main = f'選這 3 人：{s["choice_text"]}'
                info.append('會影響第 5 章能否避開 BAD END。')
            else:
                main = '依序調查：'
                clicks = [t for t in s['click_texts'] if t != '離開搜查']
                main += '\n' + '\n'.join(f'• {t}' for t in clicks) if clicks else '直接離開'
                info.append('調查完按「離開」。')
            if s.get('effects'):
                info.append('效果：' + '；'.join(s['effects']))
            cons = self.consequences(s)
            if cons:
                info.append('其他選擇的走向：' + '；'.join(cons))
            self.c_main.configure(text=main)
            self.c_info.configure(text='\n'.join(info))
            photos = s.get('photo')
            if photos:
                self.show_photos(photos if isinstance(photos, list) else [photos])
        if self.offroute:
            self.where.configure(text='⚠ 目前場景不在這條路線上，可能前面選錯了。請讀取較早存檔，或在下方清單手動指定位置。', fg=WARN)
        self.lb.selection_clear(0, 'end')
        self.lb.selection_set(self.ptr)
        if scroll:
            self.lb.see(min(self.ptr + 3, self.lb.size() - 1))
            self.lb.see(self.ptr)

    def show_photos(self, files):
        try:
            from PIL import Image, ImageTk
        except Exception:
            return
        for f in files:
            p = os.path.join(PHOTO, f)
            if not os.path.exists(p):
                continue
            im = Image.open(p).convert('RGBA')
            im.thumbnail((72, 72))
            ph = ImageTk.PhotoImage(im)
            self.photo_refs.append(ph)
            tk.Label(self.c_photo, image=ph, bg='#252a33').pack(side='left', padx=(0, 6))

    # ---------------- ocr results
    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'status':
                    self.status.configure(text=payload or 'OCR 執行中', fg=WARN if payload else DIM)
                elif kind == 'error':
                    self.status.configure(text=payload, fg=WARN)
                elif kind == 'ocr':
                    self.handle_ocr(*payload)
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        finally:
            self.root.after(200, self.poll)

    def handle_ocr(self, rect, lines, title=""):
        self.status.configure(text=f'OCR 執行中 · 遊戲視窗 {rect[2]}×{rect[3]}', fg=DIM)
        old = self.ptr
        kind, i = self.tr.classify(rect, lines, title)
        if kind is None and i == 'dialog':
            i = None
        if kind in ('hold', 'deduc_x'):
            if kind == 'deduc_x':
                self.where.configure(text='推理（不在目標路線上）：' + '／'.join(a['text'] for a in i['answers']), fg=WARN)
            return
        if kind in ('select', 'map', 'deduc', 'search') and i is not None:
            self.ptr = i
            label = {'select': '選項', 'map': '地圖', 'deduc': '推理清單', 'search': '搜查'}[kind]
            self.where.configure(text=f'偵測到{label}畫面 ✓', fg=OK)
        elif kind == 'offselect':
            self.where.configure(text='偵測到選項畫面，但這題不在目前路線上', fg=WARN)
        elif self.offroute:
            self.where.configure(text='目前場景不在這條路線上', fg=WARN)
        if self.ptr != old or kind == 'offselect':
            self.render()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # before Tk, or coordinates are scaled
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    root.bind('<Configure>', lambda e: setattr(app.watcher, 'exclude', [(
        root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())]))
    root.mainloop()


if __name__ == '__main__':
    main()
