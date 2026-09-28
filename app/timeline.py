import random

def _split_allowed(allowed, left_keys, right_keys):
    left_allowed = []
    right_allowed = []
    for key in allowed:
        if left_keys is not None and key in left_keys:
            left_allowed.append(key)
        elif right_keys is not None and key in right_keys:
            right_allowed.append(key)
    return left_allowed, right_allowed

def _project_key_to_allowed(key, allowed, left_keys, right_keys, fallback_idx):
    if key is None:
        return allowed[fallback_idx % len(allowed)]
    if left_keys is not None and key in left_keys:
        allowed_left = [k for k in allowed if k in left_keys]
        if allowed_left:
            return allowed_left[left_keys.index(key) % len(allowed_left)]
    if right_keys is not None and key in right_keys:
        allowed_right = [k for k in allowed if k in right_keys]
        if allowed_right:
            return allowed_right[right_keys.index(key) % len(allowed_right)]
    return allowed[fallback_idx % len(allowed)]

def _project_group_to_allowed(keys, allowed, left_keys, right_keys):
    count = len(keys)
    if count == 0:
        return [], False
    left_allowed, right_allowed = _split_allowed(allowed, left_keys, right_keys)
    left_cap = len(left_allowed)
    right_cap = len(right_allowed)
    left_orig = sum(1 for k in keys if left_keys is not None and k in left_keys)
    right_orig = sum(1 for k in keys if right_keys is not None and k in right_keys)
    if left_orig <= left_cap and right_orig <= right_cap:
        return [
            _project_key_to_allowed(key, allowed, left_keys, right_keys, i)
            for i, key in enumerate(keys)
        ], False
    total_cap = left_cap + right_cap
    if count > total_cap:
        return [
            _project_key_to_allowed(key, allowed, left_keys, right_keys, i)
            for i, key in enumerate(keys)
        ], False
    if right_cap > left_cap:
        right_n = min(right_cap, (count + 1) // 2)
        left_n = count - right_n
    elif left_cap > right_cap:
        left_n = min(left_cap, (count + 1) // 2)
        right_n = count - left_n
    else:
        if right_orig >= left_orig:
            right_n = min(right_cap, (count + 1) // 2)
            left_n = count - right_n
        else:
            left_n = min(left_cap, (count + 1) // 2)
            right_n = count - left_n
    if left_n > left_cap:
        left_n = left_cap
        right_n = count - left_n
    if right_n > right_cap:
        right_n = right_cap
        left_n = count - right_n
    left_selected = left_allowed[:left_n]
    right_selected = right_allowed[:right_n]
    left_fill = 0
    right_fill = 0
    rem_left = left_n
    rem_right = right_n
    result = []
    last_hand = None
    for key in keys:
        if left_keys is not None and key in left_keys:
            orig_hand = "left"
        elif right_keys is not None and key in right_keys:
            orig_hand = "right"
        else:
            orig_hand = None
        if last_hand is None:
            if orig_hand == "left" and rem_left > 0:
                hand = "left"
            elif orig_hand == "right" and rem_right > 0:
                hand = "right"
            elif rem_left > 0:
                hand = "left"
            else:
                hand = "right"
        elif last_hand == "left" and rem_right > 0:
            hand = "right"
        elif last_hand == "right" and rem_left > 0:
            hand = "left"
        elif rem_left > 0:
            hand = "left"
        else:
            hand = "right"
        if hand == "left":
            result.append(left_selected[left_fill])
            left_fill += 1
            rem_left -= 1
            last_hand = "left"
        else:
            result.append(right_selected[right_fill])
            right_fill += 1
            rem_right -= 1
            last_hand = "right"
    return result, True

def build_timeline(macro_key_info, custom_keys, press_duration,
                   key_assignments=None, key_hold_ms=None, speed=1.0,
                   key_allowed=None, left_keys=None, right_keys=None,
                   key_groups=None,
                   angles=None,
                   regular_offset_ms=5.0,
                   irregular_offset_ms=10.0):
    """
    生成時間軸
    :param angles: 一個 list，包含每個按鍵對應的軌道角度。
    :param regular_offset_ms: 規則角度（或雙押/三連音）的隨機偏移量，預設 ±5ms。
    :param irregular_offset_ms: 不規則角度的隨機偏移量，預設 ±10ms。
    """
    timeline = []
    press_duration = max(1, int(press_duration or 40))
    press_duration = press_duration * max(speed, 1e-9)
    if not macro_key_info or not custom_keys:
        return timeline

    projected = {}
    if key_assignments and key_groups and key_allowed:
        buckets = {}
        for i in range(len(macro_key_info)):
            allowed = key_allowed[i] if i < len(key_allowed) else None
            if not allowed:
                continue
            group_id = key_groups[i] if i < len(key_groups) else None
            if group_id is None:
                continue
            bucket_key = (group_id, tuple(allowed))
            buckets.setdefault(bucket_key, []).append(i)
        for (_, allowed_tuple), indexes in buckets.items():
            allowed = list(allowed_tuple)
            original_keys = [key_assignments[i] for i in indexes]
            mapped, rebalanced = _project_group_to_allowed(
                original_keys, allowed, left_keys, right_keys
            )
            if rebalanced:
                for idx, key in zip(indexes, mapped):
                    projected[idx] = key

    presses = []
    current_allowed = None
    segment_idx = 0
    for i, key_info in enumerate(macro_key_info):
        if key_assignments:
            key = key_assignments[i]
        else:
            key = custom_keys[i % len(custom_keys)]
        allowed = key_allowed[i] if key_allowed and i < len(key_allowed) else None
        if allowed:
            if allowed != current_allowed:
                current_allowed = allowed
                segment_idx = 0
            if key_assignments:
                if i in projected:
                    key = projected[i]
                elif key not in allowed:
                    key = _project_key_to_allowed(
                        key, allowed, left_keys, right_keys, segment_idx
                    )
            else:
                key = allowed[segment_idx % len(allowed)]
            segment_idx += 1
        else:
            current_allowed = None
            segment_idx = 0
        hold_ms = key_hold_ms[i] if key_hold_ms is not None else None
        presses.append((key_info['press_time'], key, key_info['is_hold'],
                        key_info['release_time'], hold_ms))

    events = []
    # 定義規則角度集合 (0, 90, 180, 270, 360)
    REGULAR_ANGLES = {0, 90, 180, 270, 360}
    TOLERANCE = 2.0 # 允許 2 度的誤差

    def is_regular_angle(angle):
        if angle is None:
            return True
        norm_angle = angle % 360
        for ra in REGULAR_ANGLES:
            if abs(norm_angle - (ra % 360)) < TOLERANCE:
                return True
        return False

    for idx, (press_time, key, is_hold, release_time, hold_ms) in enumerate(presses):
        if is_hold and release_time is not None:
            lift_time = release_time
        elif hold_ms is not None:
            lift_time = press_time + max(1, float(hold_ms))
        else:
            lift_time = press_time + press_duration

        # ================= 核心邏輯：判斷偏移量 =================
        current_offset = regular_offset_ms # 預設使用正常偏移
        
        # 1. 檢查是否為雙押/三連音 (multi_count > 1)
        is_multi_press = False
        if idx < len(macro_key_info):
            if macro_key_info[idx].get('multi_count', 1) > 1:
                is_multi_press = True
                
        # 2. 如果不是多押，才去檢查角度是否不規則
        if not is_multi_press:
            if angles is not None and idx < len(angles):
                angle = angles[idx]
                if not is_regular_angle(angle):
                    current_offset = irregular_offset_ms
        # ========================================================

        press_time += random.uniform(-current_offset, current_offset)
        lift_time += random.uniform(-current_offset, current_offset)

        # 保護機制：防止極端情況下抬起時間早於按下時間
        if lift_time <= press_time:
            lift_time = press_time + 0.1

        events.append((press_time, key, "D"))
        events.append((lift_time, key, "U"))

    events.sort(key=lambda x: x[0])
    return events