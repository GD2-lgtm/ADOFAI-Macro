import heapq
import math
import time
from bisect import bisect_left, bisect_right

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from ..multipress import annotate_multi_press, track_angle_limit
from .. import i18n


LANE_CHOICES = (4, 8)
DIVISIONS = (4, 8, 16, 32)

HIT_EFFECT_MS = 320.0
HIT_BOX_MAX_SCALE = 2.4

LEFT_NOTE_COLOR = QColor("#e8590c")
RIGHT_NOTE_COLOR = QColor("#2f7fb5")
NOTE_EDGE_COLOR = QColor("#ffffff")

LANE_LINE_COLOR = QColor(255, 255, 255, 80)
LANE_LINE_WIDTH = 1.4
BEAT_LINE_COLOR = QColor(255, 255, 255, 78)
BEAT_LINE_STRONG_COLOR = QColor(255, 255, 255, 155)
JUDGE_LINE_COLOR = QColor(255, 255, 255, 170)
CAP_FILL_COLOR = QColor(26, 33, 42)
CAP_EDGE_COLOR = QColor(86, 96, 110)

WINDOW_STYLE = """
QDialog { background: #0b0f14; }
"""


class _FallingNotesCanvas(QWidget):

    LEAD_MS = 1500.0
    JUDGE_LINE_RATIO = 0.86
    JUDGE_LINE_RATIO_8K = 0.82
    NOTE_HEIGHT = 22.0
    LANE_PADDING_RATIO = 0.10
    LOWER_ROW_SCALE = 0.84
    LOWER_LEFT_NOTE_COLOR = QColor("#ff0000")        
    LOWER_RIGHT_NOTE_COLOR = QColor("#0000ff")       
    LOWER_ROW_BALL_RATIO = 0.45
    LOWER_ROW_BALL_COLOR = QColor("#000000")
    LOWER_ROW_BALL_EDGE_COLOR = QColor(210, 220, 232, 210)
    LOWER_ROW_BALL_EDGE_WIDTH = 0.8
    LOWER_ROW_EDGE_WIDTH = 1.8
    CAP_16K_ROW_GAP_RATIO = 0.20
    CAP_16K_ROW_GAP_MIN = 8.0
    CAP_HEIGHT_RATIO = 0.06
    CAP_HEIGHT_MIN = 10.0
    CAP_HEIGHT_MAX = 44.0
    CAP_LINE_GAP_RATIO = 0.025
    CAP_LINE_GAP_MIN = 4.0
    CAP_BOTTOM_MARGIN_RATIO = 0.015
    CAP_PRESS_MS = 180.0
    CAP_PRESS_MIN_SCALE = 0.70
    CAP_PRESS_SHRINK_RATIO = 0.35

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 320)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.notes = []
        self._press_times = []
        self._active_holds = set()
        self._hold_release_heap = []
        self._hold_add_index = 0
        self._multi_display_span_ms = 0.0
        self.lanes = LANE_CHOICES[0]
        self.chart_time = 0.0
        self.bpm = 0.0
        self.speed_scale = 1.0
        self.division = 4
        self.multi_press_enabled = True
        self.hit_effect_enabled = False
        self._angles = None
        self._bpm_points = []
        self._effects = []
        self._hit_events = []
        self._hit_index = 0

    @property
    def placeholder(self):
        return i18n.tr("canvas.placeholder")

    def set_lanes(self, lanes):
        try:
            value = int(lanes)
        except (TypeError, ValueError):
            value = LANE_CHOICES[0]
        self.lanes = value if value in LANE_CHOICES else LANE_CHOICES[0]
        self.update()

    def set_notes(self, notes, angles=None, bpm_points=None, annotate_multi=True):


        pairs = []
        for index, note in enumerate(notes or []):
            try:
                item = dict(note)
            except (TypeError, ValueError):
                continue
            angle = None
            if angles is not None:
                try:
                    angle = angles[index]
                except (IndexError, TypeError):
                    angle = None
            pairs.append((item, angle))

        pairs.sort(key=lambda pair: self._press_of(pair[0]))
        self.notes = [pair[0] for pair in pairs]
        self._press_times = [self._press_of(note) for note in self.notes]
        self._angles = [pair[1] for pair in pairs]
        self._bpm_points = self._normalize_bpm_points(bpm_points)
        if annotate_multi:
            self._reannotate()
        else:
            self._apply_precomputed_multi_display()
        self._rebuild_hit_events()
        self._rebuild_hold_tracking()
        self._effects.clear()
        self.update()

    def set_multi_press_enabled(self, enabled):
        self.multi_press_enabled = bool(enabled)
        self._rebuild_hit_events()
        self.update()

    def set_hit_effect_enabled(self, enabled):
        self.hit_effect_enabled = bool(enabled)
        if not self.hit_effect_enabled:
            self._effects.clear()
        self.update()

    def _normalize_bpm_points(self, bpm_points):
        items = []
        for item in bpm_points or []:
            try:
                time_ms = max(0.0, float(item[0]))
                bpm = float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if bpm > 0:
                items.append((time_ms, bpm))
        items.sort(key=lambda pair: pair[0])
        if not items:
            base = float(self.bpm or 0.0)
            return [(0.0, base)] if base > 0 else []
        if items[0][0] > 0.0:
            base = float(self.bpm or 0.0)
            fallback = base if base > 0 else items[0][1]
            items.insert(0, (0.0, fallback))
        return items

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

    @staticmethod
    def _raw_multi_count(note):
        try:
            count = int(note.get("multi_count", 1) or 1)
        except (TypeError, ValueError, AttributeError):
            return 1
        return count if count >= 2 else 1

    def _reannotate(self):
        if not self.notes:
            return
        limits = [
            track_angle_limit(self._bpm_at(self._press_of(note)))
            for note in self.notes
        ]
        annotate_multi_press(self.notes, self._angles, limit=limits)
        self._apply_precomputed_multi_display()

    def _apply_precomputed_multi_display(self):
        lead_time = None
        max_span = 0.0
        for note in self.notes:
            if self._raw_multi_count(note) < 2:
                note.pop("multi_display_press", None)
                continue
            actual = self._press_of(note)
            if note.get("multi_lead"):
                lead_time = actual
            if lead_time is None:
                note.pop("multi_display_press", None)
                display = actual
            else:
                note["multi_display_press"] = lead_time
                display = lead_time
            try:
                span = max(0.0, actual - float(display))
            except (TypeError, ValueError):
                span = 0.0
            if span > max_span:
                max_span = span
        self._multi_display_span_ms = max_span

    def _rebuild_hit_events(self):
        events = []
        for note in self.notes:
            lane = self._note_lane(note)
            if lane is None:
                continue
            events.append((self._display_press_of(note), lane))
        events.sort(key=lambda item: item[0])
        self._hit_events = events
        self._hit_index = self._count_hits(self.chart_time, strict=True)

    def _count_hits(self, value, strict=False):
        count = 0
        for press, _lane in self._hit_events:
            if press < value or (not strict and press <= value):
                count += 1
            else:
                break
        return count

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

    def active_hold_end_time(self):
        end_time = 0.0
        for index in self._active_holds:
            if index < 0 or index >= len(self.notes):
                continue
            release = self._hold_release_ms(self.notes[index])
            if release is not None and release > end_time:
                end_time = release
        return end_time if end_time > 0.0 else None

    def _rebuild_hold_tracking(self):
        value = self.chart_time
        self._active_holds = set()
        self._hold_release_heap = []
        self._hold_add_index = bisect_right(self._press_times, value)
        for index in range(self._hold_add_index):
            release = self._hold_release_ms(self.notes[index])
            if release is None:
                continue
            expire = release + self.CAP_PRESS_MS
            if expire > value:
                self._active_holds.add(index)
                heapq.heappush(self._hold_release_heap, (expire, index))

    def _advance_hold_tracking(self, value):
        count = len(self._press_times)
        while (self._hold_add_index < count
               and self._press_times[self._hold_add_index] <= value):
            index = self._hold_add_index
            release = self._hold_release_ms(self.notes[index])
            if release is not None:
                expire = release + self.CAP_PRESS_MS
                if expire > value:
                    self._active_holds.add(index)
                    heapq.heappush(self._hold_release_heap, (expire, index))
            self._hold_add_index += 1

        heap = self._hold_release_heap
        while heap and heap[0][0] <= value:
            _, index = heapq.heappop(heap)
            self._active_holds.discard(index)

    def reset_hits(self):
        self._hit_index = self._count_hits(self.chart_time, strict=True)
        self._effects = []
        self._rebuild_hold_tracking()
        self.update()

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
        while (self._hit_index < len(self._hit_events)
               and self._hit_events[self._hit_index][0] <= value):
            if self.hit_effect_enabled:
                self._effects.append((value, self._hit_events[self._hit_index][1]))
            self._hit_index += 1
        if self._effects:
            cutoff = value - HIT_EFFECT_MS
            self._effects = [
                effect for effect in self._effects if effect[0] >= cutoff
            ]
        self.update()

    def has_active_effects(self):
        if not self.hit_effect_enabled:
            return False
        return any(
            self.chart_time - start < HIT_EFFECT_MS
            for start, _lane in self._effects
        )

    def advance_for_effects(self, delta_ms):
        if delta_ms <= 0:
            return
        self.chart_time += delta_ms
        cutoff = self.chart_time - HIT_EFFECT_MS
        self._effects = [
            effect for effect in self._effects if effect[0] >= cutoff
        ]
        self._hit_index = self._count_hits(self.chart_time)
        self._advance_hold_tracking(self.chart_time)
        self.update()

    def set_options(self, speed, division, lanes=None, multi_press=None,
                    hit_effect=None):
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
        if lanes is not None:
            self.set_lanes(lanes)
        if multi_press is not None:
            self.set_multi_press_enabled(multi_press)
        if hit_effect is not None:
            self.set_hit_effect_enabled(hit_effect)
        self.update()

    @staticmethod
    def _press_of(note):
        try:
            return float(note.get("press_time", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _display_press_of(self, note):
        press = self._press_of(note)
        if not self.multi_press_enabled or self._raw_multi_count(note) < 2:
            return press
        aligned = note.get("multi_display_press")
        if aligned is None:
            return press
        try:
            return float(aligned)
        except (TypeError, ValueError):
            return press

    @staticmethod
    def _release_of(note, press):
        raw = note.get("release_time")
        try:
            release = float(raw) if raw is not None else press
        except (TypeError, ValueError):
            release = press
        return release if release > press else press

    def _lane_count(self):
        return self.lanes if self.lanes in LANE_CHOICES else LANE_CHOICES[0]

    def _note_lane(self, note):
        try:
            lane = int(note.get("lane", 0))
        except (TypeError, ValueError):
            return None
        if lane < 0 or lane >= self._lane_count():
            return None
        return lane

    def _is_lower_row(self, note):
        if self._lane_count() != 8:
            return False
        try:
            return int(note.get("key_row", 0) or 0) % 2 == 1
        except (TypeError, ValueError):
            return False

    @classmethod
    def _cap_press_scale(cls, progress):
        if progress < 0.0 or progress >= 1.0:
            return 1.0
        if progress < cls.CAP_PRESS_SHRINK_RATIO:
            t = progress / cls.CAP_PRESS_SHRINK_RATIO
            return 1.0 - (1.0 - cls.CAP_PRESS_MIN_SCALE) * t
        t = (progress - cls.CAP_PRESS_SHRINK_RATIO) / (1.0 - cls.CAP_PRESS_SHRINK_RATIO)
        eased = 1.0 - (1.0 - t) ** 3
        return cls.CAP_PRESS_MIN_SCALE + (1.0 - cls.CAP_PRESS_MIN_SCALE) * eased

    @classmethod
    def _cap_hold_scale(cls, press, release, chart_time):

        shrink_ms = max(1.0, cls.CAP_PRESS_MS * cls.CAP_PRESS_SHRINK_RATIO)
        recover_ms = max(1.0, cls.CAP_PRESS_MS * (1.0 - cls.CAP_PRESS_SHRINK_RATIO))
        if chart_time < release:
            t = min(1.0, max(0.0, (chart_time - press) / shrink_ms))
            eased = 1.0 - (1.0 - t) ** 3
            return 1.0 - (1.0 - cls.CAP_PRESS_MIN_SCALE) * eased
        t = min(1.0, max(0.0, (chart_time - release) / recover_ms))
        eased = 1.0 - (1.0 - t) ** 3
        return cls.CAP_PRESS_MIN_SCALE + (1.0 - cls.CAP_PRESS_MIN_SCALE) * eased

    def _cap_scale_of(self, note, now):
        lane = self._note_lane(note)
        if lane is None:
            return None
        row = 1 if self._is_lower_row(note) else 0
        press = self._display_press_of(note)
        if press > now:
            return None
        release = self._release_of(note, press)
        if bool(note.get("is_hold")) and release > press:
            scale = self._cap_hold_scale(press, release, now)
        else:
            progress = (now - press) / self.CAP_PRESS_MS
            if progress >= 1.0:
                return None
            scale = self._cap_press_scale(progress)
        return (row, lane), scale

    def _cap_scales(self):

        now = self.chart_time
        result = {}

        def apply(index):
            value = self._cap_scale_of(self.notes[index], now)
            if value is None:
                return
            key, scale = value
            if key not in result or scale < result[key]:
                result[key] = scale

        recent_start = bisect_left(
            self._press_times, now - self.CAP_PRESS_MS
        )
        multi_window_ms = 0.0
        if self.multi_press_enabled:
            multi_window_ms = max(
                0.0, float(getattr(self, "_multi_display_span_ms", 0.0))
            )
        recent_end = bisect_right(
            self._press_times, now + multi_window_ms
        )
        for index in range(recent_start, recent_end):
            apply(index)
        for index in self._active_holds:
            if index < recent_start:
                apply(index)
        return result

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
        gradient.setColorAt(1.0, QColor("#1a212b"))
        painter.fillRect(rect, QBrush(gradient))

        lanes = self._lane_count()
        lane_w = float(width) / float(lanes)

        cap_height = max(
            self.CAP_HEIGHT_MIN,
            min(float(height) * self.CAP_HEIGHT_RATIO, self.CAP_HEIGHT_MAX),
        )
        cap_bottom = float(height) - float(height) * self.CAP_BOTTOM_MARGIN_RATIO

        two_layer_caps = lanes == 8
        cap_upper_h = cap_height
        if two_layer_caps:
            cap_row_gap = max(
                self.CAP_16K_ROW_GAP_MIN,
                cap_height * self.CAP_16K_ROW_GAP_RATIO,
            )
            cap_lower_h = cap_upper_h
        else:
            cap_row_gap = 0.0
            cap_lower_h = 0.0
        cap_total_h = cap_upper_h + cap_row_gap + cap_lower_h
        cap_top = cap_bottom - cap_total_h
        cap_center_y = cap_top + cap_upper_h * 0.5
        cap_lower_center_y = (
            cap_top + cap_upper_h + cap_row_gap + cap_lower_h * 0.5
        )
        cap_gap = max(self.CAP_LINE_GAP_MIN, float(height) * self.CAP_LINE_GAP_RATIO)
        judge_ratio = (
            self.JUDGE_LINE_RATIO_8K if two_layer_caps else self.JUDGE_LINE_RATIO
        )
        judge_y = max(float(height) * judge_ratio, cap_top - cap_gap)
        cap_padding = max(3.0, lane_w * self.LANE_PADDING_RATIO)
        cap_width = max(4.0, lane_w - cap_padding * 2.0)

        speed_scale = self.speed_scale if self.speed_scale > 0 else 1.0
        px_per_ms = judge_y / self.LEAD_MS * speed_scale

        self._draw_beat_lines(painter, width, judge_y, px_per_ms)

        pen = QPen(LANE_LINE_COLOR)
        pen.setWidthF(LANE_LINE_WIDTH)
        painter.setPen(pen)
        for index in range(1, lanes):
            x = lane_w * index
            painter.drawLine(QPointF(x, 0.0), QPointF(x, float(height)))

        pen = QPen(JUDGE_LINE_COLOR)
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(0.0, judge_y), QPointF(float(width), judge_y))

        cap_scales = self._cap_scales()

        def draw_cap(center_x, center_y, box_w, box_h):
            painter.setPen(QPen(CAP_EDGE_COLOR, 1.6))
            painter.setBrush(QBrush(CAP_FILL_COLOR))
            painter.drawRoundedRect(
                QRectF(
                    center_x - box_w * 0.5,
                    center_y - box_h * 0.5,
                    box_w,
                    box_h,
                ),
                4.0,
                4.0,
            )

        for lane in range(lanes):
            upper_scale = cap_scales.get((0, lane), 1.0)
            center_x = lane * lane_w + lane_w * 0.5
            upper_w = cap_width * upper_scale
            upper_h = cap_upper_h * upper_scale
            draw_cap(center_x, cap_center_y, upper_w, upper_h)
            if two_layer_caps:
                lower_scale = cap_scales.get((1, lane), 1.0)
                lower_w = cap_width * lower_scale
                lower_h = cap_lower_h * lower_scale
                draw_cap(center_x, cap_lower_center_y, lower_w, lower_h)

        if not self.notes:
            painter.setPen(QColor("#66717f"))
            font = QFont(self.font())
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self.placeholder)
            painter.end()
            return

        multi_span = 0.0
        if self.multi_press_enabled:
            multi_span = max(
                0.0, float(getattr(self, "_multi_display_span_ms", 0.0))
            )
        visible_lo = (
            self.chart_time - self.NOTE_HEIGHT * 3.0 / px_per_ms
        )
        visible_hi = (
            self.chart_time
            + (judge_y + self.NOTE_HEIGHT * 3.0) / px_per_ms
            + multi_span
        )
        start = bisect_left(self._press_times, visible_lo)
        end = bisect_right(self._press_times, visible_hi)

        for lower_pass in (False, True):
            for index in range(start, end):
                note = self.notes[index]
                if self._is_lower_row(note) != lower_pass:
                    continue
                self._draw_note(painter, note, lane_w, judge_y, px_per_ms)
            for index in self._active_holds:
                if index >= start:
                    continue
                note = self.notes[index]
                if self._is_lower_row(note) != lower_pass:
                    continue
                self._draw_note(painter, note, lane_w, judge_y, px_per_ms)
        self._draw_hit_effects(painter, lane_w, judge_y)
        painter.end()

    def _draw_beat_lines(self, painter, width, judge_y, px_per_ms):
        if self.bpm <= 0 or self.division not in DIVISIONS or px_per_ms <= 0:
            return
        beat_ms = 60000.0 / self.bpm
        interval_ms = beat_ms * (4.0 / self.division)
        if interval_ms <= 0:
            return
        lead_ms = judge_y / px_per_ms
        first = int(math.floor(self.chart_time / interval_ms))
        last = int(math.ceil((self.chart_time + lead_ms) / interval_ms))
        for k in range(first, last + 1):
            y = judge_y - (k * interval_ms - self.chart_time) * px_per_ms
            if y < 0.0 or y > judge_y:
                continue
            if k % self.division == 0:
                pen = QPen(BEAT_LINE_STRONG_COLOR, 2.2)
            else:
                pen = QPen(BEAT_LINE_COLOR, 1.4)
            painter.setPen(pen)
            painter.drawLine(QPointF(0.0, y), QPointF(float(width), y))

    def _draw_hit_effects(self, painter, lane_w, judge_y):
        if not self.hit_effect_enabled or not self._effects:
            return
        pad = max(3.0, lane_w * self.LANE_PADDING_RATIO)
        base_w = max(4.0, lane_w - pad * 2.0)
        base_h = self.NOTE_HEIGHT
        for start, lane in self._effects:
            progress = (self.chart_time - start) / HIT_EFFECT_MS
            if progress < 0.0 or progress > 1.0:
                continue
            scale = 1.0 + progress * (HIT_BOX_MAX_SCALE - 1.0)
            box_w = base_w * scale
            box_h = base_h * scale
            alpha = int(235 * (1.0 - progress))
            if alpha <= 0:
                continue
            pen = QPen(
                QColor(255, 255, 255, alpha),
                max(1.0, self.NOTE_HEIGHT * 0.09 * (1.0 - progress * 0.7)),
            )
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            x = (lane + 0.5) * lane_w - box_w * 0.5
            y = judge_y - box_h * 0.5
            radius = min(box_h * 0.18, 6.0)
            painter.drawRoundedRect(QRectF(x, y, box_w, box_h), radius, radius)

    def _draw_note(self, painter, note, lane_w, judge_y, px_per_ms):
        lane = self._note_lane(note)
        if lane is None:
            return
        press = self._display_press_of(note)
        release = self._release_of(note, press)
        is_hold = bool(note.get("is_hold")) and release > press

        per_hand = max(1, self._lane_count() // 2)

        lower_row = self._is_lower_row(note)
        if lane < per_hand:
            color = (
                self.LOWER_LEFT_NOTE_COLOR if lower_row else LEFT_NOTE_COLOR
            )
        else:
            color = (
                self.LOWER_RIGHT_NOTE_COLOR if lower_row else RIGHT_NOTE_COLOR
            )

        scale = self.LOWER_ROW_SCALE if lower_row else 1.0
        note_h = self.NOTE_HEIGHT * scale
        pad = max(3.0, lane_w * self.LANE_PADDING_RATIO)
        full_w = max(4.0, lane_w - pad * 2.0)
        note_w = max(3.0, full_w * scale)
        left = lane * lane_w + (lane_w - note_w) * 0.5
        head_y = judge_y - (press - self.chart_time) * px_per_ms
        base_stroke = max(1.6, note_h * 0.10)
        stroke = (
            max(base_stroke, self.LOWER_ROW_EDGE_WIDTH)
            if lower_row else base_stroke
        )

        def draw_ball(center_x, center_y):
            if not lower_row:
                return
            radius = note_h * self.LOWER_ROW_BALL_RATIO
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.LOWER_ROW_BALL_COLOR))
            painter.drawEllipse(QPointF(center_x, center_y), radius, radius)
            if radius >= 2.0:
                painter.setPen(
                    QPen(
                        self.LOWER_ROW_BALL_EDGE_COLOR,
                        self.LOWER_ROW_BALL_EDGE_WIDTH,
                    )
                )
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(center_x, center_y), radius, radius)

        if not is_hold:
            if head_y > judge_y:
                return
            if head_y < -note_h * 3.0:
                return
            painter.setPen(QPen(NOTE_EDGE_COLOR, stroke))
            painter.setBrush(QBrush(color))
            rect = QRectF(left, head_y - note_h * 0.5, note_w, note_h)
            painter.drawRoundedRect(rect, 4.0, 4.0)
            draw_ball(rect.center().x(), rect.center().y())
            return

        tail_y = judge_y - (release - self.chart_time) * px_per_ms
        if tail_y >= judge_y:
            return
        if head_y < -note_h * 3.0:
            return

        stick_y = min(head_y, judge_y)
        top = max(tail_y, 0.0)
        bottom = max(stick_y, top + 1.0)
        painter.save()
        painter.setClipRect(
            QRectF(0.0, 0.0, float(self.width()), judge_y + 1.0)
        )
        painter.setPen(QPen(NOTE_EDGE_COLOR, max(1.0, stroke * 0.7)))
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(
            QRectF(left, top, note_w, bottom - top),
            note_h * 0.30,
            note_h * 0.30,
        )
        painter.restore()

        painter.setPen(QPen(NOTE_EDGE_COLOR, stroke))
        painter.setBrush(QBrush(color))
        head_rect = QRectF(left, stick_y - note_h * 0.5, note_w, note_h)
        painter.drawRoundedRect(head_rect, 4.0, 4.0)
        draw_ball(head_rect.center().x(), head_rect.center().y())


