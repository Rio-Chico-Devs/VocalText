"""
Audio player – wraps pygame.mixer for WAV playback with position tracking.
All public methods are safe to call from any thread.
"""

import threading
import time
import os


class AudioPlayer:
    """Simple WAV player built on pygame.mixer."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pygame_ok = False
        self._path: str | None = None
        self._duration: float = 0.0
        self._start_time: float = 0.0
        self._pause_pos: float = 0.0
        self._playing = False
        self._paused = False
        self._on_end = None
        self._monitor_thread: threading.Thread | None = None
        self._init_pygame()

    def _init_pygame(self):
        try:
            import pygame
            pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
            pygame.mixer.init()
            self._pygame_ok = True
        except Exception as exc:
            print(f"[AudioPlayer] pygame not available: {exc}")

    # ── Loading ────────────────────────────────────────────────────────────────

    def load(self, path: str) -> float:
        """Load a WAV file. Returns duration in seconds (0 if unreadable)."""
        if not self._pygame_ok:
            return 0.0
        import pygame
        with self._lock:
            self._stop_locked()
            self._path = path
            self._duration = self._read_duration(path)
            self._pause_pos = 0.0
        return self._duration

    def _read_duration(self, path: str) -> float:
        """Read WAV duration without loading all samples into memory."""
        try:
            import wave
            with wave.open(path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / rate if rate > 0 else 0.0
        except Exception:
            return 0.0

    # ── Playback control ───────────────────────────────────────────────────────

    def play(self, on_end=None):
        """Start or resume playback."""
        if not self._pygame_ok or not self._path:
            return
        import pygame
        # Re-initialize if mixer was quit() by another player or cleanup
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
                pygame.mixer.init()
            except Exception as exc:
                print(f"[AudioPlayer] play error: {exc}")
                return
        with self._lock:
            self._on_end = on_end
            if self._paused:
                pygame.mixer.music.unpause()
                self._start_time = time.monotonic() - self._pause_pos
                self._paused = False
                self._playing = True
            else:
                try:
                    pygame.mixer.music.load(self._path)
                    pygame.mixer.music.play()
                    self._start_time = time.monotonic()
                    self._pause_pos = 0.0
                    self._playing = True
                    self._paused = False
                except Exception as exc:
                    print(f"[AudioPlayer] play error: {exc}")
                    return
        self._start_monitor()

    def pause(self):
        if not self._pygame_ok:
            return
        import pygame
        with self._lock:
            if self._playing and not self._paused:
                pygame.mixer.music.pause()
                self._pause_pos = time.monotonic() - self._start_time
                self._paused = True
                self._playing = False

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        if not self._pygame_ok:
            return
        import pygame
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self._playing = False
        self._paused = False
        self._pause_pos = 0.0

    def seek(self, seconds: float):
        """Seek to position (seconds). Restarts playback from that point."""
        if not self._pygame_ok or not self._path:
            return
        import pygame
        was_playing = self._playing or self._paused
        with self._lock:
            self._stop_locked()
            self._pause_pos = max(0.0, min(seconds, self._duration))
            if was_playing:
                try:
                    pygame.mixer.music.load(self._path)
                    pygame.mixer.music.play(start=self._pause_pos)
                    self._start_time = time.monotonic() - self._pause_pos
                    self._playing = True
                    self._paused = False
                except Exception:
                    pass
        if was_playing:
            self._start_monitor()

    def restart(self):
        self.seek(0.0)

    # ── State ──────────────────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        """Current playback position in seconds."""
        if self._paused:
            return self._pause_pos
        if self._playing:
            return min(time.monotonic() - self._start_time, self._duration)
        return self._pause_pos

    # ── End monitor ────────────────────────────────────────────────────────────

    def _start_monitor(self):
        """Background thread that calls on_end when track finishes."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def _watch():
            import pygame
            cb = None
            while True:
                time.sleep(0.1)
                with self._lock:
                    if not self._playing:
                        break
                    if not pygame.mixer.music.get_busy():
                        self._playing = False
                        self._pause_pos = 0.0
                        cb = self._on_end
                        break
            if cb:
                cb()

        self._monitor_thread = threading.Thread(target=_watch, daemon=True)
        self._monitor_thread.start()

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def quit(self):
        with self._lock:
            self._stop_locked()
        if self._pygame_ok:
            try:
                import pygame
                pygame.mixer.quit()
            except Exception:
                pass
