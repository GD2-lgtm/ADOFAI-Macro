def build_timeline(macro_key_info, custom_keys, press_duration,
                   key_assignments=None, key_hold_ms=None, speed=1.0):
    timeline = []
    press_duration = max(1, int(press_duration or 40))
    press_duration = press_duration * max(speed, 1e-9)

    if not macro_key_info or not custom_keys:
        return timeline

    presses = []
    for i, key_info in enumerate(macro_key_info):
        if key_assignments:
            key = key_assignments[i]
        else:
            key = custom_keys[i % len(custom_keys)]
        hold_ms = key_hold_ms[i] if key_hold_ms is not None else None
        presses.append((key_info['press_time'], key, key_info['is_hold'],
                        key_info['release_time'], hold_ms))

    events = []
    for press_time, key, is_hold, release_time, hold_ms in presses:
        if is_hold and release_time is not None:
            lift_time = release_time
        elif hold_ms is not None:
            lift_time = press_time + max(1, float(hold_ms))
        else:
            lift_time = press_time + press_duration

        events.append((press_time, key, "D"))
        events.append((lift_time, key, "U"))

    events.sort(key=lambda x: x[0])
    return events
