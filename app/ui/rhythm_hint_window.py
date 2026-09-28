import heapq
import math
import time
from bisect import bisect_left, bisect_right

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..multipress import annotate_multi_press, track_angle_limit


NORMAL_COLOR = QColor("#ff4b3e")
NORMAL_EDGE = QColor("#ffffff")
HOLD_COLOR = QColor("#ffd23f")
HOLD_EDGE = QColor("#ffffff")
MULTI_COLOR = QColor("#2ee66b")
MULTI_TEXT_COLOR = QColor("#0b0f14")

BEAT_LINE_COLOR = QColor(255, 255, 255, 78)
BEAT_LINE_STRONG_COLOR = QColor(255, 255, 255, 155)

DIVISIONS = (4, 8, 16, 32)

HIT_EFFECT_MS = 320.0
HIT_RING_MAX_SCALE = 2.8

WINDOW_STYLE = """
QDialog { background: #0b0f14; }
QWidget#hintPanel {
    background: #141a22;
    border: 1px solid #222c38;
    border-radius: 12px;
}
QLabel#hintCaption {
    color: #7f8b9c;
    font-size: 11px;
    font-weight: 600;
}
QLabel#hintBpm {
    color: #ffffff;
    font-size: 30px;
    font-weight: 800;
}
QLabel#hintCount {
    color: #4fc3f7;
    font-size: 17px;
    font-weight: 700;
}
"""


