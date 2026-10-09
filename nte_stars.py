"""Locate a complete horizontal group of three gold stars in the level list."""
from dataclasses import dataclass


@dataclass(frozen=True)
class StarAnchor:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self):
        return self.x + self.width / 2, self.y + self.height / 2


class StarAnchorDetector:
    def __init__(self):
        import cv2
        import numpy as np
        self.cv, self.np = cv2, np

    def groups(self, image):
        """Return bounding boxes for whole triplets, in this image's coordinates."""
        cv, np = self.cv, self.np
        if image is None or not image.size:
            return []
        mask = cv.inRange(cv.cvtColor(image, cv.COLOR_BGR2HSV),
                          np.array([8, 100, 130], np.uint8),
                          np.array([40, 255, 255], np.uint8))
        mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        stars = []
        for contour in contours:
            x, y, w, h = cv.boundingRect(contour)
            if not (12 <= w <= 90 and 12 <= h <= 90 and 0.75 <= w / h <= 1.35):
                continue
            if not 0.3 <= cv.contourArea(contour) / (w * h) <= 0.8:
                continue
            hull = cv.convexHull(contour, returnPoints=False)
            if len(hull) < 3 or len(contour) < 4:
                continue
            defects = cv.convexityDefects(contour, hull)
            notches = sum(d[0][3] / 256 > min(w, h) * 0.1 for d in defects) if defects is not None else 0
            if 4 <= notches <= 6:
                stars.append(StarAnchor(x, y, w, h))
        rows = []
        for star in sorted(stars, key=lambda item: item.center[1]):
            row = next((row for row in rows
                        if abs(row[0].center[1] - star.center[1]) <= min(row[0].height, star.height) * 0.25), None)
            if row is None:
                rows.append([star])
            else:
                row.append(star)
        groups = []
        for row in rows:
            row.sort(key=lambda star: star.x)
            for index in range(len(row) - 2):
                triplet = row[index:index + 3]
                widths, heights = [s.width for s in triplet], [s.height for s in triplet]
                gaps = [triplet[i + 1].center[0] - triplet[i].center[0] for i in range(2)]
                mean_width = sum(widths) / 3
                if max(widths) / min(widths) > 1.3 or max(heights) / min(heights) > 1.3:
                    continue
                if not all(0.9 * mean_width <= gap <= 2 * mean_width for gap in gaps):
                    continue
                if max(gaps) / min(gaps) > 1.25:
                    continue
                left, top = min(s.x for s in triplet), min(s.y for s in triplet)
                right = max(s.x + s.width for s in triplet)
                bottom = max(s.y + s.height for s in triplet)
                groups.append(StarAnchor(left, top, right - left, bottom - top))
        return groups

    def find(self, reference_frame):
        """Search only the left level list, excluding the header and right panel."""
        menu = reference_frame[140:1390, :455]
        groups = self.groups(menu)
        if not groups:
            return None
        group = min(groups, key=lambda item: abs(item.center[1] - menu.shape[0] / 2))
        return StarAnchor(group.x, group.y + 140, group.width, group.height)
