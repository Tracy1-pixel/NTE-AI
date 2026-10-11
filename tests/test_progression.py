import threading
import unittest

from automation import Stopped
from nte_workflow import Controller, LEVELS, Scene, ScreenReader, normalize_level, score_progress, settings
from nte_status import RuntimeStatus
from test_workflow import Game


class ProgressGame(Game):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chosen = None
        self.selected_levels = []
        self.started_levels = []
        self.retry_levels = []
        self.claimed_levels = []

    def goal(self):
        return 1900 if self.chosen == '3-10' else 700

    def observe(self, *, read_selected=True, target_level='3-10'):
        scene = super().observe(read_selected=read_selected, target_level=target_level)
        if scene.page == 'home' and read_selected:
            scene.selected = self.chosen == target_level
        if scene.page in ('ready', 'playing'):
            scene.goal = self.goal()
        return scene

    def select_level(self, target_level='3-10'):
        if super().select_level(target_level):
            self.chosen = target_level
            self.selected_levels.append(target_level)
            return True
        return False

    def action(self, name):
        if name == 'start':
            self.started_levels.append(self.chosen)
        elif name == 'retry':
            self.retry_levels.append(self.chosen)
        elif name == 'claim':
            self.claimed_levels.append(self.chosen)
        super().action(name)
        if name == 'hammer' and self.scene.page == 'playing' and self.hits >= 3:
            self.scene.score = self.goal() + 27


class ProgressionTests(unittest.TestCase):
    def make(self, game, start='3-9'):
        now = [0.0]
        stop = threading.Event()
        def sleep(dt):
            now[0] += dt
            if now[0] > 300:
                stop.set()
        controller = Controller({'mode': 'progression', 'start_level': start, 'scan_interval': 0.1,
                                 'click_interval': 0.03, 'confirm_frames': 2}, game, stop,
                                clock=lambda: now[0], sleep=sleep, log=lambda text: None)
        return controller, stop

    def test_two_levels_finish_only_after_final_claim_and_return(self):
        game = ProgressGame(city=500)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '闯关完成'):
            controller.run()
        self.assertEqual(game.selected_levels, ['3-9', '3-10'])
        self.assertEqual(game.claimed_levels, ['3-9', '3-10'])
        self.assertEqual(controller.completed, 2)
        self.assertEqual(game.scene.page, 'home')
        self.assertEqual(game.city, 404)

    def test_all_thirty_levels_follow_numeric_order_across_chapters(self):
        game = ProgressGame(city=10000)
        controller, _ = self.make(game, '1-1')
        with self.assertRaisesRegex(Stopped, '共完成 30 关'):
            controller.run()
        self.assertEqual(game.started_levels, list(LEVELS))
        self.assertEqual(game.claimed_levels, list(LEVELS))
        self.assertEqual(game.selected_levels[9:11], ['1-10', '2-1'])
        self.assertEqual(game.selected_levels[19:21], ['2-10', '3-1'])

    def test_failure_retries_same_level_before_advancing(self):
        game = ProgressGame(city=500, outcomes=['failure', 'success', 'success'])
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '闯关完成'):
            controller.run()
        self.assertEqual(game.retry_levels, ['3-9'])
        self.assertEqual(game.selected_levels, ['3-9', '3-10'])
        self.assertEqual(game.claimed_levels, ['3-9', '3-10'])
        self.assertEqual(controller.failures, 0)

    def test_three_failures_stop_without_skipping_level(self):
        game = ProgressGame(outcomes=['failure'] * 3)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '连续三次'):
            controller.run()
        self.assertEqual(game.selected_levels, ['3-9'])
        self.assertEqual(game.retry_levels, ['3-9', '3-9'])
        self.assertEqual(game.claimed_levels, [])
        self.assertEqual(controller.level, '3-9')

    def test_claim_without_confirmed_return_does_not_advance(self):
        class NoReturn(ProgressGame):
            def action(self, name):
                if name == 'claim':
                    self.actions.append(name)
                    return
                super().action(name)
        game = NoReturn(city=500)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(controller.completed, 0)
        self.assertEqual(controller.level, '3-9')
        self.assertEqual(game.actions.count('claim'), 1)
        self.assertEqual(game.selected_levels, ['3-9'])

    def test_stamina_zero_after_claim_prevents_next_level_start(self):
        game = ProgressGame(city=48)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, '都市体力为 0'):
            controller.run()
        self.assertEqual(game.started_levels, ['3-9'])
        self.assertEqual(controller.completed, 1)

    def test_variable_costs_and_zero_reward_stop_progression(self):
        class VariableCost(ProgressGame):
            costs = iter([48, 24, 7, 0])
            def action(self, name):
                if name == 'exit':
                    self.cost = next(self.costs)
                super().action(name)
        game = VariableCost(city=500)
        controller, _ = self.make(game, '1-1')
        with self.assertRaisesRegex(Stopped, '消耗为 0'):
            controller.run()
        self.assertEqual(game.selected_levels, ['1-1', '1-2', '1-3', '1-4'])
        self.assertEqual(game.claimed_levels, ['1-1', '1-2', '1-3'])
        self.assertEqual(controller.completed, 3)

    def test_missing_goal_does_not_default_to_pianist_target(self):
        class MissingGoal(ProgressGame):
            def observe(self, **kwargs):
                scene = super().observe(**kwargs)
                scene.goal = None
                return scene
        game = MissingGoal(city=500)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertNotIn('exit', game.actions)
        self.assertEqual(game.claimed_levels, [])

    def test_alternating_goal_reads_cannot_confirm_completion(self):
        class ChangingGoal(ProgressGame):
            reads = 0
            def observe(self, **kwargs):
                scene = super().observe(**kwargs)
                if scene.page == 'playing' and scene.score > 0:
                    self.reads += 1
                    scene.goal = 500 if self.reads % 2 else 700
                return scene
        game = ChangingGoal(city=500)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertNotIn('exit', game.actions)

    def test_wrong_selected_heading_prevents_start(self):
        class WrongHeading(ProgressGame):
            def observe(self, **kwargs):
                scene = super().observe(**kwargs)
                scene.selected = False
                return scene
        game = WrongHeading(city=500)
        controller, _ = self.make(game)
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(game.started_levels, [])

    def test_unknown_frame_interrupts_completion_confirmation(self):
        class InterruptedGoal(ProgressGame):
            reads = 0
            def observe(self, **kwargs):
                scene = super().observe(**kwargs)
                if scene.page == 'playing' and scene.score > 0:
                    self.reads += 1
                    if self.reads % 3 == 2:
                        return Scene('unknown')
                return scene
        game = InterruptedGoal(city=500)
        controller, _ = self.make(game)
        controller.c['confirm_frames'] = 3
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertNotIn('exit', game.actions)

    def test_f8_stops_progression_without_input(self):
        game = ProgressGame()
        controller, stop = self.make(game, '1-1')
        stop.set()
        with self.assertRaisesRegex(Stopped, 'F8'):
            controller.run()
        self.assertEqual(game.actions, [])


