"""Shared dashboard and in-game overlay status."""
from dataclasses import dataclass

PHASES = {
    'home': '确认初始界面', 'cursor': '识别游戏光标', 'anchor': '识别三星锚点',
    'scrolling': '三星锚点滚动', 'select': 'OCR 寻找 3-10', 'selected': '准备开始营业',
    'starting': '等待营业开始', 'retrying': '重新挑战', 'playing': '连点锤子',
    'exiting': '退出并结算', 'retry_loading': '等待重新挑战', 'claiming': '领取奖励',
}


@dataclass
class RuntimeStatus:
    phase: str = '就绪'
    state: str = 'idle'
    details: str = '请选择游戏窗口，从初始界面开始'
    score: int | None = None
    completed: int = 0
    failures: int = 0
    mode: str = 'loop'
    level: str = '3-10'
    goal: int | None = 1900

    def apply(self, data):
        for name in ('phase', 'state', 'details', 'score', 'completed', 'failures', 'mode', 'level', 'goal'):
            if name in data:
                setattr(self, name, data[name])

    @property
    def color(self):
        return {'idle': '#8fa1bc', 'starting': '#6ba7ff', 'running': '#42ddbc',
                'paused': '#ffc267', 'stopped': '#8fa1bc', 'error': '#ff7c8d'}.get(self.state, '#8fa1bc')

    @property
    def score_text(self):
        score = '—' if self.score is None else f'{self.score:,}'
        goal = '—' if self.goal is None else f'{self.goal:,}'
        return f'{score} / {goal}'

    @property
    def mode_text(self):
        return '闯关模式' if self.mode == 'progression' else '钢琴家循环'

    @property
    def progress_unit(self):
        return '关' if self.mode == 'progression' else '轮'


def overlay_position(area, width=430, height=112, margin=16):
    return area.x + margin, area.y + max(margin, area.height - height - margin)
