import math
from collections import Counter as _Cnt

STYLE_NAMES = ["内轮"]
STYLE_NAMES_LEGACY = ["内轮"]

_KEY_COUNT = 16
_HAND_MAX = 16
_TIER_SIZE = 4
_TIER_COUNT = 4
_DEFAULT_HOLD = 50.0


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def map_key_number(key_num, left_keys, right_keys):
    key_num = int(key_num)
    if key_num < 1 or key_num > 32:
        return None

    group = (key_num - 1) // 4
    side = "right" if group % 2 == 1 else "left"
    tier = (key_num - 1) // 8
    pos = (key_num - 1) % 4

    idx = tier * _TIER_SIZE + pos
    if side == "left":
        return left_keys[idx % len(left_keys)] if left_keys else None
    else:
        return right_keys[idx % len(right_keys)] if right_keys else None


class AdvancedTechnique:

    def __init__(self, left_keys, right_keys, single_finger_bpm=400.0,
                 main_hand="right"):
        self.left_keys = list(left_keys)
        self.right_keys = list(right_keys)
        self.single_finger_bpm = float(single_finger_bpm)
        self.main_hand = main_hand

    def simulate(self, press_times_ms):
        n = len(press_times_ms)
        if n == 0:
            return [], []

        if not self.left_keys or not self.right_keys:
            all_keys = self.left_keys + self.right_keys
            if not all_keys:
                return [None] * n, [_DEFAULT_HOLD] * n
            return [all_keys[i % len(all_keys)] for i in range(n)], [_DEFAULT_HOLD] * n

        TIME = [t / 1000.0 for t in press_times_ms]
        press_key = self._build_press_key_numbers(
            TIME, len(self.left_keys), len(self.right_keys)
        )
        if len(press_key) < n:
            last = press_key[-1] if press_key else 1
            press_key = press_key + [last] * (n - len(press_key))
        elif len(press_key) > n:
            press_key = press_key[:n]

        assignments = [map_key_number(k, self.left_keys, self.right_keys) for k in press_key]
        hold_ms = self._build_hold_ms(press_key, TIME)
        return assignments, hold_ms

    def _build_press_key_numbers(self, TIME, left_size, right_size):
        n = len(TIME)
        if n < 1:
            return []

        right_hand = [5, 6, 7, 8, 13, 14, 15, 16,
                      21, 22, 23, 24, 29, 30, 31, 32]
        left_hand = [4, 3, 2, 1, 12, 11, 10, 9,
                     20, 19, 18, 17, 28, 27, 26, 25]
        thr = 60.0 / (self.single_finger_bpm * 2)
        main_hand_parity = 1 if self.main_hand == "right" else 0

        TL = 0
        group_count = 0
        plus = 0
        minus = 0.0
        K = 0
        lastkey = 0
        lk = 0
        WHOAMI = 0
        press_key = []
        append = press_key.append

        def flush_group():
            nonlocal TL, plus, lastkey, lk, WHOAMI, group_count

            if group_count <= 0:
                return

            chunks = []
            used = 0
            for _ in range(math.ceil(group_count / _HAND_MAX)):
                value = _clamp(group_count - used, 0, _HAND_MAX)
                chunks.append(value)
                used += value

            idx1 = TL - (group_count - 1)
            couple = lastkey if (plus & 1) == main_hand_parity else lk
            idx2 = (TL - group_count) - couple
            seg = TIME[idx1 - 1] - TIME[idx2 - 1]
            speed = (60.0 / seg) if seg != 0 else float("inf")

            if self.single_finger_bpm > speed:
                if WHOAMI != 1:
                    plus = 1
                else:
                    plus = plus + 1 if (plus & 1) == main_hand_parity else 1
                    WHOAMI = 0
            else:
                plus += 1

            used = 0
            for _ in range(len(chunks)):
                cur = chunks[0]
                group_count = cur
                hand = right_hand if (plus & 1) == main_hand_parity else left_hand
                group_start = len(press_key)

                remaining = int(_clamp(cur - used, 0, _HAND_MAX))
                tier = 0
                while remaining > 0 and tier < _TIER_COUNT:
                    k = remaining if remaining < _TIER_SIZE else _TIER_SIZE
                    base = tier * _TIER_SIZE
                    for off in range(k - 1, -1, -1):
                        pos = base + off
                        append(hand[pos] if 0 <= pos < _HAND_MAX else 0)
                    remaining -= k
                    tier += 1

                if cur == 4 and len(press_key) - group_start == 4:
                    gi = group_start
                    if gi >= 1 and gi + 3 < len(TIME):
                        ts = TIME[gi:gi + 4]
                        gaps = [round(ts[j + 1] - ts[j], 6) for j in range(3)]
                        cnt = _Cnt(gaps)
                        has_dup = any(v >= 2 for v in cnt.values())
                        not_all_same = len(cnt) > 1
                        keys4 = press_key[gi:gi + 4]
                        if has_dup and not_all_same and all(1 <= k <= 8 for k in keys4):
                            hand_size = left_size if keys4[0] <= 4 else right_size
                            if hand_size >= 8:
                                d = keys4[3]
                                press_key[gi] = keys4[1]
                                press_key[gi + 1] = keys4[2]
                                press_key[gi + 2] = keys4[3]
                                press_key[gi + 3] = d + 8

                used = 0
                chunks.pop(0)
                if chunks:
                    plus += 1
                    WHOAMI = 1

            if (plus & 1) == main_hand_parity:
                lastkey = group_count - 1
                lk += group_count - 1
            else:
                lk = group_count - 1
                lastkey += group_count - 1

        for _ in range(n):
            K += 1
            if minus < thr and K <= n - 1:
                TL += 1
                minus += TIME[TL] - TIME[TL - 1]
                group_count += 1
            else:
                flush_group()
                group_count = 0
                minus = 0.0
                TL += 1
                if TL + 1 <= n:
                    minus += TIME[TL] - TIME[TL - 1]
                group_count += 1

        if group_count > 0:
            flush_group()

        return press_key

    def _build_hold_ms(self, press_key, TIME):
        n = len(TIME)
        full_hold = [_DEFAULT_HOLD] * n
        if n == 0:
            return full_hold

        raw = []
        for i, key_num in enumerate(press_key):
            if i < 1 or key_num < 1 or i >= n:
                continue
            raw.append((key_num, TIME[i] * 1000.0))

        m = len(raw)
        if m == 0:
            return full_hold

        kid = [r[0] for r in raw]
        t = [r[1] for r in raw]
        hold = [_DEFAULT_HOLD] * m

        ns = [-1.0] * m
        last = {}
        for i in range(m - 1, -1, -1):
            k = kid[i]
            if k in last:
                ns[i] = t[last[k]]
            last[k] = i

        def target_of(k):
            if k == 4 or k == 5:
                return 0
            return k - 1 if k > 4 else k + 1

        for i in range(m):
            k = kid[i]
            target = target_of(k)
            if 1 <= target <= _KEY_COUNT and i + 1 < m and kid[i + 1] == target:
                continue
            if ns[i] < 0:
                continue
            gap = ns[i] - t[i]
            hold[i] = gap * 4.0 / 6.0 if gap * 5.0 / 6.0 < _DEFAULT_HOLD else _DEFAULT_HOLD

        for i in range(m - 1, -1, -1):
            k = kid[i]
            target = target_of(k)
            h = _DEFAULT_HOLD
            if 1 <= target <= _KEY_COUNT and i + 1 < m and kid[i + 1] == target:
                h = t[i + 1] - t[i] + hold[i + 1]
            hold[i] = h

        for i in range(m):
            if kid[i] <= 8:
                continue
            if ns[i] < 0:
                hold[i] = _DEFAULT_HOLD
                continue
            gap = ns[i] - t[i]
            hold[i] = gap * 4.0 / 6.0 if gap * 5.0 / 6.0 < _DEFAULT_HOLD else _DEFAULT_HOLD

        for idx, i in enumerate(range(1, m + 1)):
            if i < n:
                full_hold[i] = hold[idx]

        return full_hold
