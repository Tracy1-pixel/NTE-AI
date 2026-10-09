"""Recognize the photographed game arrow by its pointed, concave outline.

This is graphic recognition, not OCR. Only a small region around the actual
mouse position is searched, so arrows elsewhere in the game are not targets.
Windows can draw a hardware cursor separately when screenshots omit it.
"""
import sys


class CursorDetector:
    def __init__(self):
        import cv2
        import numpy as np
        self.cv, self.np = cv2, np
        # Approximate normalized outline based on the user's photographed arrow.
        # Its upper-left tip, wide right shoulder and inward notch distinguish
        # it from a plain triangle or the standard Windows mouse pointer.
        outline = np.array([(0, 0), (95, 55), (98, 62), (50, 72),
                            (28, 100), (10, 100), (5, 90)], np.int32)
        mask = np.zeros((112, 112), np.uint8)
        cv2.fillPoly(mask, [outline + 5], 255)
        self.reference = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0][0]

    def matches(self, image):
        if image is None or not image.size:
            return False
        cv, np = self.cv, self.np
        gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
        edges = cv.Canny(gray, 40, 110)
        edges = cv.morphologyEx(edges, cv.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        _, bright = cv.threshold(gray, 190, 255, cv.THRESH_BINARY)
        for mask in (edges, bright):
            contours, _ = cv.findContours(mask, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                _, _, width, height = cv.boundingRect(contour)
                area = cv.contourArea(contour)
                if not (12 <= height <= 110 and 0.7 <= width / height <= 1.2 and area >= 45):
                    continue
                hull_area = cv.contourArea(cv.convexHull(contour))
                if not hull_area or not 0.65 <= area / hull_area <= 0.94:
                    continue
                if cv.matchShapes(self.reference, contour, cv.CONTOURS_MATCH_I1, 0) <= 0.16:
                    return True
        return False

    def near_pointer(self, frame, x, y):
        height, width = frame.shape[:2]
        if not (0 <= x < width and 0 <= y < height):
            return False
        return self.matches(frame[max(0, y - 16):min(height, y + 112),
                                  max(0, x - 16):min(width, x + 112)])


def windows_cursor_bitmap(handle=None):
    """Render the currently visible Windows cursor without moving/clicking it."""
    if sys.platform != 'win32':
        return None
    import ctypes as ct
    from ctypes import wintypes as wt
    import numpy as np

    class CursorInfo(ct.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('flags', wt.DWORD),
                    ('hCursor', wt.HANDLE), ('ptScreenPos', wt.POINT)]

    class BitmapInfoHeader(ct.Structure):
        _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG),
                    ('biPlanes', wt.WORD), ('biBitCount', wt.WORD),
                    ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD),
                    ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG),
                    ('biClrUsed', wt.DWORD), ('biClrImportant', wt.DWORD)]

    u, g = ct.WinDLL('user32'), ct.WinDLL('gdi32')
    signatures = (
        (u, 'GetCursorInfo', [ct.POINTER(CursorInfo)], wt.BOOL),
        (u, 'DrawIconEx', [wt.HDC, ct.c_int, ct.c_int, wt.HANDLE, ct.c_int,
                         ct.c_int, wt.UINT, wt.HBRUSH, wt.UINT], wt.BOOL),
        (g, 'CreateCompatibleDC', [wt.HDC], wt.HDC),
        (g, 'CreateDIBSection', [wt.HDC, ct.POINTER(BitmapInfoHeader), wt.UINT,
                               ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD], wt.HBITMAP),
        (g, 'SelectObject', [wt.HDC, wt.HANDLE], wt.HANDLE),
        (g, 'DeleteObject', [wt.HANDLE], wt.BOOL),
        (g, 'DeleteDC', [wt.HDC], wt.BOOL),
        (g, 'GdiFlush', [], wt.BOOL),
    )
    for api, name, args, result in signatures:
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    cursor = CursorInfo()
    cursor.cbSize = ct.sizeof(cursor)
    if handle is not None:  # Allows a deterministic native rendering smoke test.
        cursor.flags, cursor.hCursor = 1, handle
    elif not u.GetCursorInfo(ct.byref(cursor)):
        raise OSError('无法读取当前光标')
    if not cursor.flags & 1 or not cursor.hCursor:
        return None  # Software-rendered game cursors are searched in the frame.
    dc, bitmap, previous = g.CreateCompatibleDC(None), None, None
    if not dc:
        raise OSError('无法创建光标识别画布')
    try:
        size = 128
        info = BitmapInfoHeader(ct.sizeof(BitmapInfoHeader), size, -size, 1, 32)
        bits = ct.c_void_p()
        bitmap = g.CreateDIBSection(dc, ct.byref(info), 0, ct.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise OSError('无法读取光标图形')
        previous = g.SelectObject(dc, bitmap)
        if not previous or previous == ct.c_void_p(-1).value:
            raise OSError('无法准备光标图形')
        ct.memset(bits, 0, size * size * 4)
        if not u.DrawIconEx(dc, 0, 0, cursor.hCursor, 0, 0, 0, None, 3):
            raise OSError('无法绘制光标图形')
        if not g.GdiFlush():
            raise OSError('光标图形尚未绘制完成')
        data = (ct.c_ubyte * (size * size * 4)).from_address(bits.value)
        image = np.ctypeslib.as_array(data).reshape(size, size, 4)[:, :, :3].copy()
        return image, (cursor.ptScreenPos.x, cursor.ptScreenPos.y)
    finally:
        if previous and previous != ct.c_void_p(-1).value:
            g.SelectObject(dc, previous)
        if bitmap:
            g.DeleteObject(bitmap)
        g.DeleteDC(dc)
