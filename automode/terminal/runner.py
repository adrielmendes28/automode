"""Run a child process under a PTY, passing the terminal through untouched.

automode sits between your keyboard and the agent. Bytes are forwarded in both
directions verbatim, so the agent's TUI looks and behaves exactly as it does
unwrapped, while a copy of the output goes to the controller, which may type
into the PTY on your behalf.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import tty
from typing import Protocol, Sequence

READ_SIZE = 65536
# Cap the select timeout so the schedule is re-checked promptly after the
# machine wakes from sleep, where the wall clock jumps but no fd is ready.
MAX_TIMEOUT = 5.0
# Long enough for the agent to notice the fake resize and repaint. Only ever
# paid once, when the menu closes.
REDRAW_SETTLE = 0.2


class Controller(Protocol):
    def on_output(self, data: bytes) -> None: ...
    def on_user_input(self, data: bytes) -> None: ...
    def next_timeout(self) -> float: ...
    def tick(self, inject) -> None: ...


#: How many nested wrappers before we assume something is looping. A shell
#: function or a script named `claude` that calls automode back would recurse
#: forever; genuine nesting (an agent opening an agent) never goes this deep.
MAX_DEPTH = 3


def session_depth() -> int:
    """How many automode wrappers we are already inside."""
    try:
        return int(os.environ.get("AUTOMODE_DEPTH", "0") or 0)
    except ValueError:
        return 0


def _get_winsize(fd: int) -> tuple[int, int, int, int]:
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
        return rows, cols, xpix, ypix
    except OSError:
        return 24, 80, 0, 0


def _set_winsize(fd: int, size: tuple[int, int, int, int]) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", *size))
    except OSError:
        pass


def _write_all(fd: int, data: bytes) -> None:
    while data:
        try:
            written = os.write(fd, data)
        except InterruptedError:
            continue
        except BlockingIOError:
            select.select([], [fd], [], 0.05)
            continue
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EINTR):
                continue
            raise
        data = data[written:]


def _signal_eof(master_fd: int) -> None:
    """Pass our stdin's EOF along, so a child reading a pipe does not hang.

    A PTY has no EOF of its own. The end of input is the VEOF character, and
    only while the child is in canonical mode. A TUI in raw mode is reading
    keystrokes, not a stream, so sending it ^D would just be a stray keypress.
    """
    try:
        attrs = termios.tcgetattr(master_fd)
    except termios.error:
        return
    if not attrs[3] & termios.ICANON:
        return
    veof = attrs[6][termios.VEOF]
    payload = veof if isinstance(veof, bytes) else bytes([veof])
    try:
        _write_all(master_fd, payload)
    except OSError:
        pass


def _force_redraw(master_fd: int, pid: int, size: tuple[int, int, int, int]) -> None:
    """Make the agent repaint everything after the menu covered it.

    Leaving the alternate screen is supposed to restore the agent's screen, and
    usually does. But the agents draw their header exactly once and never again,
    so if the restore comes up short there is nothing to bring it back.

    Measured against Claude Code: a same-size SIGWINCH is ignored, but a real
    size change makes it re-emit its entire UI, header included. So we lie about
    the size for a moment and put it back.
    """
    rows, cols, xpix, ypix = size
    if rows < 2:
        return
    _set_winsize(master_fd, (rows - 1, cols, xpix, ypix))
    try:
        os.kill(pid, signal.SIGWINCH)
    except OSError:
        return
    time.sleep(REDRAW_SETTLE)
    _set_winsize(master_fd, size)
    try:
        os.kill(pid, signal.SIGWINCH)
    except OSError:
        pass


def run(argv: Sequence[str], controller: Controller, overlay=None) -> int:
    """Run argv under a PTY. Returns the child's exit code.

    While `overlay` is open it swallows the keyboard and the agent's output is
    held back rather than drawn, so the menu owns the screen alone.
    """
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    interactive = os.isatty(stdin_fd)
    size = _get_winsize(stdin_fd) if interactive else (24, 80, 0, 0)

    depth = session_depth()
    pid, master_fd = pty.fork()
    if pid == 0:
        # Child: pty.fork() already gave us the slave as a controlling
        # terminal on fds 0/1/2, so the agent believes it owns a real tty.
        os.environ["AUTOMODE_SESSION"] = "1"
        os.environ["AUTOMODE_DEPTH"] = str(depth + 1)
        try:
            os.execvp(argv[0], list(argv))
        except OSError as exc:
            sys.stderr.write(f"automode: cannot run {argv[0]!r}: {exc.strerror}\n")
            sys.stderr.flush()
        os._exit(127)

    _set_winsize(master_fd, size)

    old_attr = None
    if interactive:
        try:
            old_attr = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd)
        except termios.error:
            old_attr = None

    resized = [False]

    def _on_winch(_signum, _frame):
        resized[0] = True

    old_winch = None
    if interactive:
        old_winch = signal.signal(signal.SIGWINCH, _on_winch)

    watch = [master_fd]
    if interactive or not sys.stdin.closed:
        watch.append(stdin_fd)

    def inject(payload: bytes) -> None:
        try:
            _write_all(master_fd, payload)
        except OSError:
            pass

    try:
        while True:
            if resized[0]:
                resized[0] = False
                size = _get_winsize(stdin_fd)
                _set_winsize(master_fd, size)
                try:
                    os.kill(pid, signal.SIGWINCH)
                except OSError:
                    pass
                if overlay is not None and overlay.open:
                    _write_all(stdout_fd, overlay.resize((size[0], size[1])))

            timeout = min(max(controller.next_timeout(), 0.0), MAX_TIMEOUT)
            try:
                readable, _, _ = select.select(watch, [], [], timeout)
            except InterruptedError:
                continue
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise

            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, READ_SIZE)
                except OSError:
                    data = b""
                if data:
                    controller.on_user_input(data)
                    if overlay is not None and overlay.open:
                        _write_all(stdout_fd, overlay.handle(data))
                        if overlay.done:
                            _write_all(stdout_fd, overlay.leave())
                            _force_redraw(master_fd, pid, _get_winsize(stdin_fd))
                    elif overlay is not None and overlay.matches_hotkey(data):
                        current = _get_winsize(stdin_fd)
                        _write_all(stdout_fd, overlay.enter((current[0], current[1])))
                    else:
                        try:
                            _write_all(master_fd, data)
                        except OSError:
                            break
                else:
                    # Our stdin closed; stop watching it but keep relaying the
                    # agent's output until it exits on its own.
                    watch.remove(stdin_fd)
                    _signal_eof(master_fd)

            if master_fd in readable:
                try:
                    data = os.read(master_fd, READ_SIZE)
                except OSError as exc:
                    # The kernel reports the child's exit as EIO on the master.
                    if exc.errno in (errno.EIO, errno.EBADF):
                        break
                    raise
                if not data:
                    break
                if overlay is not None:
                    overlay.track_output(data)
                    if overlay.open:
                        overlay.hold(data)
                    else:
                        _write_all(stdout_fd, data)
                else:
                    _write_all(stdout_fd, data)
                controller.on_output(data)

            controller.tick(inject)
    finally:
        if old_winch is not None:
            signal.signal(signal.SIGWINCH, old_winch)
        if old_attr is not None:
            termios.tcsetattr(stdin_fd, termios.TCSAFLUSH, old_attr)
        try:
            os.close(master_fd)
        except OSError:
            pass

    return _reap(pid)


def _reap(pid: int) -> int:
    try:
        _, status = os.waitpid(pid, 0)
    except OSError:
        return 0
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 0
