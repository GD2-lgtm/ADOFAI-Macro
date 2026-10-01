import ctypes
import multiprocessing
import threading
from . import i18n
from .console import PERF_FREQ, get_perf_counter_raw
from .playback import PlaybackEngine

def _boost_process_timing():
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.SetPriorityClass.restype = ctypes.c_bool
        kernel32.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
        kernel32.SetThreadPriority.restype = ctypes.c_bool
        kernel32.SetPriorityClass(
            kernel32.GetCurrentProcess(), 0x00008000
        )
        kernel32.SetThreadPriority(
            kernel32.GetCurrentThread(), 2
        )
    except Exception:
        pass
    try:
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        return winmm
    except Exception:
        return None

def _process_log(message, msg_type="system"):
    try:
        print(f"[{msg_type}] {message}", flush=True)
    except Exception:
        pass

def _send_status(status, message):
    if status is None:
        return
    try:
        status.send(message)
    except Exception:
        pass

def _apply_config(engine, timeline, keys, speed, key_output_enabled, verbose):
    engine.timeline = list(timeline or [])
    engine.keys = list(keys or [])
    engine.speed = speed if speed else 1.0
    engine.key_output_enabled = bool(key_output_enabled)
    engine.verbose = bool(verbose)
    engine.log_message = _process_log if engine.verbose else (lambda *a, **k: None)
    for _, key, _ in engine.timeline:
        try:
            engine._key_to_codes(key)
        except Exception:
            pass

def _set_process_language(code):
    """The spawned worker keeps its own i18n state, so mirror it over."""
    try:
        i18n.set_language(code)
    except Exception:
        pass

def _playback_process_main(control, status, timeline=None, keys=None,
                           speed=1.0, verbose=False,
                           key_output_enabled=True):
    winmm_timer = _boost_process_timing()
    engine = PlaybackEngine(lambda *args, **kwargs: None)
    engine.is_playing = False
    if timeline is not None:
        _apply_config(engine, timeline, keys, speed,
                      key_output_enabled, verbose)
    else:
        engine.speed = speed if speed else 1.0
        engine.verbose = bool(verbose)
        engine.key_output_enabled = bool(key_output_enabled)
        engine.log_message = _process_log if engine.verbose else (lambda *a, **k: None)
    _send_status(status, ("ready",))
    try:
        while True:
            try:
                message = control.recv()
            except (EOFError, OSError):
                break
            if not message:
                continue
            kind = message[0]
            if kind == "configure":
                _apply_config(
                    engine,
                    message[1] if len(message) > 1 else [],
                    message[2] if len(message) > 2 else [],
                    message[3] if len(message) > 3 else 1.0,
                    message[4] if len(message) > 4 else True,
                    message[5] if len(message) > 5 else False,
                )
                if len(message) > 6:
                    _set_process_language(message[6])
                _send_status(status, ("configured",))
            elif kind == "language":
                if len(message) > 1:
                    _set_process_language(message[1])
            elif kind == "start":
                if len(message) > 1:
                    engine.verbose = bool(message[1])
                    engine.log_message = (
                        _process_log if engine.verbose else (lambda *a, **k: None)
                    )
                if len(message) > 2:
                    engine.key_output_enabled = bool(message[2])
                if len(message) > 3:
                    _set_process_language(message[3])
                engine.is_playing = True
                engine._run_loop(
                    control=control,
                    status=status,
                    verbose=engine.verbose,
                )
            elif kind == "stop":
                engine.release_all_keys()
            elif kind == "offset":
                try:
                    engine.offset_ms = float(message[1])
                except (TypeError, ValueError, IndexError):
                    pass
            elif kind == "key_output_enabled":
                try:
                    engine.key_output_enabled = bool(message[1])
                except IndexError:
                    pass
            elif kind == "keys":
                try:
                    engine.keys = list(message[1])
                except (TypeError, IndexError):
                    pass
            elif kind == "release_all":
                engine.release_all_keys()
            elif kind == "shutdown":
                engine.release_all_keys()
                break
    finally:
        try:
            engine.release_all_keys()
        except Exception:
            pass
        if winmm_timer is not None:
            try:
                winmm_timer.timeEndPeriod(1)
            except Exception:
                pass
        for handle in (control, status):
            try:
                handle.close()
            except Exception:
                pass

