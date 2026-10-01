import threading
import time
import keyboard
from . import i18n
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
        self.key_output_enabled = True
        self.timeline = []
        self.speed = 1.0
        self._thread = None
        self._start_counter = None
        self._keyboard_hooks = []

    def preload_timeline(self, timeline, speed=1.0):
        self.timeline = timeline
        self.speed = speed

    def chart_position_ms(self):
        if not self.is_playing or self._start_counter is None:
            return None
        try:
            elapsed_ms = (
                (get_perf_counter_raw() - self._start_counter)
                * 1000.0
                / PERF_FREQ
            )
        except Exception:
            return None
        return (elapsed_ms - self.offset_ms) * self.speed

    def start(self, verbose, on_stopped=None):
        self.verbose = verbose
        self._start_counter = None
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

    def _release_keys(self, keys):
        codes = []
        for key in keys:
            try:
                codes.append(self._key_to_codes(key)[0])
            except Exception:
                pass
        inputs = []
        for code in codes:
            try:
                inputs.append(self.injector.input_for(code, keyup=True))
            except Exception:
                pass
        if inputs:
            try:
                if not self.injector.send(inputs):
                    for code in codes:
                        try:
                            keyboard.release(code)
                        except Exception:
                            pass
            except Exception:
                for code in codes:
                    try:
                        keyboard.release(code)
                    except Exception:
                        pass
        self._held_keys.clear()

    def release_all_keys(self, keys=None):
        if keys is None:
            keys = list(self._held_keys)
            keys.extend(key for key in self.keys if key not in self._held_keys)
        self._release_keys(keys)

    def release_held_keys(self):
        self._release_keys(tuple(self._held_keys))

    def _run(self, on_stopped):
        self._run_loop(on_stopped=on_stopped)

    @staticmethod
    def _send_status(status, message):
        if status is None:
            return
        try:
            status.send(message)
        except Exception:
            pass

    def _poll_control(self, control):
        if control is None:
            return not self.is_playing
        try:
            while control.poll():
                message = control.recv()
                if not message:
                    continue
                kind = message[0]
                if kind == "stop":
                    self.is_playing = False
                    break
                if kind == "offset":
                    try:
                        self.offset_ms = float(message[1])
                    except (TypeError, ValueError, IndexError):
                        pass
                elif kind == "key_output_enabled":
                    try:
                        self.key_output_enabled = bool(message[1])
                    except IndexError:
                        pass
                elif kind == "keys":
                    try:
                        self.keys = list(message[1])
                    except (TypeError, IndexError):
                        pass
                elif kind == "release_all":
                    self.release_all_keys()
        except (EOFError, OSError):
            self.is_playing = False
        return not self.is_playing

    def _run_loop(self, on_stopped=None, control=None, status=None, verbose=None):
        if verbose is not None:
            self.verbose = verbose
        self.log_message(i18n.tr("log.playback_start"), "system")
        try:
            self.release_all_keys()
            speed = self.speed if self.speed else 1.0
            ms_per_counter = 1000.0 / PERF_FREQ
            counter_per_ms = PERF_FREQ / 1000.0
            margin_counter = 5.0 * counter_per_ms
            min_sleep_counter = 3.0 * counter_per_ms
            start_counter = get_perf_counter_raw()
            self._start_counter = start_counter
            self._send_status(status, ("started", start_counter))
            groups = []
            for event_time, key, action in self.timeline:
                base = start_counter + (event_time / speed) * counter_per_ms
                if groups and groups[-1][0] == base:
                    groups[-1][1].append((key, action))
                else:
                    groups.append((base, [(key, action)]))
            est_counter = 2.0 * counter_per_ms
            for base, actions in groups:
                if self._poll_control(control):
                    break
                while True:
                    if self._poll_control(control):
                        break
                    current = get_perf_counter_raw()
                    target = base + self.offset_ms * counter_per_ms
                    wait = target - current
                    if wait <= est_counter:
                        break
                    if wait > margin_counter + min_sleep_counter:
                        sleep_ms = (wait - margin_counter) * ms_per_counter / 1000.0
                        if control is not None:
                            sleep_ms = min(max(sleep_ms, 0.001), 0.02)
                        time.sleep(sleep_ms)
                if not self.is_playing:
                    break
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
                if self.key_output_enabled:
                    ok = self.injector.send(inputs)
                else:
                    ok = True
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
                            self.log_message(
                                i18n.tr("log.key_failed", key=key, error=e), "error"
                            )
                    self.log_message(i18n.tr("log.sendinput_fallback"), "error")
                if self.verbose:
                    for key, action in actions:
                        t_ms = (base - start_counter) * ms_per_counter + self.offset_ms
                        if action == "D":
                            self.log_message(f"[{t_ms:.1f}ms] Press {key}", "key")
                        else:
                            self.log_message(f"[{t_ms:.1f}ms] Release {key}", "delay")
            self.log_message(i18n.tr("log.playback_end"), "system")
        except Exception as e:
            self.log_message(i18n.tr("log.playback_error", error=e), "error")
            import traceback
            traceback.print_exc()
        finally:
            self.release_all_keys()
            self.is_playing = False
            self._send_status(status, ("stopped",))
            if on_stopped:
                on_stopped()