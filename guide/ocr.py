"""Screen capture + Windows built-in OCR (zh-Hant-TW)."""
import asyncio
import ctypes
import ctypes.wintypes as wt
import os

import mss
from PIL import Image

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap, BitmapAlphaMode
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_language(Language('zh-Hant-TW'))
        if _engine is None:
            raise RuntimeError('Windows OCR 沒有繁中語言包')
    return _engine


PREFIXES = ('殼之少女HD', '殻ノ少女HD', 'THE SHELL HD', '壳之少女HD')


def find_game_window(title_keywords=('The Shell', '殼之少女', '殻ノ少女', '壳之少女'), with_title=False):
    """Return (x, y, w, h) of the game's client area, or None.
    Windows whose title starts with the real game title (list_windows_tw.tbl gametitle)
    are tried first, so a browser tab or folder named after the game is not picked."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        t = buf.value
        if any(k.lower() in t.lower() for k in title_keywords) and 'guide' not in t.lower() \
                and '攻略' not in t:
            pri = 0 if t.upper().startswith(tuple(p.upper() for p in PREFIXES)) else 1
            found.append((pri, hwnd, t))
        return True

    user32.EnumWindows(cb, 0)
    for _, hwnd, title in sorted(found, key=lambda x: x[0]):
        if user32.IsIconic(hwnd):
            continue
        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = r.right - r.left, r.bottom - r.top
        if w > 200 and h > 200:
            global last_hwnd
            last_hwnd = hwnd
            return ((pt.x, pt.y, w, h), title) if with_title else (pt.x, pt.y, w, h)
    return None


_sct = None
last_hwnd = None


def _cloaked(h):
    v = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(h), 14, ctypes.byref(v), 4)   # DWMWA_CLOAKED
    except Exception:
        return False
    return v.value != 0


def covered_fraction(hwnd=None):
    """Share of the game's client area covered by other programs' windows above it
    (our own pet window does not count)."""
    hwnd = hwnd or last_hwnd
    if not hwnd:
        return 1.0
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    gx0, gy0, gx1, gy1 = pt.x, pt.y, pt.x + r.right, pt.y + r.bottom
    area = max(1, (gx1 - gx0) * (gy1 - gy0))
    me = os.getpid()
    user32.GetWindow.restype = wt.HWND
    rects = []
    h = user32.GetWindow(hwnd, 3)                      # GW_HWNDPREV: windows above in z-order
    while h:
        ex = user32.GetWindowLongW(h, -20)                 # GWL_EXSTYLE
        clickthrough = ex & 0x20 or (ex & 0x80000 and ex & 0x80)   # TRANSPARENT, or LAYERED tool window
        if user32.IsWindowVisible(h) and not user32.IsIconic(h) and not _cloaked(h) and not clickthrough:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value != me:
                wr = wt.RECT()
                user32.GetWindowRect(h, ctypes.byref(wr))
                x0, y0 = max(wr.left, gx0), max(wr.top, gy0)
                x1, y1 = min(wr.right, gx1), min(wr.bottom, gy1)
                if x1 > x0 and y1 > y0:
                    rects.append((x0, y0, x1, y1))
        h = user32.GetWindow(h, 3)
    if not rects:
        return 0.0
    # union area on a coarse grid (cheap and good enough)
    step = 8
    cov, limit = 0, 0.02 * area / (step * step)
    for y in range(gy0, gy1, step):
        for x in range(gx0, gx1, step):
            if any(a <= x < c and b <= y < d for a, b, c, d in rects):
                cov += 1
        if cov > limit:                                # enough to call it covered
            break
    return cov * step * step / area


def is_unobscured(hwnd=None):
    return covered_fraction(hwnd) < 0.02


def grab(rect):
    global _sct
    if _sct is None:
        _sct = mss.mss()
    x, y, w, h = rect
    shot = _sct.grab({'left': x, 'top': y, 'width': w, 'height': h})
    return Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')


def _to_softbitmap(img):
    img = img.convert('RGBA')
    w, h = img.size
    r, g, b, a = img.split()
    bgra = Image.merge('RGBA', (b, g, r, a)).tobytes()
    dw = DataWriter()
    dw.write_bytes(bgra)
    buf = dw.detach_buffer()
    return SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)


async def _recognize(img):
    res = await engine().recognize_async(_to_softbitmap(img))
    lines = []
    for ln in res.lines:
        words = list(ln.words)
        if not words:
            continue
        xs = [w.bounding_rect.x for w in words]
        ys = [w.bounding_rect.y for w in words]
        x2 = [w.bounding_rect.x + w.bounding_rect.width for w in words]
        y2 = [w.bounding_rect.y + w.bounding_rect.height for w in words]
        text = ''.join(w.text for w in words)  # Chinese: no spaces
        lines.append((text, (min(xs), min(ys), max(x2), max(y2))))
    return lines


def recognize(img, scale=1.0):
    """OCR a PIL image. Returns list of (text, (x1,y1,x2,y2)) in original coords."""
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    mx = OcrEngine.max_image_dimension
    if max(img.size) > mx:
        k = mx / max(img.size)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
        scale *= k
    lines = asyncio.run(_recognize(img))
    if scale != 1.0:
        lines = [(t, tuple(int(v / scale) for v in bb)) for t, bb in lines]
    return lines


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        im = Image.open(sys.argv[1])
    else:
        r = find_game_window()
        print('game window:', r)
        if not r:
            sys.exit(1)
        im = grab(r)
    for t, bb in recognize(im):
        print(bb, t)
