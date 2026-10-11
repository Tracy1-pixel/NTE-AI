"""Recognize the photographed game arrow by its pointed, concave outline.

This is graphic recognition, not OCR. A software cursor is located in the
game image independently of Windows coordinates; ambiguous arrows are rejected.
Windows can draw a hardware cursor separately when screenshots omit it.
"""
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CursorHit:
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def point(self):
        return self.x, self.y


@dataclass(frozen=True)
class CursorPosition:
    point: tuple
    source: str


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
        self.reference_mask = self.shape_mask(self.reference)

    def shape_mask(self, contour):
        cv, np = self.cv, self.np
        x, y, width, height = cv.boundingRect(contour)
        mask = np.zeros((height, width), np.uint8)
        cv.drawContours(mask, [contour - (x, y)], -1, 255, -1)
        return cv.resize(mask, (100, 100), interpolation=cv.INTER_NEAREST)

    def candidates(self, image, oriented=False):
        if image is None or not image.size:
            return []
        cv, np = self.cv, self.np
        hits = []
        gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
        edges = cv.Canny(gray, 40, 110)
        edges = cv.morphologyEx(edges, cv.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        _, bright = cv.threshold(gray, 190, 255, cv.THRESH_BINARY)
        for mask in (edges, bright):
            contours, _ = cv.findContours(mask, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, width, height = cv.boundingRect(contour)
                area = cv.contourArea(contour)
                if not (12 <= height <= 110 and 0.7 <= width / height <= 1.2 and area >= 45):
                    continue
                hull_area = cv.contourArea(cv.convexHull(contour))
                if not hull_area or not 0.65 <= area / hull_area <= 0.94:
                    continue
                score = cv.matchShapes(self.reference, contour, cv.CONTOURS_MATCH_I1, 0)
                if score <= 0.16:
                    if oriented:
                        # Hu descriptors ignore orientation. Text and furniture
                        # edges can match them; require the photographed arrow's
                        # upright silhouette before locating it in a whole frame.
                        shape = self.shape_mask(contour)
                        overlap = cv.countNonZero(cv.bitwise_and(shape, self.reference_mask))
                        union = cv.countNonZero(cv.bitwise_or(shape, self.reference_mask))
                        if not union or overlap / union < 0.8:
                            continue
                    hits.append(CursorHit(x, y, width, height, float(score)))
        # Edge / fill / inner outline of the same pointer form one candidate.
        unique = []
        for hit in sorted(hits, key=lambda item: item.score):
            if not any(max(abs(hit.x - other.x), abs(hit.y - other.y)) <= 8 for other in unique):
                unique.append(hit)
        return unique

    def matches(self, image):
        return bool(self.candidates(image))

    def locate(self, frame, previous=None, reacquire=True):
        """Return a unique arrow tip, or None when absent / ambiguous.

        Track in a bounded area around the last image-confirmed position. Never
        use the desired destination to choose among otherwise ambiguous arrows.
        """
        if previous is not None:
            x, y = previous
            height, width = frame.shape[:2]
            left, top = max(0, x - 200), max(0, y - 200)
            right, bottom = min(width, x + 312), min(height, y + 312)
            if left < right and top < bottom:
                hits = self.candidates(frame[top:bottom, left:right], oriented=True)
                if len(hits) == 1:
                    hit = hits[0]
                    return CursorHit(hit.x + left, hit.y + top, hit.width, hit.height, hit.score)
                if hits:
                    return None
            if not reacquire:
                return None
        hits = self.candidates(frame, oriented=True)
        return hits[0] if len(hits) == 1 else None

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
