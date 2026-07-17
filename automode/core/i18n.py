"""Interface translations.

English is the default. The language is a normal setting, so it can be changed
from the menu like anything else. Logs are deliberately not translated — they
are diagnostics, and a bug report is easier to read in one language.

To add a language: copy the "en" block, translate the values, and add the code
to LANGUAGES. Any key you miss falls back to English rather than crashing.
"""

from __future__ import annotations

DEFAULT = "en"

CATALOG: dict[str, dict[str, str]] = {
    "en": {
        # menu chrome
        "menu.keys": " arrows move · space change · s save · q back ",
        "menu.edit_keys": "enter confirms · esc cancels",
        "menu.saved": "saved",
        "menu.save_failed": "could not save: {error}",
        "menu.not_a_number": "must be a number: {value}",
        "menu.bad_time": "invalid time: {value}",
        "menu.unsaved": "left without saving (press `s` to save)",
        "menu.needs_terminal": "the menu needs a terminal",
        # sections
        "section.continue": "Auto continue",
        "section.ping": "Auto ping",
        "section.general": "General",
        # auto continue
        "row.auto_continue": "auto continue",
        "hint.auto_continue": "spot the limit and type the message when it resets",
        "row.continue_message": "message",
        "hint.continue_message": "what to type once the limit is back",
        "row.grace_seconds": "wait after reset",
        "hint.grace_seconds": "how long to wait past the reset time",
        "row.idle_guard_seconds": "keyboard guard",
        "hint.idle_guard_seconds": "never type while you are typing",
        "row.answer_limit_prompt": "answer limit menu",
        "hint.answer_limit_prompt": "pick 'wait for reset' if the agent is stuck on it",
        # auto ping
        "row.ping_enabled": "auto ping",
        "hint.ping_enabled": "say hi early so the 5h window lands in your workday",
        "row.ping_message": "message",
        "row.ping_times": "times",
        "hint.ping_times": "comma separated, e.g. 05:00, 17:00",
        "row.ping_agent": "headless agent",
        "hint.ping_agent": "which agent the scheduled ping wakes up",
        "row.catchup_minutes": "catch-up",
        "hint.catchup_minutes": "if the machine slept through it, still count for X min",
        "row.ping_idle_seconds": "required silence",
        "hint.ping_idle_seconds": "only ping when the session is idle",
        # general
        "row.notify": "notifications",
        "row.hotkey": "menu hotkey",
        "hint.hotkey": "ctrl+g always works; alt+g needs terminal setup",
        "row.timezone": "timezone",
        "hint.timezone": "only touch this if the agent reports another zone",
        "row.language": "language",
        "hint.language": "language of this menu",
        "value.system_tz": "(system: {zone})",
        "value.empty": "(empty)",
        "value.none": "(none)",
        # cli
        "cli.tagline": "keep claude/codex working across usage limits",
        "cli.hotkey_line": "Inside a session, {hotkey} opens the menu over the agent.",
        "cli.unknown_command": "unknown command: {command}",
        "hotkey.join": " or ",
    },
    "pt": {
        "menu.keys": " setas movem · espaco altera · s salva · q volta ",
        "menu.edit_keys": "enter confirma · esc cancela",
        "menu.saved": "salvo",
        "menu.save_failed": "nao consegui salvar: {error}",
        "menu.not_a_number": "precisa ser um numero: {value}",
        "menu.bad_time": "horario invalido: {value}",
        "menu.unsaved": "saiu sem salvar (use `s` pra salvar)",
        "menu.needs_terminal": "o menu precisa de um terminal",
        "section.continue": "Auto continue",
        "section.ping": "Auto ping",
        "section.general": "Geral",
        "row.auto_continue": "auto continue",
        "hint.auto_continue": "detecta o limite e digita a mensagem quando renovar",
        "row.continue_message": "mensagem",
        "hint.continue_message": "o que digitar quando o limite voltar",
        "row.grace_seconds": "margem apos reset",
        "hint.grace_seconds": "quanto esperar depois do horario do reset",
        "row.idle_guard_seconds": "guarda de teclado",
        "hint.idle_guard_seconds": "nunca digita enquanto voce esta digitando",
        "row.answer_limit_prompt": "responder o menu",
        "hint.answer_limit_prompt": "escolhe 'esperar o reset' se o agente travou nele",
        "row.ping_enabled": "auto ping",
        "hint.ping_enabled": "manda um oi cedo pra janela de 5h cair no seu expediente",
        "row.ping_message": "mensagem",
        "row.ping_times": "horarios",
        "hint.ping_times": "separados por virgula, ex: 05:00, 17:00",
        "row.ping_agent": "agente headless",
        "hint.ping_agent": "qual agente o ping agendado acorda",
        "row.catchup_minutes": "catch-up",
        "hint.catchup_minutes": "se o pc dormiu e perdeu o horario, ainda vale por X min",
        "row.ping_idle_seconds": "silencio necessario",
        "hint.ping_idle_seconds": "so manda o ping se a sessao estiver parada",
        "row.notify": "notificacoes",
        "row.hotkey": "atalho do menu",
        "hint.hotkey": "ctrl+g funciona sempre; alt+g exige configurar o terminal",
        "row.timezone": "timezone",
        "hint.timezone": "so mexa se o agente reportar o reset em outro fuso",
        "row.language": "idioma",
        "hint.language": "idioma deste menu",
        "value.system_tz": "(do sistema: {zone})",
        "value.empty": "(vazio)",
        "value.none": "(nenhum)",
        "cli.tagline": "mantem o claude/codex trabalhando apesar dos limites",
        "cli.hotkey_line": "Dentro da sessao, {hotkey} abre o menu por cima do agente.",
        "cli.unknown_command": "comando desconhecido: {command}",
        "hotkey.join": " ou ",
    },
}

#: Codes offered in the menu, with the name each language calls itself.
LANGUAGES = {"en": "english", "pt": "portugues"}

_current = DEFAULT


def set_language(code: str) -> str:
    """Switch the interface language. Unknown codes fall back to English."""
    global _current
    _current = code if code in CATALOG else DEFAULT
    return _current


def language() -> str:
    return _current


def t(key: str, **fields: object) -> str:
    """Translate a key, falling back to English, then to the key itself."""
    text = CATALOG.get(_current, {}).get(key) or CATALOG[DEFAULT].get(key) or key
    if fields:
        try:
            return text.format(**fields)
        except (KeyError, IndexError):
            return text
    return text
