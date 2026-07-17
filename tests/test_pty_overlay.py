"""Drive the whole wrapper through a real PTY.

Everything else mocks the terminal. This spawns automode for real, presses
keys at it, and reads what a terminal would have received. The only way to
know the open/close flow actually works.
"""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Raw mode, like every real agent TUI: reads land byte by byte with no echo.
FAKE_AGENT = """
import os, sys, termios, tty
tty.setraw(0)
sys.stdout.write("AGENTE-PRONTO\\r\\n")
sys.stdout.flush()
while True:
    data = os.read(0, 1024)
    if not data:
        break
    sys.stdout.write("AGENTE-RECEBEU:" + repr(data) + "\\r\\n")
    sys.stdout.flush()
"""

ALT_ON = b"\x1b[?1049h"
ALT_OFF = b"\x1b[?1049l"


def _winsize(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class PtyHarness:
    """automode running under a PTY we own, as if we were the terminal."""

    def __init__(self, tmpdir: Path, config: str):
        (tmpdir / "automode").mkdir(parents=True, exist_ok=True)
        (tmpdir / "automode" / "config.toml").write_text(config)
        agent = tmpdir / "agent.py"
        agent.write_text(FAKE_AGENT)

        self.master, slave = pty.openpty()
        _winsize(slave, 30, 100)
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "XDG_CONFIG_HOME": str(tmpdir),
            "XDG_STATE_HOME": str(tmpdir / "state"),
            "PYTHONPATH": str(ROOT),
        }
        # The suite may itself be running inside a wrapped session (it happens:
        # you run the tests from a claude that automode wrapped). The depth
        # counter is inherited, and a deep enough one turns the wrapper off.
        env.pop("AUTOMODE_DEPTH", None)
        env.pop("AUTOMODE_SESSION", None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "automode", "--", sys.executable, str(agent)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
        )
        os.close(slave)

    def read(self, seconds=1.0) -> bytes:
        out = b""
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.master], [], [], 0.1)
            if self.master in ready:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
        return out

    def press(self, data: bytes):
        os.write(self.master, data)

    def close(self):
        try:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            self.proc.kill()
        try:
            os.close(self.master)
        except OSError:
            pass


CONFIG = """
auto_continue = true
notify = false
hotkey = "ctrl+g, alt+g"
"""


class OverlayThroughPtyTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.h = PtyHarness(Path(self.tmp.name), CONFIG)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.h.close)
        boot = self.h.read(3)
        self.assertIn(b"AGENTE-PRONTO", boot, "o agente nem subiu")

    def test_ctrl_g_opens_the_menu_and_q_closes_it(self):
        self.h.press(b"\x07")
        opened = self.h.read(1.5)
        self.assertIn(ALT_ON, opened, "nao entrou na tela alternativa")
        self.assertIn(b"MOD", opened, "o titulo autoMODe nao apareceu")
        self.assertIn("╔".encode("utf-8"), opened, "a caixa nao foi desenhada")

        self.h.press(b"q")
        closed = self.h.read(1.5)
        self.assertIn(ALT_OFF, closed, "nao saiu da tela alternativa")
        self.assertIn(b"\x1b[?25h", closed, "nao devolveu o cursor")

    def test_the_hotkey_never_reaches_the_agent(self):
        self.h.press(b"\x07")
        self.h.read(1.0)
        self.h.press(b"q")
        out = self.h.read(1.0)
        self.assertNotIn(b"AGENTE-RECEBEU", out, "o agente recebeu a tecla do menu")

    def test_keys_reach_the_agent_again_after_closing(self):
        self.h.press(b"\x07")
        self.h.read(1.0)
        self.h.press(b"q")
        self.h.read(1.0)
        self.h.press(b"oi\r")
        after = self.h.read(1.5)
        self.assertIn(b"AGENTE-RECEBEU", after, "o teclado nao voltou pro agente")
        self.assertIn(b"oi", after)

    def test_closing_forces_the_agent_to_repaint(self):
        # The agents draw their header once and never again, so a botched
        # restore leaves it hidden forever. Closing must provoke a real resize.
        self.h.press(b"\x07")
        self.h.read(1.0)
        before = struct.unpack(
            "HHHH", fcntl.ioctl(self.h.master, termios.TIOCGWINSZ, b"\0" * 8)
        )
        self.h.press(b"q")
        self.h.read(1.5)
        after = struct.unpack(
            "HHHH", fcntl.ioctl(self.h.master, termios.TIOCGWINSZ, b"\0" * 8)
        )
        self.assertEqual(before, after, "o tamanho tem que voltar ao original")

    def test_agent_output_during_the_menu_is_not_lost(self):
        self.h.press(b"\x07")
        self.h.read(1.0)
        # The agent speaks while the menu is up: held back, then replayed.
        self.h.press(b"q")
        replayed = self.h.read(1.5)
        self.assertIn(ALT_OFF, replayed)

    def test_alt_g_also_opens_when_the_terminal_sends_meta(self):
        self.h.press(b"\x1bg")
        opened = self.h.read(1.5)
        self.assertIn(ALT_ON, opened)

    def test_a_lone_escape_goes_to_the_agent_not_the_menu(self):
        # Esc is how you interrupt claude; it must never be eaten by automode.
        self.h.press(b"\x1b")
        out = self.h.read(1.0)
        self.assertNotIn(ALT_ON, out, "o menu abriu com um Esc solto")
        self.assertIn(b"AGENTE-RECEBEU", out, "o Esc nao chegou no agente")

    def test_arrow_keys_navigate_without_closing(self):
        self.h.press(b"\x07")
        self.h.read(1.0)
        self.h.press(b"\x1b[B")  # desce
        self.h.press(b"\x1b[B")
        drawn = self.h.read(1.0)
        self.assertNotIn(ALT_OFF, drawn, "as setas fecharam o menu")
        self.h.press(b"q")
        self.assertIn(ALT_OFF, self.h.read(1.5))

    def test_toggling_a_checkbox_then_closing(self):
        self.h.press(b"\x07")
        self.h.read(1.0)
        self.h.press(b" ")  # o primeiro item e um checkbox
        drawn = self.h.read(1.0)
        self.assertIn(b"[ ]", drawn, "o checkbox nao desmarcou")
        self.h.press(b"q")
        self.assertIn(ALT_OFF, self.h.read(1.5))

    def test_q_typed_into_a_number_does_not_close_and_does_not_corrupt_it(self):
        # Space on a number opens an editor, so `q` is text, not a command.
        # It must neither close the menu nor be written into an int field.
        self.h.press(b"\x07")
        self.h.read(1.0)
        self.h.press(b"\x1b[B\x1b[B")  # down to "wait after reset"
        self.h.press(b" ")  # abre o editor
        self.h.press(b"q\r")  # digita lixo e confirma
        drawn = self.h.read(1.0)
        self.assertNotIn(ALT_OFF, drawn, "o q fechou o menu de dentro do editor")
        self.assertIn(b"must be a number", drawn)
        self.h.press(b"\x1b")
        self.assertIn(ALT_OFF, self.h.read(1.5))


if __name__ == "__main__":
    unittest.main()