class RemotePlaybackEngine:
    def __init__(self, log_message):
        self.log_message = log_message
        self._keys = []
        self.is_playing = False
        self.offset_ms = 0.0
        self.verbose = True
        self._key_output_enabled = True
        self.timeline = []
        self.speed = 1.0
        self._start_counter = None
        self._process = None
        self._control = None
        self._status = None
        self._monitor_thread = None
        self._on_stopped = None
        self._ready_event = threading.Event()
        self._job_stopped_event = threading.Event()
        self._worker_lock = threading.RLock()
        self._configured = False
        self._ctx = multiprocessing.get_context("spawn")
        self.language = i18n.get_language()

    @property
    def key_output_enabled(self):
        return self._key_output_enabled

    @key_output_enabled.setter
    def key_output_enabled(self, value):
        self._key_output_enabled = bool(value)
        self._send_control(("key_output_enabled", self._key_output_enabled))

    @property
    def keys(self):
        return self._keys

    @keys.setter
    def keys(self, value):
        self._keys = list(value or [])
        self._send_control(("keys", self._keys))

    def preload_timeline(self, timeline, speed=1.0):
        self.timeline = list(timeline or [])
        self.speed = speed
        self._configured = False
        try:
            self._ensure_worker()
            if not self.is_playing:
                self._send_configure()
        except Exception as e:
            self.log_message(i18n.tr("log.preload_failed", error=e), "error")

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
        self._on_stopped = None
        self.stop()
        self.verbose = bool(verbose)
        self._on_stopped = on_stopped
        self._start_counter = None
        self._job_stopped_event.clear()
        self._ensure_worker()
        if not self._configured:
            self._send_configure()
        self.is_playing = True
        self._send_control(
            ("start", self.verbose, self._key_output_enabled, self.language)
        )

    def stop(self):
        was_playing = self.is_playing
        self.is_playing = False
        if not self._worker_is_alive():
            self._close_worker_handles()
            return
        self._send_control(("stop",))
        if was_playing:
            self._job_stopped_event.wait(timeout=0.8)
            if not self._job_stopped_event.is_set():
                self._cleanup_worker()
        else:
            self._send_control(("release_all",))

    def shutdown(self):
        self.is_playing = False
        if self._worker_is_alive():
            self._send_control(("shutdown",))
            proc = self._process
            if proc is not None:
                try:
                    proc.join(timeout=0.8)
                except Exception:
                    pass
        self._cleanup_worker()

    def release_all_keys(self, keys=None):
        self._send_control(("release_all",))

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
        self._send_control(("offset", self.offset_ms))
        return self.offset_ms

    def reset_offset(self):
        self.offset_ms = 0.0
        self._send_control(("offset", 0.0))
        return 0.0

    def _worker_is_alive(self):
        proc = self._process
        try:
            return proc is not None and proc.is_alive()
        except Exception:
            return False

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker_is_alive():
                return
            self._cleanup_worker()
            control_parent, control_child = self._ctx.Pipe(duplex=True)
            status_parent, status_child = self._ctx.Pipe(duplex=False)
            process = self._ctx.Process(
                target=_playback_process_main,
                args=(control_child, status_child),
                daemon=True,
            )
            self._process = process
            self._control = control_parent
            self._status = status_parent
            self._configured = False
            self._ready_event.clear()
            self._job_stopped_event.clear()
            try:
                process.start()
            except Exception:
                self._process = None
                self._control = None
                self._status = None
                for handle in (control_parent, status_parent,
                               control_child, status_child):
                    try:
                        handle.close()
                    except Exception:
                        pass
                raise
            for handle in (control_child, status_child):
                try:
                    handle.close()
                except Exception:
                    pass
            self._monitor_thread = threading.Thread(
                target=self._monitor,
                name="remote-playback-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def _cleanup_worker(self):
        with self._worker_lock:
            proc = self._process
            monitor = self._monitor_thread
            self._process = None
            self._monitor_thread = None
            if proc is not None:
                try:
                    if proc.is_alive():
                        self._send_control(("shutdown",))
                        proc.join(timeout=0.5)
                except Exception:
                    pass
                try:
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=0.3)
                except Exception:
                    pass
            self._close_worker_handles()
            if monitor is not None and monitor.is_alive():
                try:
                    monitor.join(timeout=0.3)
                except Exception:
                    pass
            self._configured = False
            self._ready_event.clear()
            self._job_stopped_event.set()

    def _close_worker_handles(self):
        for name in ("_control", "_status"):
            handle = getattr(self, name, None)
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass
            setattr(self, name, None)

    def _send_control(self, message):
        control = self._control
        if control is None:
            return
        try:
            control.send(message)
        except Exception:
            pass

    def _send_configure(self):
        self._send_control((
            "configure",
            list(self.timeline),
            list(self.keys),
            self.speed,
            self._key_output_enabled,
            self.verbose,
            self.language,
        ))
        self._configured = True

    def _monitor(self):
        status = self._status
        while status is not None:
            try:
                message = status.recv()
            except (EOFError, OSError):
                break
            except Exception:
                break
            if not message:
                continue
            kind = message[0]
            if kind == "ready":
                self._ready_event.set()
            elif kind == "configured":
                self._configured = True
            elif kind == "started" and len(message) >= 2:
                self._start_counter = message[1]
            elif kind == "stopped":
                self.is_playing = False
                self._job_stopped_event.set()
                callback = self._on_stopped
                self._on_stopped = None
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        pass
        self.is_playing = False
        self._job_stopped_event.set()
        self._ready_event.clear()
        callback = self._on_stopped
        self._on_stopped = None
        if callback is not None:
            try:
                callback()
            except Exception:
                pass