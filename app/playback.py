import threading
import time

import keyboard

from .console import PERF_FREQ, get_perf_counter_raw
from .keys import KeyInjector, resolve_key_codes


class PlaybackEngine:
    def __init__(self, log_message):
        self.log_message = log_message
        self.injector = KeyInjector()
        self.keys = []
        self._held_keys = set()
        self._key_codes_cache = {}
        self.is_playing = False
        self.offset_ms = 0.0
        self.verbose = True
        self.timeline = []
        self.speed = 1.0
        self._thread = None

        self._keyboard_hooks = []

    def preload_timeline(self, timeline, speed=1.0):
        self.timeline = timeline
        self.speed = speed

    def start(self, verbose, on_stopped=None):
        self.verbose = verbose
        self.is_playing = True
        self._thread = threading.Thread(
            target=self._run,
            kwargs={"on_stopped": on_stopped},
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self.is_playing = False
        self.release_all_keys()

    def adjust_offset(self, delta: float = None, *,
                      step: float = None,
                      multiplier: float = 1.0,
                      absolute: bool = False) -> float:
        if delta is not None:
            actual_delta = float(delta)
        elif step is not None:
            actual_delta = float(step) * multiplier
        else:
            actual_delta = 10.0 * multiplier

        if absolute:
            self.offset_ms = actual_delta
        else:
            self.offset_ms += actual_delta

        return self.offset_ms

    def reset_offset(self):
        self.offset_ms = 0.0
        return 0.0

    def _key_to_codes(self, key):
        codes = self._key_codes_cache.get(key)
        if codes is None:
            codes = self._key_codes_cache[key] = resolve_key_codes(key)
        return codes

    def release_all_keys(self, keys=None):
        keys = keys if keys is not None else self.keys
        for key in keys:
            try:
                code = self._key_to_codes(key)[0]
                if not self.injector.send([self.injector.input_for(code, keyup=True)]):
                    keyboard.release(code)
            except Exception:
                try:
                    keyboard.release(self._key_to_codes(key)[0])
                except Exception:
                    pass
        self._held_keys.clear()

    def _run(self, on_stopped):
        self.log_message("=== Macro 开始 ===", "system")
        try:
            self.release_all_keys()
            speed = self.speed
            ms_per_counter = 1000.0 / PERF_FREQ
            counter_per_ms = PERF_FREQ / 1000.0
            margin_counter = 5.0 * counter_per_ms
            min_sleep_counter = 3.0 * counter_per_ms
            start_counter = get_perf_counter_raw()

            groups = []
            for event_time, key, action in self.timeline:
                base = start_counter + (event_time / speed) * counter_per_ms
                if groups and groups[-1][0] == base:
                    groups[-1][1].append((key, action))
                else:
                    groups.append((base, [(key, action)]))

            est_counter = 2.0 * counter_per_ms

            for base, actions in groups:
                if not self.is_playing:
                    break

                while True:
                    current = get_perf_counter_raw()
                    target = base + self.offset_ms * counter_per_ms
                    wait = target - current
                    if wait <= est_counter:
                        break
                    if wait > margin_counter + min_sleep_counter:
                        time.sleep((wait - margin_counter) * ms_per_counter / 1000.0)

                inputs = []
                for key, action in actions:
                    code = self._key_to_codes(key)[0]
                    if action == "D":
                        if key in self._held_keys:
                            inputs.append(self.injector.input_for(code, keyup=True))
                            self._held_keys.discard(key)
                        inputs.append(self.injector.input_for(code, keyup=False))
                        self._held_keys.add(key)
                    else:
                        inputs.append(self.injector.input_for(code, keyup=True))
                        self._held_keys.discard(key)

                t0 = get_perf_counter_raw()
                ok = self.injector.send(inputs)
                t1 = get_perf_counter_raw()
                est_counter = est_counter * 0.9 + (t1 - t0) * 0.1

                if not ok:
                    for key, action in actions:
                        try:
                            if action == "D":
                                keyboard.press(self._key_to_codes(key)[0])
                            else:
                                keyboard.release(self._key_to_codes(key)[0])
                        except Exception as e:
                            self.log_message(f"按键失败 [{key}]: {e}", "error")
                    self.log_message("SendInput 注入失败,已回退", "error")

                if self.verbose:
                    for key, action in actions:
                        t_ms = (base - start_counter) * ms_per_counter + self.offset_ms
                        if action == "D":
                            self.log_message(f"[{t_ms:.1f}ms] Press {key}", "key")
                        else:
                            self.log_message(f"[{t_ms:.1f}ms] Release {key}", "delay")

            self.log_message("=== Macro 结束 ===", "system")

        except Exception as e:
            self.log_message(f"错误: {e}", "error")
            import traceback
            traceback.print_exc()
        finally:
            self.release_all_keys()
            self.is_playing = False
            if on_stopped:
                on_stopped()