class LevelTests(unittest.TestCase):
    def test_config_migration_defaults_to_loop_and_validates_start(self):
        self.assertEqual(settings({'workflow_version': 5})['mode'], 'loop')
        self.assertEqual(len(LEVELS), 30)
        self.assertEqual(normalize_level('１.１'), '1-1')
        for level in ('1-0', '1-11', '4-1', '13-10', '1-1 extra'):
            with self.subTest(level=level), self.assertRaises(ValueError):
                settings({'mode': 'progression', 'start_level': level})

    def test_ocr_requires_exact_identifier_and_rejects_ambiguity(self):
        for level in LEVELS:
            self.assertTrue(ScreenReader.is_level(f'{level} 名字未知', level))
        for text in ('1-10', '11-1', '1-100', '1-1 1-2', '11'):
            self.assertFalse(ScreenReader.is_level(text, '1-1'))
        self.assertTrue(ScreenReader.is_level('１．１新品练习', '1-1'))

    def test_score_target_requires_a_complete_positive_fraction(self):
        self.assertEqual(score_progress('727 / 700'), (727, 700))
        self.assertEqual(score_progress('1,927 ／ 1,900'), (1927, 1900))
        self.assertEqual(score_progress('0/800'), (0, 800))
        for text in ('1900', '700/0', 'unknown', '727/700 extra', '99999/700'):
            self.assertIsNone(score_progress(text))

    def test_hud_shows_current_level_mode_and_variable_goal(self):
        status = RuntimeStatus()
        status.apply({'mode': 'progression', 'level': '2-3', 'goal': 700, 'score': 727, 'completed': 5})
        self.assertEqual(status.score_text, '727 / 700')
        self.assertEqual((status.mode_text, status.level, status.progress_unit), ('闯关模式', '2-3', '关'))
        status.apply({'goal': None, 'score': None})
        self.assertEqual(status.score_text, '— / —')


if __name__ == '__main__':
    unittest.main()