class _TaikoCanvas(QWidget):

    LEAD_MS = 1500.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 90)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.notes = []
        self._press_times = []
        self._active_holds = set()
        self._hold_release_heap = []
        self._hold_add_index = 0
        self._hit_index = 0
        self._effects = []
        self.chart_time = 0.0
        self.bpm = 0.0
        self.speed_scale = 1.0
        self.division = 4
        self.hit_effect_enabled = True
        self.multi_press_enabled = True
        self._angles = None
        self._bpm_points = []
        self.placeholder = "未加载谱面"

    def set_notes(self, notes, angles=None, bpm_points=None):

        self._bpm_points = list(bpm_points or [])

        def press_of(note):
            try:
                return float(note.get("press_time", 0.0))
            except (TypeError, ValueError):
                return 0.0

        pairs = []
        for index, note in enumerate(notes or []):
            try:
                item = dict(note)
            except (TypeError, ValueError):
                continue
            angle = None
            if angles is not None and index < len(angles):
                angle = angles[index]
            pairs.append((item, angle))

        pairs.sort(key=lambda pair: press_of(pair[0]))
        items = [pair[0] for pair in pairs]
        self._angles = [pair[1] for pair in pairs]
        self.notes = items
        self._press_times = [press_of(n) for n in items]
        self._reannotate()
        self.reset_hits()
        self.update()

    def _bpm_at(self, chart_time):
        points = self._bpm_points
        if not points:
            return self.bpm
        bpm = points[0][1]
        for time_ms, value in points:
            if time_ms > chart_time:
                break
            bpm = value
        return bpm

    def _reannotate(self):
        if not self.notes:
            return
        limits = [
            track_angle_limit(self._bpm_at(press))
            for press in self._press_times
        ]
        annotate_multi_press(
            self.notes,
            self._angles,
            limit=limits,
        )

    @staticmethod
    def _hold_release_ms(note):
        if not note.get("is_hold"):
            return None
        raw = note.get("release_time")
        if raw is None:
            return None
        try:
            release = float(raw)
            press = float(note.get("press_time", 0.0))
        except (TypeError, ValueError):
            return None
        return release if release > press else None

    def _rebuild_hold_tracking(self):

        value = self.chart_time
        self._active_holds = set()
        self._hold_release_heap = []
        self._hold_add_index = bisect_right(self._press_times, value)
        for index in range(self._hold_add_index):
            release = self._hold_release_ms(self.notes[index])
            if release is not None and release >= value:
                self._active_holds.add(index)
                heapq.heappush(self._hold_release_heap, (release, index))

    def _advance_hold_tracking(self, value):
        count = len(self._press_times)
        while (self._hold_add_index < count
               and self._press_times[self._hold_add_index] <= value):
            index = self._hold_add_index
            release = self._hold_release_ms(self.notes[index])
            if release is not None and release >= value:
                self._active_holds.add(index)
                heapq.heappush(self._hold_release_heap, (release, index))
            self._hold_add_index += 1

        heap = self._hold_release_heap
        while heap and heap[0][0] < value:
            _, index = heapq.heappop(heap)
            self._active_holds.discard(index)

    def reset_hits(self):
        self._hit_index = self._count_hits(self.chart_time, strict=True)
        self._effects = []
        self._rebuild_hold_tracking()

    def _count_hits(self, value, strict=False):
        count = 0
        for press in self._press_times:
            if press < value or (not strict and press <= value):
                count += 1
            else:
                break
        return count

    def set_chart_time(self, value):
        value = float(value)
        old = self.chart_time
        if value < old:
            self.chart_time = value
            self._hit_index = self._count_hits(value, strict=True)
            self._effects.clear()
            self._rebuild_hold_tracking()
            self.update()
            return
        if (value - old) > 250.0:
            self.chart_time = value
            self._hit_index = self._count_hits(value)
            self._effects.clear()
            self._advance_hold_tracking(value)
            self.update()
            return
        if value == old:
            self.update()
            return

        self.chart_time = value
        self._advance_hold_tracking(value)
        while (self._hit_index < len(self._press_times)
               and self._press_times[self._hit_index] <= value):
            if self.hit_effect_enabled:
                self._effects.append(value)
            self._hit_index += 1
        if self._effects:
            cutoff = value - HIT_EFFECT_MS
            self._effects = [start for start in self._effects if start >= cutoff]
        self.update()

    def has_active_effects(self):
        if not self.hit_effect_enabled:
            return False
        return any(self.chart_time - start < HIT_EFFECT_MS for start in self._effects)

    def advance_for_effects(self, delta_ms):
        if delta_ms <= 0:
            return
        self.chart_time += delta_ms
        cutoff = self.chart_time - HIT_EFFECT_MS
        self._effects = [start for start in self._effects if start >= cutoff]
        self._hit_index = self._count_hits(self.chart_time)
        self._advance_hold_tracking(self.chart_time)
        self.update()

    def set_hit_effect_enabled(self, enabled):
        self.hit_effect_enabled = bool(enabled)
        if not self.hit_effect_enabled:
            self._effects.clear()
        self.update()

    def set_multi_press_enabled(self, enabled):
        self.multi_press_enabled = bool(enabled)
        self.update()

    def set_options(self, speed, division, hit_effect=None, multi_press=None):
        if hit_effect is not None:
            self.set_hit_effect_enabled(hit_effect)
        if multi_press is not None:
            self.set_multi_press_enabled(multi_press)
        try:
            self.speed_scale = float(speed)
        except (TypeError, ValueError):
            self.speed_scale = 1.0
        if self.speed_scale <= 0:
            self.speed_scale = 1.0
        try:
            value = int(division)
        except (TypeError, ValueError):
            value = 4
        self.division = value if value in DIVISIONS else 4
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing,
            True,
        )

        rect = self.rect()
        width = max(1, rect.width())
        height = max(1, rect.height())

        gradient = QLinearGradient(0.0, 0.0, 0.0, float(height))
        gradient.setColorAt(0.0, QColor("#0d1218"))
        gradient.setColorAt(1.0, QColor("#171e28"))
        painter.fillRect(rect, QBrush(gradient))

        center_y = height * 0.5
        note_r = max(12.0, min(height * 0.20, 30.0))
        judge_x = max(56.0, width * 0.14)
        right_x = width - note_r - 8.0
        span = max(1.0, right_x - judge_x)
        speed_scale = self.speed_scale if self.speed_scale > 0 else 1.0
        px_per_ms = span / self.LEAD_MS * speed_scale

        lane_top = center_y - note_r * 1.55
        lane_height = note_r * 3.1
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.drawRoundedRect(
            QRectF(judge_x - note_r, lane_top, width - judge_x + note_r, lane_height),
            note_r,
            note_r,
        )

        self._draw_beat_lines(
            painter, judge_x, width, lane_top, lane_height, px_per_ms
        )

        pen = QPen(QColor(255, 255, 255, 80))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(judge_x, lane_top), QPointF(judge_x, lane_top + lane_height)
        )

        if not self.notes:
            painter.setPen(QColor("#66717f"))
            font = QFont(self.font())
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self.placeholder)
            painter.end()
            return

        self._draw_judge(painter, judge_x, center_y, note_r)
        visible_lo = self.chart_time - max(note_r * 0.5, 1.0) / px_per_ms
        visible_hi = (
            self.chart_time
            + (width + note_r * 2.5 - judge_x) / px_per_ms
        )
        start = bisect_left(self._press_times, visible_lo)
        end = bisect_right(self._press_times, visible_hi)
        for index in range(start, end):
            self._draw_note(
                painter, self.notes[index], judge_x, center_y,
                note_r, px_per_ms, width
            )
        for index in self._active_holds:
            if index < start:
                self._draw_note(
                    painter, self.notes[index], judge_x, center_y,
                    note_r, px_per_ms, width
                )
        self._draw_hit_effects(painter, judge_x, center_y, note_r)
        painter.end()

    def _draw_beat_lines(self, painter, judge_x, width, lane_top, lane_height, px_per_ms):
        if self.bpm <= 0 or self.division not in DIVISIONS or px_per_ms <= 0:
            return
        beat_ms = 60000.0 / self.bpm
        interval_ms = beat_ms * (4.0 / self.division)
        if interval_ms <= 0:
            return
        lead_ms = max(0.0, (width - judge_x) / px_per_ms)
        first = int(math.floor(self.chart_time / interval_ms))
        last = int(math.ceil((self.chart_time + lead_ms) / interval_ms))
        bottom = lane_top + lane_height
        for k in range(first, last + 1):
            x = judge_x + (k * interval_ms - self.chart_time) * px_per_ms
            if x < judge_x or x > width:
                continue
            if k % self.division == 0:
                pen = QPen(BEAT_LINE_STRONG_COLOR, 2.2)
            else:
                pen = QPen(BEAT_LINE_COLOR, 1.4)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, lane_top), QPointF(x, bottom))

    def _draw_judge(self, painter, x, y, r):
        radius = r * 1.25
        painter.setPen(QPen(QColor("#39434f"), max(3.0, r * 0.16)))
        painter.setBrush(QColor("#1c232c"))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2c3641"))
        painter.drawEllipse(QPointF(x, y), r * 0.45, r * 0.45)

    def _draw_hit_effects(self, painter, x, y, r):
        if not self.hit_effect_enabled or not self._effects:
            return
        for start in self._effects:
            progress = (self.chart_time - start) / HIT_EFFECT_MS
            if progress < 0.0 or progress > 1.0:
                continue
            radius = r * (1.0 + progress * (HIT_RING_MAX_SCALE - 1.0))
            alpha = int(235 * (1.0 - progress))
            if alpha <= 0:
                continue
            pen = QPen(
                QColor(255, 255, 255, alpha),
                max(2.0, r * 0.26 * (1.0 - progress * 0.7)),
            )
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(x, y), radius, radius)

    def _multi_count_of(self, note):
        if not self.multi_press_enabled:
            return 1
        try:
            count = int(note.get("multi_count", 1) or 1)
        except (TypeError, ValueError, AttributeError):
            return 1
        return count if count >= 2 else 1

    def _draw_multi_digit(self, painter, x, y, r, count):
        font = QFont(self.font())
        font.setPointSizeF(max(6.5, r * 0.95))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(MULTI_TEXT_COLOR)))
        rect = QRectF(x - r, y - r, r * 2.0, r * 2.0)
        painter.drawText(rect, Qt.AlignCenter, str(count))

    def _draw_note(self, painter, note, judge_x, center_y, r, px_per_ms, width):
        try:
            press = float(note.get("press_time", 0.0))
        except (TypeError, ValueError):
            return
        release_raw = note.get("release_time")
        is_hold = bool(note.get("is_hold")) and release_raw is not None
        stroke = max(2.0, r * 0.14)

        count = self._multi_count_of(note)
        if count >= 2 and not note.get("multi_lead"):
            return
        cy = center_y
        fill = QColor(HOLD_COLOR) if is_hold else (
            QColor(MULTI_COLOR) if count >= 2 else QColor(NORMAL_COLOR)
        )

        x_press = judge_x + (press - self.chart_time) * px_per_ms

        if not is_hold:
            if x_press < judge_x - r * 0.25:
                return
            if x_press > width + r * 2.5:
                return
            painter.setPen(QPen(QColor(NORMAL_EDGE), stroke))
            painter.setBrush(fill)
            painter.drawEllipse(QPointF(x_press, cy), r, r)
            if count >= 2:
                self._draw_multi_digit(painter, x_press, cy, r, count)
            return

        try:
            release = float(release_raw)
        except (TypeError, ValueError):
            release = press
        x_release = judge_x + (release - self.chart_time) * px_per_ms
        if x_release < judge_x:
            return
        if x_press > width + r * 2.5:
            return

        bar_height = r * 2.0
        left = x_press - bar_height * 0.5
        right = max(x_release, judge_x + r)
        bar = QRectF(left, cy - bar_height * 0.5, right - left, bar_height)

        painter.save()
        painter.setClipRect(
            QRectF(judge_x, center_y - r * 8.0, width - judge_x + r, r * 16.0)
        )
        painter.setPen(QPen(QColor(HOLD_EDGE), max(1.5, stroke * 0.7)))
        painter.setBrush(fill)
        painter.drawRoundedRect(bar, bar_height * 0.5, bar_height * 0.5)
        painter.restore()

        head_x = x_press if self.chart_time < press else judge_x
        if head_x > -r * 4:
            painter.setPen(QPen(QColor(HOLD_EDGE), stroke))
            painter.setBrush(fill)
            painter.drawEllipse(QPointF(head_x, cy), r, r)
            if count >= 2:
                self._draw_multi_digit(painter, head_x, cy, r, count)


