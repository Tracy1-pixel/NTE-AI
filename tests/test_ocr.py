import unittest
from unittest.mock import Mock

import cv2

from automation import parse_score
from nte_workflow import ASSETS, ScreenReader, fraction, integer


class NumberTests(unittest.TestCase):
    def reader(self, rows, fallback=''):
        reader = ScreenReader.__new__(ScreenReader)
        reader.ocr = Mock(return_value=(rows, None))
        reader.text = Mock(return_value=fallback)
        return reader

    def test_fraction_denominator_is_not_progress(self):
        reader = self.reader([['0/1,900', 0.9]])
        self.assertEqual(reader.number(None, parse_score), 0)
        reader = self.reader([['1,900', 0.9]], fallback='1,900')
        self.assertIsNone(reader.number(None, parse_score))

    def test_low_confidence_and_invalid_fast_reads_use_full_ocr(self):
        for rows in (None, [], [['0', 0.4]], [['消耗', 0.99]], [['0', 0.99], ['48', 0.99]]):
            with self.subTest(rows=rows):
                reader = self.reader(rows, fallback='48')
                self.assertEqual(reader.number(None, integer), 48)

    def test_failed_reads_never_become_zero(self):
        for rows in (None, [['0', 0.4]], [['?', 0.99]]):
            reader = self.reader(rows)
            self.assertIsNone(reader.number(None, integer))

    def test_zero_and_variable_costs_are_fresh_reads(self):
        reader = self.reader(None)
        reader.ocr.side_effect = [([['48', 0.99]], None), ([['7', 0.99]], None), ([['0', 0.99]], None)]
        self.assertEqual([reader.number(None, integer) for _ in range(3)], [48, 7, 0])

    def test_scrolling_skips_selected_title_but_still_reads_city(self):
        reader = self.reader(None)
        reader.cv = cv2
        reader.number = Mock(return_value=652)
        reader.matches = lambda frame, name, box, threshold=0.82: name in ('home_title', 'home_start')
        reader.text.return_value = '3-10 钢！琴！家！'
        frame = cv2.imread(str(ASSETS / 'star_triplet.png'))
        scene = reader.inspect(frame, read_selected=False)
        self.assertEqual((scene.page, scene.city, scene.selected), ('home', 652, False))
        reader.text.assert_not_called()
        scene = reader.inspect(frame)
        self.assertEqual((scene.page, scene.city, scene.selected), ('home', 652, True))


class RealNumberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = ScreenReader()

    def test_player_number_crops_at_multiple_client_scales(self):
        for name, expected, parser in (('score_zero', 0, parse_score), ('score_goal', 1927, parse_score), ('city_sample', 652, fraction), ('cost_sample', 48, integer)):
            image = cv2.imread(str(ASSETS / (name + '.png')))
            self.assertIsNotNone(image)
            for scale in (1.0, 0.75, 0.5):
                with self.subTest(name=name, scale=scale):
                    scaled = cv2.resize(cv2.resize(image, None, fx=scale, fy=scale), (image.shape[1], image.shape[0]))
                    self.assertEqual(self.reader.number(scaled, parser), expected)


if __name__ == '__main__':
    unittest.main()