class FallingNotesWindow(QDialog):

    DEFAULT_WIDTH = 380
    DEFAULT_HEIGHT = 820
    MIN_WIDTH = 260
    MIN_HEIGHT = 460

    def __init__(self, player, size=None):
        super().__init__(None)
        self.player = player
        i18n.title(self, "window.falling_notes")
        self.setModal(False)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(*self._clamp_size(size))
        self.setStyleSheet(WINDOW_STYLE)

        self._chart_time = 0.0
        self._base_bpm = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 0)
        root.setSpacing(0)

        self.canvas = _FallingNotesCanvas()
        root.addWidget(self.canvas)

    @classmethod
    def _clamp_size(cls, size):
        if not size:
            return cls.DEFAULT_WIDTH, cls.DEFAULT_HEIGHT
        try:
            width = max(cls.MIN_WIDTH, int(size[0]))
            height = max(cls.MIN_HEIGHT, int(size[1]))
        except (TypeError, ValueError, IndexError):
            return cls.DEFAULT_WIDTH, cls.DEFAULT_HEIGHT
        return width, height

    def reset_size(self):
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def set_options(self, speed, division, lanes=None, multi_press=None,
                    hit_effect=None):
        self.canvas.set_options(
            speed, division, lanes, multi_press, hit_effect
        )

    def set_chart(self, bpm, notes, lanes=None, bpm_points=None, angles=None,
                  annotate_multi=True):

        self._chart_time = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0
        self._base_bpm = self._bpm_value(bpm)
        self.canvas.bpm = self._base_bpm
        if lanes is not None:
            self.canvas.set_lanes(lanes)
        self.canvas.set_notes(notes, angles, bpm_points, annotate_multi)
        self.canvas.set_chart_time(0.0)
        self.canvas.reset_hits()

    def reset_position(self):
        self._chart_time = 0.0
        self._last_tick_ms = time.perf_counter() * 1000.0
        self.canvas.set_chart_time(0.0)
        self.canvas.reset_hits()

    def release_active_holds(self):
        end_time = self.canvas.active_hold_end_time()
        if end_time is None:
            return
        target = max(self._chart_time, end_time + 0.001)
        if target <= self._chart_time:
            return
        self._chart_time = target
        self._last_tick_ms = time.perf_counter() * 1000.0
        self.canvas.set_chart_time(target)

    @staticmethod
    def _bpm_value(bpm):
        try:
            value = float(bpm)
        except (TypeError, ValueError):
            return 0.0
        return value if value > 0 else 0.0

    def _on_tick(self):
        playback = getattr(self.player, "playback", None)
        if playback is None:
            return
        playing = bool(playback.is_playing)
        position = playback.chart_position_ms()
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
            player._on_falling_notes_closed()
        event.accept()