class RhythmHintWindow(QDialog):

    DEFAULT_WIDTH = 900
    DEFAULT_HEIGHT = 150
    MIN_WIDTH = 480

    BPM_ANIM_MS = 260.0
    BPM_SLOW_COLOR = QColor("#4fc3f7")
    BPM_FAST_COLOR = QColor("#ff5252")
    BPM_IDLE_COLOR = QColor("#ffffff")

    def __init__(self, player, width=None):
        super().__init__(None)
        self.player = player
        self.setWindowTitle("节奏提示")
        self.setModal(False)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setFixedHeight(self.DEFAULT_HEIGHT)
        self.resize(self._clamp_width(width), self.DEFAULT_HEIGHT)
        self.setStyleSheet(WINDOW_STYLE)

        self._chart_time = 0.0
        self._base_bpm = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0
        self._bpm_points = []
        self._bpm_times = []
        self._bpm_target = 0.0
        self._bpm_display_value = 0.0
        self._bpm_anim_from = 0.0
        self._bpm_anim_start_ms = 0.0
        self._bpm_anim_progress = 1.0
        self._bpm_anim_direction = 0
        self._bpm_anim_active = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        panel = QWidget()
        panel.setObjectName("hintPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setFixedWidth(150)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 8, 12, 8)
        panel_layout.setSpacing(2)

        lbl_bpm_caption = QLabel("BPM")
        lbl_bpm_caption.setObjectName("hintCaption")
        self.lbl_bpm_value = QLabel("--")
        self.lbl_bpm_value.setObjectName("hintBpm")

        self.lbl_count_value = QLabel("0 / 0")
        self.lbl_count_value.setObjectName("hintCount")

        panel_layout.addWidget(lbl_bpm_caption)
        panel_layout.addWidget(self.lbl_bpm_value)
        panel_layout.addSpacing(6)
        panel_layout.addWidget(self.lbl_count_value)
        panel_layout.addStretch(1)

        self.canvas = _TaikoCanvas()

        root.addWidget(panel)
        root.addWidget(self.canvas, 1)

    @classmethod
    def _clamp_width(cls, width):
        if width is None:
            return cls.DEFAULT_WIDTH
        try:
            return max(cls.MIN_WIDTH, int(width))
        except (TypeError, ValueError):
            return cls.DEFAULT_WIDTH

    def reset_size(self):
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def set_options(self, speed, division, hit_effect=None, multi_press=None):
        self.canvas.set_options(speed, division, hit_effect, multi_press)

    def set_chart(self, bpm, notes, bpm_points=None, angles=None):

        self._chart_time = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0
        self._base_bpm = self._bpm_value(bpm)
        self.canvas.bpm = self._base_bpm
        self._bpm_points = self._normalize_bpm_points(bpm_points)
        self._bpm_times = [item[0] for item in self._bpm_points]
        self._update_bpm_display(self._last_tick_ms, snap=True)
        self.canvas.set_notes(notes, angles, self._bpm_points)
        self.canvas.set_chart_time(0.0)
        self._update_count(self.canvas.notes, 0.0)

    def reset_position(self):
        self._chart_time = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0
        self.canvas.chart_time = 0.0
        self.canvas.reset_hits()
        self._update_bpm_display(self._last_tick_ms, snap=True)
        self._update_count(self.canvas.notes, 0.0)
        self.canvas.update()

    @staticmethod
    def _bpm_value(bpm):
        try:
            value = float(bpm)
        except (TypeError, ValueError):
            return 0.0
        return value if value > 0 else 0.0

    def _current_speed(self):
        playback = getattr(self.player, "playback", None)
        if playback is None:
            return 1.0
        try:
            speed = float(getattr(playback, "speed", 1.0))
        except (TypeError, ValueError):
            return 1.0
        return speed if speed > 0 else 1.0

    def _normalize_bpm_points(self, bpm_points):
        items = []
        for item in bpm_points or []:
            try:
                time_ms = max(0.0, float(item[0]))
                bpm = self._bpm_value(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if bpm > 0:
                items.append((time_ms, bpm))
        items.sort(key=lambda pair: pair[0])
        if not items:
            return [(0.0, self._base_bpm)] if self._base_bpm > 0 else []
        if items[0][0] > 0.0:
            fallback = self._base_bpm if self._base_bpm > 0 else items[0][1]
            items.insert(0, (0.0, fallback))
        return items

    def _bpm_at(self, chart_time):
        points = self._bpm_points
        if not points:
            return self._base_bpm
        times = self._bpm_times
        if len(times) != len(points):
            times = [item[0] for item in points]
            self._bpm_times = times
        index = bisect_right(times, chart_time) - 1
        if index < 0:
            index = 0
        return points[index][1]

    def _update_bpm_display(self, now_ms, snap=False):

        target = max(0.0, self._bpm_at(self._chart_time) * self._current_speed())
        if snap:
            self._bpm_target = target
            self._bpm_display_value = target
            self._bpm_anim_from = target
            self._bpm_anim_progress = 1.0
            self._bpm_anim_direction = 0
            self._bpm_anim_active = False
            self._render_bpm()
            return

        if abs(target - self._bpm_target) < 1e-6:
            self._advance_bpm_animation(now_ms)
            return

        self._bpm_target = target
        self._bpm_anim_from = self._bpm_display_value
        self._bpm_anim_start_ms = now_ms
        self._bpm_anim_direction = 1 if target > self._bpm_display_value else -1
        self._bpm_anim_progress = 0.0
        self._bpm_anim_active = True
        self._render_bpm()

    def _advance_bpm_animation(self, now_ms):
        if not self._bpm_anim_active:
            return
        span = max(1.0, float(self.BPM_ANIM_MS))
        progress = (now_ms - self._bpm_anim_start_ms) / span
        if progress >= 1.0:
            progress = 1.0
            self._bpm_anim_active = False
        eased = 1.0 - (1.0 - progress) ** 3
        self._bpm_anim_progress = progress
        self._bpm_display_value = self._bpm_anim_from + (
            self._bpm_target - self._bpm_anim_from
        ) * eased
        if not self._bpm_anim_active:
            self._bpm_display_value = self._bpm_target
        self._render_bpm()

    def _render_bpm(self):
        value = self._bpm_display_value
        if value <= 0.0:
            self.lbl_bpm_value.setText("--")
            self.lbl_bpm_value.setStyleSheet(f"color: {self.BPM_IDLE_COLOR.name()};")
            return

        self.lbl_bpm_value.setText(self._format_bpm(value))
        if self._bpm_anim_direction == 0:
            color = QColor(self.BPM_IDLE_COLOR)
        else:
            start = (
                self.BPM_SLOW_COLOR
                if self._bpm_anim_direction < 0
                else self.BPM_FAST_COLOR
            )
            progress = min(1.0, max(0.0, self._bpm_anim_progress))
            color = QColor(
                round(start.red() + (255 - start.red()) * progress),
                round(start.green() + (255 - start.green()) * progress),
                round(start.blue() + (255 - start.blue()) * progress),
            )
        self.lbl_bpm_value.setStyleSheet(f"color: {color.name()};")

    @staticmethod
    def _format_bpm(value):
        if abs(value - round(value)) < 0.05:
            return f"{round(value):d}"
        return f"{value:.1f}"

    def _update_count(self, notes, chart_time):
        press_times = self.canvas._press_times
        if notes is self.canvas.notes and len(press_times) == len(notes):
            current = bisect_left(press_times, chart_time)
        else:
            current = 0
            for note in notes:
                try:
                    if float(note.get("press_time", 0.0)) < chart_time:
                        current += 1
                except (TypeError, ValueError):
                    continue
        self.lbl_count_value.setText(f"{current} / {len(notes)}")

    def _on_tick(self):
        playback = getattr(self.player, "playback", None)
        playing = bool(playback is not None and playback.is_playing)
        position = playback.chart_position_ms() if playback is not None else None
        now_ms = time.perf_counter() * 1000.0

        if position is not None:
            self._chart_time = max(0.0, position)
            self._last_tick_ms = now_ms
            self.canvas.set_chart_time(self._chart_time)
        elif not playing and self.canvas.has_active_effects():
            delta = min(max(now_ms - self._last_tick_ms, 0.0), 100.0)
            self._last_tick_ms = now_ms
            if delta > 0:
                self.canvas.advance_for_effects(delta)
                self._chart_time = self.canvas.chart_time

        self._update_bpm_display(now_ms)
        self._update_count(self.canvas.notes, self._chart_time)

    def showEvent(self, event):
        super().showEvent(event)
        self._last_tick_ms = time.perf_counter() * 1000.0
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._timer.stop()
        player = self.player
        if player is not None:
            player._on_rhythm_hint_closed()
        event.accept()
