MULTI_PRESS_GAP_MS = 50.0

MULTI_PRESS_TRACK_ANGLE_DEG = 15.0

MULTI_PRESS_TRACK_ANGLE_DEG_FAST = 30.0

MULTI_PRESS_FAST_BPM = 300.0

MULTI_PRESS_MAX_COUNT = 0

MULTI_PRESS_WINDOW_MS = 100.0

MULTI_PRESS_ANGLE_EPS = 1e-9


def track_angle(turn):
    if turn is None:
        return None
    try:
        value = float(turn)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if value == 999.0:             
        return None
    if value < 0.0:
        value %= 360.0
    return value


def track_angle_limit(bpm):
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        value = 0.0
    if value >= MULTI_PRESS_FAST_BPM:
        return MULTI_PRESS_TRACK_ANGLE_DEG_FAST
    return MULTI_PRESS_TRACK_ANGLE_DEG


def _limit_of(limits, index):
    if isinstance(limits, (list, tuple)):
        if 0 <= index < len(limits):
            value = limits[index]
        else:
            return MULTI_PRESS_TRACK_ANGLE_DEG
    else:
        value = limits
    try:
        return float(value)
    except (TypeError, ValueError):
        return MULTI_PRESS_TRACK_ANGLE_DEG


def _resolve_angles(angles, count):
    if angles is None:
        return [None] * count
    resolved = [track_angle(a) for a in list(angles)[:count]]
    resolved += [None] * (count - len(resolved))
    return resolved


def _press_time(note):
    try:
        return float(note.get("press_time", 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _gap_ok(notes, index, gap_ms):
    if gap_ms is None:
        return True
    try:
        limit = float(gap_ms)
    except (TypeError, ValueError):
        return True
    if limit <= 0.0:
        return True
    gap = _press_time(notes[index + 1]) - _press_time(notes[index])
    return 0.0 <= gap < limit


def group_multi_press(notes, angles=None, limit=None,
                      max_count=MULTI_PRESS_MAX_COUNT,
                      gap_ms=MULTI_PRESS_GAP_MS,
                      window_ms=MULTI_PRESS_WINDOW_MS):

    items = list(notes or [])
    count = len(items)
    if count < 2:
        return []

    resolved = _resolve_angles(angles, count)
    cap = None
    if max_count is not None:
        try:
            cap_value = int(max_count)
        except (TypeError, ValueError):
            cap_value = 0
        if cap_value > 0:
            cap = max(2, cap_value)

    window = None
    if window_ms is not None:
        try:
            window_value = float(window_ms)
        except (TypeError, ValueError):
            window_value = 0.0
        if window_value > 0.0:
            window = window_value

    def pair_ok(index):
        if not _gap_ok(items, index, gap_ms):
            return False
        value = resolved[index + 1]
        if value is None:
            return False
        return value <= _limit_of(limit, index + 1) + MULTI_PRESS_ANGLE_EPS

    groups = []
    index = 0
    while index < count - 1:
        if not pair_ok(index):
            index += 1
            continue

        group = [index, index + 1]
        cursor = index + 1
        while cursor < count - 1 and pair_ok(cursor):
            group.append(cursor + 1)
            cursor += 1

        if window is not None:
            span = _press_time(items[group[-1]]) - _press_time(items[group[0]])
            if span > window + 1e-9:
                index = cursor + 1
                continue

        if cap is None:
            groups.append(group)
        else:
            for start in range(0, len(group), cap):
                chunk = group[start:start + cap]
                if len(chunk) >= 2:
                    groups.append(chunk)
        index = cursor + 1
    return groups


def annotate_multi_press(notes, angles=None, limit=None,
                         max_count=MULTI_PRESS_MAX_COUNT,
                         gap_ms=MULTI_PRESS_GAP_MS,
                         window_ms=MULTI_PRESS_WINDOW_MS):

    items = list(notes or [])
    resolved = _resolve_angles(angles, len(items))

    for position, note in enumerate(items):
        if not isinstance(note, dict):
            continue
        note["multi_count"] = 1
        note["multi_slot"] = 0
        note["multi_lead"] = False
        note["multi_angle"] = resolved[position]

    groups = group_multi_press(
        items, angles, limit, max_count, gap_ms, window_ms
    )
    for group in groups:
        size = len(group)
        for slot, position in enumerate(group):
            note = items[position]
            if not isinstance(note, dict):
                continue
            note["multi_count"] = size
            note["multi_slot"] = slot
            note["multi_lead"] = slot == 0
    return len(groups)


if __name__ == "__main__":  
    demo = [
        {"press_time": 0.0},      
        {"press_time": 20.0},     
        {"press_time": 40.0},    
        {"press_time": 240.0},  
        {"press_time": 250.0},    
        {"press_time": 260.0},
    ]
    angles = [0.0, 0.0, 20.0, 30.0, 15.0, 330.0]

    print("轨道夹角:", [(a, track_angle(a)) for a in
                        (0.0, 15.0, 30.0, 180.0, 330.0, 360.0, 999.0, None)])
    print("BPM 210 上限:", track_angle_limit(210),
          " BPM 320 上限:", track_angle_limit(320))
    for bpm in (210.0, 320.0):
        data = [dict(n) for n in demo]
        count = annotate_multi_press(
            data, angles, limit=track_angle_limit(bpm)
        )
        print("BPM=%3.0f -> 组数 %d, multi_count=%s"
              % (bpm, count, [n["multi_count"] for n in data]))
