#!/usr/bin/env python3
"""
NEXUS TERMINAL — Unified Animated Terminal UI for AI & Developer CLIs.

Combines AI CLIs (opencode, gemini, codex, crush, copilot, dsh, aider, llm,
mods, hermes, agy/claude, ollama), open-source GitHub & dev CLIs, local user
scripts, and a live zero-key Public API Hub in one responsive terminal UI.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Markdown as MarkdownWidget,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import ai_hub  # noqa: E402
import api_hub  # noqa: E402

# ---------------------------------------------------------------- animation assets
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
ORB_FRAMES = ["◉", "◎", "●", "◎"]
EQ_PALETTE = ["#38BDF8", "#60A5FA", "#818CF8", "#A78BFA", "#C084FC", "#34D399"]
WAVE_BARS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃", "▂"]

PROMPT_TEMPLATES = {
    "/explain": "Explain clearly and concisely the code or project in this working directory:",
    "/fix": "Analyze the following issue and provide a safe, direct fix:",
    "/review": "Review the code/changes in this repository: identify bugs, edge cases, and improvements:",
    "/commit": "Write a concise Conventional Commits message for the current git diff.",
    "/summarize": "Summarize the key points of the following content:",
}

SLASH_COMMANDS = [
    ("/agent ", "Switch active AI agent (e.g. /agent gemini)"),
    ("/open ", "Open CLI in a new terminal window (e.g. /open gemini)"),
    ("/new", "Start a new conversation (clear chat history)"),
    ("/export ", "Export conversation to Markdown (e.g. /export chat.md)"),
    ("/sessions", "List saved chat sessions"),
    ("/load ", "Restore a saved session by number (e.g. /load 1)"),
    ("/shell", "Toggle between AI Chat mode and Shell CLI mode"),
    ("/all ", "Query all ready AI agents in parallel"),
    ("/api ", "Call open-source GitHub APIs (e.g. /api weather, /api gh ai, /api sync)"),
    ("/auth", "Show free AI tiers & login sync status"),
    ("/login ", "Sign in to an AI CLI so it syncs with Nexus (e.g. /login gemini)"),
    ("/setup", "Auto-configure local Ollama & refresh all AI CLIs"),
    ("/native ", "Launch CLI full-screen interactive TUI inside this window"),
    ("/model ", "Set or inspect model for the active session"),
    ("/cwd ", "Change or show current working directory (or cd <dir>)"),
    ("/explain", "Template: explain code or repository"),
    ("/fix", "Template: diagnose and fix a bug"),
    ("/review", "Template: code review & edge-case check"),
    ("/commit", "Template: generate git commit message"),
    ("/summarize", "Template: summarize key points"),
    ("/continue", "Toggle session context continuation (on/off)"),
    ("/reset", "Reset context for the next message"),
    ("/doctor", "Run health check on all AI CLIs"),
    ("/limits", "Show quota/cooldown fallback status"),
    ("/clis", "List all discovered CLIs on this system"),
    ("/clear", "Clear the conversation stream"),
    ("/help", "Show keyboard shortcuts and commands"),
]


class PromptInput(Input):
    """Prompt input with history navigation (Up/Down) and autocomplete."""

    def on_key(self, event) -> None:
        app = self.app
        if not isinstance(app, NexusTerminal):
            return
        suggest_visible = app.suggest_open()
        if event.key == "tab" and suggest_visible:
            event.prevent_default()
            event.stop()
            app.accept_suggestion()
            return
        if event.key == "escape" and suggest_visible:
            event.prevent_default()
            event.stop()
            app.hide_suggestions()
            return
        if event.key == "up":
            if suggest_visible:
                event.prevent_default()
                event.stop()
                app.move_suggestion(-1)
            else:
                event.prevent_default()
                event.stop()
                app.history_step(-1)
            return
        if event.key == "down":
            if suggest_visible:
                event.prevent_default()
                event.stop()
                app.move_suggestion(1)
            else:
                event.prevent_default()
                event.stop()
                app.history_step(1)
            return


class ModelPickerModal(ModalScreen[str | None]):
    """Modal dialog for picking or entering a model name."""

    CSS = """
    ModelPickerModal {
        align: center middle;
        background: rgba(5, 8, 16, 0.78);
    }
    #model-dialog {
        width: 72;
        max-height: 26;
        background: #0F172A;
        border: round #38BDF8;
        padding: 1 2;
    }
    #model-title {
        color: #E2E8F0;
        text-style: bold;
        margin-bottom: 1;
    }
    #model-custom {
        margin-bottom: 1;
        background: #1E293B;
        border: tall #334155;
    }
    #model-list {
        height: 12;
        background: #0B1220;
        border: round #1E293B;
        margin-bottom: 1;
    }
    #model-actions {
        height: 3;
        align: right middle;
    }
    """

    def __init__(self, agent_name: str, current_model: str, models: list[str]) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.current_model = current_model
        self.models = models

    def compose(self) -> ComposeResult:
        with Vertical(id="model-dialog"):
            yield Label(f"✦ Select Model — {self.agent_name}", id="model-title")
            yield Input(
                value=self.current_model,
                placeholder="Type a model name or pick one below (empty = agent default)...",
                id="model-custom",
            )
            ol = OptionList(id="model-list")
            ol.add_option(Option("(agent default)", id="__default__"))
            for m in self.models:
                ol.add_option(Option(m, id=m))
            yield ol
            with Horizontal(id="model-actions"):
                yield Button("Apply", variant="primary", id="btn-model-ok")
                yield Button("Cancel", id="btn-model-cancel")

    @on(OptionList.OptionSelected, "#model-list")
    def _pick(self, event: OptionList.OptionSelected) -> None:
        val = "" if event.option.id == "__default__" else str(event.option.id)
        self.dismiss(val)

    @on(Input.Submitted, "#model-custom")
    def _submit_custom(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    @on(Button.Pressed, "#btn-model-ok")
    def _ok(self) -> None:
        val = self.query_one("#model-custom", Input).value.strip()
        self.dismiss(val)

    @on(Button.Pressed, "#btn-model-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class NexusHeader(Static):
    """Animated status bar showing active agent, model, context, cwd, and clock."""

    def render_status(
        self,
        tick: int,
        boot_progress: float,
        agent: str,
        model: str,
        cont: bool,
        cwd: str,
        busy_label: str,
        counts: tuple[int, int, int],
    ) -> None:
        t = Text()
        orb_color = "#FBBF24" if busy_label else ("#A78BFA" if boot_progress < 1.0 else "#34D399")
        orb = SPINNER_FRAMES[tick % len(SPINNER_FRAMES)] if busy_label else ORB_FRAMES[(tick // 3) % len(ORB_FRAMES)]
        t.append(f" {orb} ", style=f"bold {orb_color}")

        title = "NEXUS TERMINAL"
        for idx, ch in enumerate(title):
            col = EQ_PALETTE[(idx + (tick // 2)) % len(EQ_PALETTE)] if (boot_progress < 1.0 or busy_label) else "#E2E8F0"
            t.append(ch, style=f"bold {col}")

        t.append("  │  ", style="#334155")
        t.append(f"✦ {agent}", style="bold #38BDF8")
        if model:
            t.append(f":{model}", style="#A78BFA")
        t.append("  ", style="")
        t.append("ctx:ON" if cont else "ctx:OFF", style="bold #34D399" if cont else "#64748B")
        t.append("  │  ", style="#334155")

        short_cwd = cwd.replace(str(Path.home()), "~")
        if len(short_cwd) > 30:
            short_cwd = "…" + short_cwd[-29:]
        t.append(short_cwd, style="#94A3B8")

        if busy_label:
            t.append("  │  ", style="#334155")
            wave = "".join(
                WAVE_BARS[(tick + i * 2) % len(WAVE_BARS)] for i in range(6)
            )
            t.append(f"{wave} {busy_label}", style="bold #FBBF24")
        else:
            ai_n, dev_n, scr_n = counts
            t.append("  │  ", style="#334155")
            t.append(f"{ai_n} AI · {dev_n} Dev · {scr_n} Scripts", style="#64748B")

        now_s = dt.datetime.now().strftime("%H:%M:%S")
        t.append(f"  [{now_s}]", style="#475569")
        self.update(t)


class ThinkingWidget(Static):
    """Animated thinking & live token streaming card."""

    def __init__(self, agent: str, prompt_preview: str) -> None:
        super().__init__(classes="thinking-card")
        self.agent = agent
        self.model = ""
        self.prompt_preview = prompt_preview
        self.stream_text = ""
        self.t0 = time.time()

    def set_attempt(self, agent: str, model: str) -> None:
        self.agent = agent
        self.model = model

    def set_stream_text(self, text: str) -> None:
        self.stream_text = text

    def tick(self, frame: int) -> None:
        elapsed = time.time() - self.t0
        spin = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
        t = Text()
        t.append(f" {spin} ", style="bold #FBBF24")
        t.append(f"{self.agent}", style="bold #38BDF8")
        if self.model:
            t.append(f" ({self.model})", style="#A78BFA")
        t.append("  ", style="")
        if not self.stream_text:
            shimmer_len = 14
            pos = frame % shimmer_len
            for i in range(shimmer_len):
                dist = abs(i - pos)
                if dist == 0:
                    t.append("█", style="bold #38BDF8")
                elif dist == 1:
                    t.append("▓", style="#818CF8")
                elif dist == 2:
                    t.append("▒", style="#475569")
                else:
                    t.append("░", style="#1E293B")
            t.append(f"  {elapsed:.1f}s", style="bold #94A3B8")
            t.append("  [Ctrl+X stop]", style="#475569")
            if self.prompt_preview:
                t.append(f"\n   › {self.prompt_preview}", style="dim #64748B")
        else:
            t.append(f"streaming · {elapsed:.1f}s", style="bold #34D399")
            t.append("  [Ctrl+X stop]\n\n", style="#475569")
            cursor = "▍" if (frame // 2) % 2 == 0 else " "
            t.append(self.stream_text[-2500:] + cursor, style="#E2E8F0")
        self.update(t)


class NexusTerminal(App):
    """Unified CLI Terminal with smooth animations and multi-turn AI chat."""

    TITLE = "Nexus Terminal — Unified CLI Hub"
    ENABLE_COMMAND_PALETTE = True

    CSS = """
    Screen {
        background: #070B14;
        color: #E2E8F0;
    }

    #top-bar {
        dock: top;
        height: 3;
        background: #0D1424;
        border-bottom: heavy #1E293B;
        content-align: left middle;
        padding: 0 1;
    }

    #main-body {
        height: 1fr;
    }

    #sidebar {
        width: 34;
        background: #0B111E;
        border-right: heavy #1E293B;
        padding: 1;
    }

    #sidebar.hidden {
        display: none;
    }

    #cli-filter {
        height: 3;
        background: #11192C;
        border: tall #1E293B;
        margin-bottom: 1;
    }

    #cli-filter:focus {
        border: tall #38BDF8;
    }

    #cli-tabs {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    OptionList {
        background: #090E1A;
        border: round #1E293B;
        height: 1fr;
        scrollbar-color: #334155;
    }

    OptionList:focus {
        border: round #38BDF8;
    }

    #sidebar-hint {
        height: 2;
        color: #64748B;
        padding: 0 1;
        margin-top: 1;
    }

    #workspace {
        width: 1fr;
        background: #070B14;
    }

    #stream-scroll {
        height: 1fr;
        padding: 1 2;
        scrollbar-color: #334155;
    }

    .boot-banner {
        height: auto;
        background: #0D1526;
        border: round #38BDF8;
        padding: 1 2;
        margin-bottom: 1;
    }

    .user-card {
        height: auto;
        background: #101A2E;
        border-left: heavy #38BDF8;
        padding: 0 2;
        margin-bottom: 1;
        color: #F8FAFC;
    }

    .thinking-card {
        height: auto;
        background: #0F172A;
        border: round #FBBF24;
        padding: 1 2;
        margin-bottom: 1;
    }

    .ai-card {
        height: auto;
        background: #0C1322;
        border: round #1E293B;
        padding: 1 2;
        margin-bottom: 1;
    }

    .ai-card Markdown {
        height: auto;
        margin: 0;
        padding: 0;
    }

    .ai-card-ok {
        border: round #34D399;
    }

    .ai-card-err {
        border: round #FB7185;
    }

    .ai-card-header {
        height: auto;
        color: #E2E8F0;
        text-style: bold;
        margin-bottom: 1;
    }

    .shell-card {
        height: auto;
        background: #090E18;
        border: round #818CF8;
        padding: 1 2;
        margin-bottom: 1;
    }

    #suggest-box {
        display: none;
        max-height: 9;
        margin: 0 2;
        background: #0F172A;
        border: round #38BDF8;
    }

    #suggest-box.open {
        display: block;
    }

    #composer {
        dock: bottom;
        height: auto;
        background: #0B111E;
        border-top: heavy #1E293B;
        padding: 1 2;
    }

    #quick-chips {
        height: 1;
        margin-bottom: 1;
        overflow-x: auto;
    }

    .chip-btn {
        width: auto;
        min-width: 4;
        margin-right: 1;
        background: #131C31;
        color: #CBD5E1;
    }

    .chip-btn:hover {
        background: #1E293B;
        color: #FFFFFF;
    }

    .chip-active {
        background: #0C4A6E;
        color: #7DD3FC;
        text-style: bold;
    }

    .chip-action {
        background: #1E1B4B;
        color: #C4B5FD;
    }

    #input-row {
        height: 3;
    }

    #prompt-input {
        width: 1fr;
        background: #111827;
        border: tall #334155;
        color: #F8FAFC;
    }

    #prompt-input:focus {
        border: tall #38BDF8;
    }

    #btn-send {
        width: 10;
        margin-left: 1;
    }

    #btn-native, #btn-newwin {
        width: 11;
        margin-left: 1;
    }

    #footer-hints {
        height: 1;
        color: #64748B;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Toggle Dock"),
        Binding("ctrl+n", "new_chat", "New Chat"),
        Binding("ctrl+l", "clear_stream", "Clear"),
        Binding("ctrl+t", "cycle_agent", "Next Agent"),
        Binding("ctrl+g", "send_all", "Compare All"),
        Binding("ctrl+x", "cancel_active", "Stop"),
        Binding("f2", "launch_native", "Chat TUI"),
        Binding("f3", "pick_model", "Model"),
        Binding("f4", "open_new_terminal", "New Win"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, start_agent: str, model: str, cwd: str, timeout: int | None) -> None:
        super().__init__()
        self.cfg = ai_hub.load_config()
        self.env = ai_hub.build_env(self.cfg)
        self.active_agent = start_agent if start_agent in self.cfg["agents"] else self.cfg["default_agent"]
        self.active_model = model
        self.cwd = cwd
        self.timeout = timeout
        self.cont = False
        self.shell_mode = False
        self.chat_history: list[dict] = []
        self.session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.sessions_dir = Path.home() / ".local" / "share" / "ai-hub" / "sessions"
        self.catalog = ai_hub.discover_all_clis(self.cfg, self.env)
        self.auth_map = {r["name"]: r for r in ai_hub.get_auth_status(self.cfg, self.env)}
        self.tick_count = 0
        self.boot_progress = 0.0
        self.active_thinking: list[ThinkingWidget] = []
        self._cancel_events: list[threading.Event] = []
        self.busy_label = ""
        self.history: list[str] = []
        self.history_idx = -1
        self._suggest_items: list[tuple[str, str]] = []
        self._boot_banner: Static | None = None

    def compose(self) -> ComposeResult:
        yield NexusHeader(id="top-bar")
        with Horizontal(id="main-body"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="Filter CLIs, AI, or APIs...", id="cli-filter")
                with TabbedContent(id="cli-tabs"):
                    with TabPane("AI", id="tab-ai"):
                        yield OptionList(id="list-ai")
                    with TabPane("Dev", id="tab-dev"):
                        yield OptionList(id="list-dev")
                    with TabPane("Scripts", id="tab-scripts"):
                        yield OptionList(id="list-scripts")
                    with TabPane("APIs", id="tab-api"):
                        yield OptionList(id="list-api")
                yield Static(
                    "Enter: select/run · F2: native TUI · F4: new window · Ctrl+B: hide",
                    id="sidebar-hint",
                )
            with Vertical(id="workspace"):
                yield VerticalScroll(id="stream-scroll")
                yield OptionList(id="suggest-box")
                with Vertical(id="composer"):
                    with Horizontal(id="quick-chips"):
                        yield Button("AI Chat", id="chip-mode", classes="chip-btn chip-active", compact=True)
                        for ag in ("opencode", "crush", "llm", "mods", "codex", "gemini"):
                            if ag in self.cfg["agents"]:
                                cls = "chip-btn chip-active" if ag == self.active_agent else "chip-btn"
                                yield Button(ag, id=f"chip-{ag}", classes=cls, compact=True)
                        yield Button("@all", id="chip-action-all", classes="chip-btn chip-action", compact=True)
                        yield Button("/api", id="chip-action-api", classes="chip-btn chip-action", compact=True)
                        yield Button("/new", id="chip-action-new", classes="chip-btn", compact=True)
                    with Horizontal(id="input-row"):
                        yield PromptInput(
                            placeholder=self._prompt_placeholder(),
                            id="prompt-input",
                        )
                        yield Button("Send", variant="primary", id="btn-send")
                        yield Button("Chat TUI", variant="warning", id="btn-native")
                        yield Button("New Win", variant="success", id="btn-newwin")
                    yield Static(
                        "Enter Send · Chat TUI (F2) open native CLI · New Win (F4) open new Terminal · /shell toggle mode · Ctrl+N New Chat",
                        id="footer-hints",
                    )

    def _prompt_placeholder(self) -> str:
        if self.shell_mode:
            return "Shell CLI mode — run any command (ls, git status, gemini, opencode) or /shell for AI..."
        return f"Chat with {self.active_agent} (multi-turn) · or !cmd, @agent, /open <cli>, F2/F4 native chat..."

    def _counts(self) -> tuple[int, int, int]:
        ai_n = sum(1 for x in self.catalog["ai"] if x["installed"])
        dev_n = sum(1 for x in self.catalog["dev"] if x["installed"])
        scr_n = len(self.catalog["scripts"])
        return (ai_n, dev_n, scr_n)

    def on_mount(self) -> None:
        self._populate_lists()
        self._render_boot_banner()
        self.set_interval(0.1, self._on_tick)
        threading.Thread(target=ai_hub.warm_ollama, args=("llama3.2:latest", 5), daemon=True).start()
        self.query_one("#prompt-input", Input).focus()

    def action_cancel_active(self) -> None:
        if not self._cancel_events:
            return
        for ev in list(self._cancel_events):
            ev.set()
        self.notify("Cancelling active request...", severity="warning")

    def _on_tick(self) -> None:
        if not self.is_running:
            return
        self.tick_count += 1
        if self.boot_progress < 1.0:
            self.boot_progress = min(1.0, self.boot_progress + 0.06)
            self._update_boot_banner()
        for tw in list(self.active_thinking):
            if tw.is_mounted:
                tw.tick(self.tick_count)
        try:
            header = self.query_one("#top-bar", NexusHeader)
        except Exception:
            return
        header.render_status(
            self.tick_count,
            self.boot_progress,
            self.active_agent,
            self.active_model,
            self.cont,
            self.cwd,
            self.busy_label,
            self._counts(),
        )

    def _render_boot_banner(self) -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        banner = Static(classes="boot-banner")
        self._boot_banner = banner
        scroll.mount(banner)
        self._update_boot_banner()

    def _update_boot_banner(self) -> None:
        if not self._boot_banner or not self._boot_banner.is_mounted:
            return
        ai_n, dev_n, scr_n = self._counts()
        pct = int(self.boot_progress * 100)
        filled = int(self.boot_progress * 24)
        bar = "━" * filled + "─" * (24 - filled)

        ready_ai = [x["name"] for x in self.catalog["ai"] if x["installed"]]
        ready_dev = [x["name"] for x in self.catalog["dev"] if x["installed"]]

        t = Text()
        t.append("◈ NEXUS TERMINAL ", style="bold #38BDF8")
        t.append(f"v{ai_hub.VERSION}", style="#A78BFA")
        t.append("  —  Unified CLI & AI Hub\n", style="#94A3B8")
        if self.boot_progress < 1.0:
            t.append(f"  Scanning installed CLIs [{bar}] {pct}%\n", style="#34D399")
        else:
            t.append("  ● Ready! ", style="bold #34D399")
            t.append(f"{ai_n} AI CLIs · {dev_n} GitHub/Dev CLIs · {scr_n} Scripts connected\n", style="#CBD5E1")
        t.append("\n  AI CLIs : ", style="bold #7DD3FC")
        t.append(", ".join(ready_ai) or "-", style="#E2E8F0")
        t.append("\n  Dev/GH  : ", style="bold #A78BFA")
        t.append(", ".join(ready_dev[:12]) + (" …" if len(ready_dev) > 12 else ""), style="#CBD5E1")
        t.append("\n\n  Quick Tips: ", style="bold #FBBF24")
        t.append("Type directly to chat · ", style="#94A3B8")
        t.append("@gemini ...", style="bold #38BDF8")
        t.append(" quick route · ", style="#94A3B8")
        t.append("@all ...", style="bold #34D399")
        t.append(" compare parallel · ", style="#94A3B8")
        t.append("!git status", style="bold #A78BFA")
        t.append(" run any CLI", style="#94A3B8")
        self._boot_banner.update(t)

    def _refresh_auth_and_dock(self) -> None:
        self.catalog = ai_hub.discover_all_clis(self.cfg, self.env)
        self.auth_map = {r["name"]: r for r in ai_hub.get_auth_status(self.cfg, self.env)}
        try:
            q = self.query_one("#cli-filter", Input).value
        except Exception:
            q = ""
        self._populate_lists(q)

    def _populate_lists(self, query: str = "") -> None:
        q = query.strip().lower()
        mapping = [
            ("#list-ai", self.catalog["ai"]),
            ("#list-dev", self.catalog["dev"]),
            ("#list-scripts", self.catalog["scripts"]),
        ]
        for widget_id, items in mapping:
            ol = self.query_one(widget_id, OptionList)
            ol.clear_options()
            for it in items:
                if q and q not in it["name"].lower() and q not in it["label"].lower():
                    continue
                if it["category"] == "ai":
                    st = self.auth_map.get(it["name"], {})
                    status = st.get("status", "ready" if it["installed"] else "missing")
                    dot = "●" if status == "ready" else ("◐" if status == "login-needed" else "○")
                    star = " ★" if it["name"] == self.active_agent else ""
                    badge = " [login]" if status == "login-needed" else (" [free]" if st.get("tier") in ("free-cloud", "free-local") else "")
                    label = f"{dot} {it['name']}{star}{badge}"
                else:
                    dot = "●" if it["installed"] else "○"
                    tag = " [TUI]" if it.get("interactive") else ""
                    label = f"{dot} {it['name']}{tag}"
                ol.add_option(Option(label, id=f"{it['category']}:{it['name']}"))

        api_ol = self.query_one("#list-api", OptionList)
        api_ol.clear_options()
        for cmd, desc in api_hub.BUILTIN_APIS:
            if q and q not in cmd.lower() and q not in desc.lower():
                continue
            api_ol.add_option(Option(f"◈ {cmd}", id=f"api:{cmd}"))

    @on(Input.Changed, "#cli-filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self._populate_lists(event.value)

    @on(OptionList.OptionSelected, "#list-ai")
    def _select_ai_from_dock(self, event: OptionList.OptionSelected) -> None:
        _, name = str(event.option.id).split(":", 1)
        self._set_active_agent(name)

    @on(OptionList.OptionSelected, "#list-dev")
    def _select_dev_from_dock(self, event: OptionList.OptionSelected) -> None:
        _, name = str(event.option.id).split(":", 1)
        it = next((x for x in self.catalog["dev"] if x["name"] == name), None)
        if not it or not it["installed"]:
            self.notify(f"{name} is not installed", severity="warning")
            return
        if it.get("interactive"):
            self._run_native_cmd([it["path"] or name], title=name)
        else:
            inp = self.query_one("#prompt-input", Input)
            inp.value = f"!{name} "
            inp.cursor_position = len(inp.value)
            inp.focus()

    @on(OptionList.OptionSelected, "#list-scripts")
    def _select_script_from_dock(self, event: OptionList.OptionSelected) -> None:
        _, name = str(event.option.id).split(":", 1)
        it = next((x for x in self.catalog["scripts"] if x["name"] == name), None)
        if it:
            inp = self.query_one("#prompt-input", Input)
            inp.value = f"!{shlex.quote(it['path'])}"
            inp.cursor_position = len(inp.value)
            inp.focus()
            self.notify(f"Ready to run: {name} (press Enter)")

    @on(OptionList.OptionSelected, "#list-api")
    def _select_api_from_dock(self, event: OptionList.OptionSelected) -> None:
        _, cmd = str(event.option.id).split(":", 1)
        base = cmd.split()[0]
        if "<" in cmd or "[" in cmd:
            inp = self.query_one("#prompt-input", Input)
            inp.value = f"/api {base} "
            inp.cursor_position = len(inp.value)
            inp.focus()
        else:
            self._append_user_card("API", f"/api {base}")
            self._run_api_bg(base)

    def _set_active_agent(self, name: str) -> None:
        if name not in self.cfg["agents"]:
            return
        self.active_agent = name
        self.cont = False
        self._populate_lists(self.query_one("#cli-filter", Input).value)
        for btn in self.query(".chip-btn"):
            if btn.id and btn.id.startswith("chip-") and not btn.id.startswith(("chip-action-", "chip-tpl-", "chip-mode")):
                ag = btn.id.removeprefix("chip-")
                btn.set_class(ag == name, "chip-active")
        inp = self.query_one("#prompt-input", Input)
        inp.placeholder = self._prompt_placeholder()
        inp.focus()
        st = self.auth_map.get(name, {})
        if st.get("status") == "login-needed":
            self.notify(f"{name}: sign in first with `/login {name}` or F2 ({st.get('detail', '')})", severity="warning")
        else:
            self.notify(f"Active agent: {name}")

    # ---------------------------------------------------------------- autocomplete
    def suggest_open(self) -> bool:
        return self.query_one("#suggest-box", OptionList).has_class("open")

    def hide_suggestions(self) -> None:
        self.query_one("#suggest-box", OptionList).remove_class("open")

    def move_suggestion(self, delta: int) -> None:
        box = self.query_one("#suggest-box", OptionList)
        if box.option_count == 0:
            return
        cur = 0 if box.highlighted is None else box.highlighted
        box.highlighted = (cur + delta) % box.option_count

    def accept_suggestion(self) -> None:
        box = self.query_one("#suggest-box", OptionList)
        if box.option_count == 0:
            self.hide_suggestions()
            return
        idx = 0 if box.highlighted is None else box.highlighted
        opt = box.get_option_at_index(idx)
        val = str(opt.id)
        inp = self.query_one("#prompt-input", Input)
        inp.value = val
        inp.cursor_position = len(val)
        self.hide_suggestions()
        inp.focus()

    @on(OptionList.OptionSelected, "#suggest-box")
    def _click_suggestion(self, event: OptionList.OptionSelected) -> None:
        inp = self.query_one("#prompt-input", Input)
        inp.value = str(event.option.id)
        inp.cursor_position = len(inp.value)
        self.hide_suggestions()
        inp.focus()

    @on(Input.Changed, "#prompt-input")
    def _prompt_changed(self, event: Input.Changed) -> None:
        val = event.value
        box = self.query_one("#suggest-box", OptionList)
        items: list[tuple[str, str]] = []
        if val.startswith("@file "):
            q = val[6:].strip().lower()
            try:
                skip = {".git", "node_modules", "__pycache__", ".venv", "venv"}
                entries = sorted(Path(self.cwd).iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
                for p in entries:
                    if p.name in skip or p.name.startswith("."):
                        continue
                    if p.is_file() and (not q or q in p.name.lower()):
                        items.append((f"@file {p.name} ", f"@file {p.name:<20} — attach file ({p.stat().st_size} B)"))
            except OSError:
                pass
        elif val.startswith("@") and " " not in val:
            q = val[1:].lower()
            cands = [("all", "Query all ready AI agents in parallel"), ("file", "Attach a local file as prompt context")] + [
                (x["name"], x["label"]) for x in self.catalog["ai"] if x["installed"]
            ]
            for name, desc in cands:
                if q in name.lower():
                    items.append((f"@{name} ", f"@{name:<10} — {desc}"))
        elif val.startswith("/") and " " not in val:
            q = val.lower()
            for cmd, desc in SLASH_COMMANDS:
                if q in cmd.lower():
                    items.append((cmd, f"{cmd:<12} — {desc}"))
        elif val.startswith("!") and " " not in val:
            q = val[1:].lower()
            all_tools = self.catalog["dev"] + self.catalog["scripts"]
            for it in all_tools:
                if it["installed"] and q in it["name"].lower():
                    items.append((f"!{it['name']} ", f"!{it['name']:<14} — {it['label']}"))

        box.clear_options()
        self._suggest_items = items[:8]
        if self._suggest_items:
            for insert_val, label in self._suggest_items:
                box.add_option(Option(label, id=insert_val))
            box.highlighted = 0
            box.add_class("open")
        else:
            box.remove_class("open")

    def history_step(self, delta: int) -> None:
        if not self.history:
            return
        if self.history_idx == -1:
            if delta < 0:
                self.history_idx = len(self.history) - 1
            else:
                return
        else:
            self.history_idx += delta
        inp = self.query_one("#prompt-input", Input)
        if self.history_idx < 0:
            self.history_idx = 0
        elif self.history_idx >= len(self.history):
            self.history_idx = -1
            inp.value = ""
            return
        inp.value = self.history[self.history_idx]
        inp.cursor_position = len(inp.value)

    # ---------------------------------------------------------------- buttons & actions
    @on(Button.Pressed)
    def _button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-send":
            self._submit_current()
        elif bid == "btn-all":
            self.action_send_all()
        elif bid == "btn-native":
            self.action_launch_native()
        elif bid == "btn-newwin":
            self.action_open_new_terminal()
        elif bid == "chip-mode":
            self._toggle_shell_mode()
        elif bid == "chip-action-new":
            self.action_new_chat()
        elif bid == "chip-action-all":
            inp = self.query_one("#prompt-input", Input)
            if not inp.value.startswith("@all"):
                inp.value = "@all " + inp.value
                inp.cursor_position = len(inp.value)
            inp.focus()
        elif bid == "chip-action-shell":
            inp = self.query_one("#prompt-input", Input)
            if not inp.value.startswith("!"):
                inp.value = "!" + inp.value
                inp.cursor_position = len(inp.value)
            inp.focus()
        elif bid == "chip-action-api":
            inp = self.query_one("#prompt-input", Input)
            if not inp.value.startswith("/api"):
                inp.value = "/api " + inp.value
                inp.cursor_position = len(inp.value)
            inp.focus()
        elif bid.startswith("chip-tpl-"):
            tpl = "/" + bid.removeprefix("chip-tpl-")
            inp = self.query_one("#prompt-input", Input)
            inp.value = PROMPT_TEMPLATES.get(tpl, tpl) + " "
            inp.cursor_position = len(inp.value)
            inp.focus()
        elif bid.startswith("chip-"):
            self._set_active_agent(bid.removeprefix("chip-"))

    @on(Input.Submitted, "#prompt-input")
    def _submitted(self, event: Input.Submitted) -> None:
        if self.suggest_open() and (event.value in ("@", "/", "!")):
            self.accept_suggestion()
            return
        self.hide_suggestions()
        self._submit_current()

    def _submit_current(self) -> None:
        inp = self.query_one("#prompt-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""
        self.hide_suggestions()
        if not self.history or self.history[-1] != text:
            self.history.append(text)
        self.history_idx = -1
        self._handle_line(text)

    def action_toggle_sidebar(self) -> None:
        self.query_one("#sidebar").toggle_class("hidden")

    def action_clear_stream(self) -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        for child in list(scroll.children):
            child.remove()
        self._boot_banner = None
        self._render_boot_banner()

    def action_new_chat(self) -> None:
        self.chat_history.clear()
        self.cont = False
        self.session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.action_clear_stream()
        self.notify(f"Started a new chat session ({self.active_agent})")

    def _save_session(self) -> None:
        if not self.chat_history:
            return
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            path = self.sessions_dir / f"session-{self.session_id}.json"
            payload = {
                "id": self.session_id,
                "agent": self.active_agent,
                "cwd": self.cwd,
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "messages": self.chat_history,
            }
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        except OSError:
            pass

    def _list_sessions(self) -> list[Path]:
        try:
            if not self.sessions_dir.is_dir():
                return []
            return sorted(self.sessions_dir.glob("session-*.json"), reverse=True)[:15]
        except OSError:
            return []

    def _export_markdown(self, target_name: str) -> None:
        if not self.chat_history:
            self.notify("No chat messages to export yet", severity="warning")
            return
        fname = target_name or f"nexus-chat-{self.session_id}.md"
        out_path = Path(fname).expanduser()
        if not out_path.is_absolute():
            out_path = Path(self.cwd) / out_path
        lines = [f"# Nexus Terminal Chat ({self.session_id})\n", f"- **Agent:** `{self.active_agent}`\n", f"- **CWD:** `{self.cwd}`\n\n---\n"]
        for m in self.chat_history:
            role = "You" if m["role"] == "user" else self.active_agent
            lines.append(f"### {role}\n\n{m['content']}\n\n")
        try:
            out_path.write_text("\n".join(lines))
            self._append_info_card(f"Exported conversation to `{out_path}`", title="EXPORTED")
        except OSError as e:
            self.notify(f"Export failed: {e}", severity="error")

    def _expand_file_mentions(self, text: str) -> tuple[str, list[str]]:
        """Resolve `@file path` tokens into fenced file contents."""
        attached: list[str] = []
        pattern = re.compile(r"@file\s+(\S+)")
        blocks: list[str] = []

        def _repl(m: re.Match) -> str:
            raw_path = m.group(1)
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = Path(self.cwd) / p
            if p.is_file():
                try:
                    content = p.read_text(errors="replace")[:24000]
                    attached.append(p.name)
                    blocks.append(f"File `{p.name}`:\n```\n{content}\n```")
                    return f"[attached: {p.name}]"
                except OSError:
                    pass
            return m.group(0)

        cleaned = pattern.sub(_repl, text).strip()
        if not blocks:
            return text, attached
        if not cleaned or cleaned.startswith("[attached:"):
            cleaned = f"Explain and review the attached file(s):\n\n" + "\n\n".join(blocks)
        else:
            cleaned = f"{cleaned}\n\n" + "\n\n".join(blocks)
        return cleaned, attached

    def _toggle_shell_mode(self) -> None:
        self.shell_mode = not self.shell_mode
        btn = self.query_one("#chip-mode", Button)
        btn.label = "Shell CLI" if self.shell_mode else "AI Chat"
        inp = self.query_one("#prompt-input", Input)
        inp.placeholder = self._prompt_placeholder()
        inp.focus()
        self.notify("Mode: Shell CLI (run commands directly)" if self.shell_mode else f"Mode: AI Chat ({self.active_agent})")

    def action_open_new_terminal(self, target: str = "") -> None:
        cli = target or self.active_agent
        if cli in self.cfg["agents"]:
            a = self.cfg["agents"][cli]
            if not ai_hub.find_bin(a):
                self.notify(f"Binary not found: {cli}", severity="error")
                return
            cmd = ai_hub.build_cmd(a, "", self.active_model if cli == self.active_agent else "", False, interactive=True)
        else:
            cmd = shlex.split(cli) if cli else ["/bin/zsh"]
        ok, msg = ai_hub.open_in_new_terminal(cmd, self.cwd)
        if ok:
            self.notify(f"Opened new terminal window: {cli}")
            self._append_info_card(f"Opened **{cli}** in a new terminal window:\n```sh\n{msg}\n```", title="NEW TERMINAL")
        else:
            self.notify(f"Failed to open new terminal: {msg}", severity="error")

    def action_cycle_agent(self) -> None:
        installed = [x["name"] for x in self.catalog["ai"] if x["installed"]]
        if not installed:
            return
        if self.active_agent in installed:
            nxt = installed[(installed.index(self.active_agent) + 1) % len(installed)]
        else:
            nxt = installed[0]
        self._set_active_agent(nxt)

    def action_send_all(self) -> None:
        inp = self.query_one("#prompt-input", Input)
        text = inp.value.strip()
        if not text:
            self.notify("Type a prompt first before comparing all agents", severity="warning")
            return
        inp.value = ""
        if text.startswith("@all "):
            text = text[5:].strip()
        self._append_user_card("@all", text)
        self._run_all_agents(text)

    def action_launch_native(self) -> None:
        a = self.cfg["agents"].get(self.active_agent)
        if not a:
            return
        bp = ai_hub.find_bin(a)
        if not bp:
            self.notify(f"Binary not found: {self.active_agent}", severity="error")
            return
        cmd = ai_hub.build_cmd(a, "", self.active_model, False, interactive=True)
        self._run_native_cmd(cmd, title=self.active_agent)

    @work
    async def action_pick_model(self) -> None:
        a = self.cfg["agents"].get(self.active_agent, {})
        models = await asyncio.to_thread(
            ai_hub.list_models, self.active_agent, a, self.cwd, self.env
        )
        picked = await self.push_screen_wait(
            ModelPickerModal(self.active_agent, self.active_model, models)
        )
        if picked is not None:
            self.active_model = picked
            self.notify(f"Model {self.active_agent}: {picked or '(default)'}")

    def _run_native_cmd(self, cmd: list[str], title: str) -> None:
        with self.suspend():
            os.system("clear")
            print(f"\x1b[36m◈ Launching {title} (native TTY) — exit to return to Nexus Terminal\x1b[0m\n")
            try:
                subprocess.run(cmd, cwd=self.cwd, env=self.env)
            except KeyboardInterrupt:
                pass
        self._refresh_auth_and_dock()
        self._append_info_card(f"Returned from native `{title}` session (auth/CLI status synced)")

    # ---------------------------------------------------------------- stream cards
    def _scroll_bottom(self) -> None:
        self.query_one("#stream-scroll", VerticalScroll).scroll_end(animate=False)

    def _append_user_card(self, target: str, text: str) -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        t = Text()
        t.append(f"› {target} ", style="bold #38BDF8")
        t.append(f"[{dt.datetime.now().strftime('%H:%M')}] ", style="#64748B")
        t.append(text, style="#F8FAFC")
        scroll.mount(Static(t, classes="user-card"))
        self._scroll_bottom()

    def _append_info_card(self, md_text: str, title: str = "INFO") -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        box = Vertical(classes="ai-card")
        scroll.mount(box)
        box.mount(Static(f"◈ {title}", classes="ai-card-header"))
        box.mount(MarkdownWidget(md_text))
        self._scroll_bottom()

    def _append_ai_card(self, res: dict) -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        ok = res.get("ok", False)
        cls = "ai-card ai-card-ok" if ok else "ai-card ai-card-err"
        box = Vertical(classes=cls)
        scroll.mount(box)
        mark = "✓" if ok else "✗"
        secs = res.get("seconds", 0)
        sw = "  ↪ auto-switch" if res.get("switched") else ""
        hdr = f"{mark} {res.get('agent', '?')} ({secs}s){sw}"
        box.mount(Static(hdr, classes="ai-card-header"))
        body = (res.get("output") or "").strip()
        if not ok:
            err = (res.get("error") or f"Failed (rc={res.get('returncode', '?')})").strip()
            body = f"{body}\n\n**Error:**\n```\n{err}\n```" if body else f"**Error:**\n```\n{err}\n```"
        box.mount(MarkdownWidget(body or "_(no output)_"))
        self._scroll_bottom()

    def _append_shell_card(self, cmd_str: str, rc: int, out: str, err: str, secs: float) -> None:
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        t = Text()
        badge_col = "#34D399" if rc == 0 else "#FB7185"
        t.append(f"$ {cmd_str}", style="bold #A78BFA")
        t.append(f"  [exit {rc} · {secs}s]\n", style=f"bold {badge_col}")
        combined = "\n".join(x for x in (out.strip(), err.strip()) if x)
        t.append(combined or "(completed with no output)", style="#CBD5E1")
        scroll.mount(Static(t, classes="shell-card"))
        self._scroll_bottom()

    # ---------------------------------------------------------------- routing
    def _handle_line(self, line: str) -> None:
        if line.startswith(("!", "$ ")):
            sh = line[1:].strip() if line.startswith("!") else line[2:].strip()
            if not sh:
                return
            self._handle_shell(sh)
            return

        if line == "cd" or line.startswith("cd "):
            target = line[2:].strip() or "~"
            self._change_cwd(target)
            return

        if line.startswith("/"):
            cmd_head = line.split(None, 1)[0].lower()
            rest = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            if cmd_head in PROMPT_TEMPLATES:
                expanded = f"{PROMPT_TEMPLATES[cmd_head]} {rest}".strip()
                self._append_user_card(self.active_agent, expanded)
                self._run_ai(self.active_agent, expanded)
                return
            if cmd_head in ("/exit", "/quit", "/q"):
                self.exit()
                return
            if cmd_head == "/clear":
                self.action_clear_stream()
                return
            if cmd_head == "/new":
                self.action_new_chat()
                return
            if cmd_head == "/export":
                self._export_markdown(rest)
                return
            if cmd_head == "/sessions":
                files = self._list_sessions()
                if not files:
                    self._append_info_card("No saved sessions yet.", title="SESSIONS")
                else:
                    lines = []
                    for idx, f in enumerate(files, 1):
                        try:
                            d = json.loads(f.read_text())
                            n_msg = len(d.get("messages", [])) // 2
                            preview = (d.get("messages", [{}])[0].get("content", "")[:50]).replace("\n", " ")
                            lines.append(f"{idx}. `{d.get('id')}` · `{d.get('agent')}` · {n_msg} turns — _{preview}_")
                        except Exception:
                            lines.append(f"{idx}. `{f.name}`")
                    lines.append("\nUse `/load <number>` to restore a session.")
                    self._append_info_card("\n".join(lines), title="SAVED SESSIONS")
                return
            if cmd_head == "/load":
                files = self._list_sessions()
                if not rest.isdigit() or not (1 <= int(rest) <= len(files)):
                    self.notify("Usage: /load <session_number> (see /sessions)", severity="warning")
                    return
                try:
                    d = json.loads(files[int(rest) - 1].read_text())
                    self.chat_history = list(d.get("messages", []))
                    self.session_id = d.get("id", self.session_id)
                    if d.get("agent") in self.cfg["agents"]:
                        self._set_active_agent(d["agent"])
                    self.cont = bool(self.chat_history)
                    self.action_clear_stream()
                    for m in self.chat_history:
                        if m["role"] == "user":
                            self._append_user_card(self.active_agent, m["content"])
                        else:
                            self._append_ai_card({"agent": self.active_agent, "ok": True, "output": m["content"], "seconds": 0})
                    self.notify(f"Loaded session {self.session_id}")
                except Exception as e:
                    self.notify(f"Failed to load session: {e}", severity="error")
                return
            if cmd_head == "/setup":
                self._handle_shell("NO_COLOR=1 ai setup")
                return
            if cmd_head == "/auth":
                rows = ai_hub.get_auth_status(self.cfg, self.env)
                self.auth_map = {r["name"]: r for r in rows}
                lines = ["| CLI | Tier | Status | Details |", "|---|---|---|---|"]
                for r in rows:
                    badge = "● Ready" if r["status"] == "ready" else ("◐ Login needed" if r["status"] == "login-needed" else "○ Missing")
                    act = f" (` /login {r['name']}`)" if r["status"] == "login-needed" and r["login_args"] is not None else ""
                    lines.append(f"| `{r['name']}` | `{r['tier']}` | {badge} | {r['detail']}{act} |")
                self._append_info_card("\n".join(lines), title="AI FREE TIERS & LOGIN SYNC")
                return
            if cmd_head == "/login":
                target = rest or self.active_agent
                if target not in self.cfg["agents"]:
                    self.notify(f"Unknown agent: {target}", severity="error")
                    return
                r_info = self.auth_map.get(target, {})
                l_args = r_info.get("login_args")
                if l_args is None:
                    self.notify(f"{target} uses local/free models and needs no login.")
                    return
                bp = ai_hub.find_bin(self.cfg["agents"][target])
                if not bp:
                    self.notify(f"Binary not found: {target}", severity="error")
                    return
                self._run_native_cmd([bp, *l_args], title=f"{target} login")
                return
            if cmd_head == "/shell":
                self._toggle_shell_mode()
                return
            if cmd_head == "/open":
                self.action_open_new_terminal(rest)
                return
            if cmd_head == "/help":
                lines = "\n".join(f"- `{c}` — {d}" for c, d in SLASH_COMMANDS)
                self._append_info_card(lines, title="NEXUS TERMINAL GUIDE")
                return
            if cmd_head == "/agent":
                if not rest:
                    self.action_cycle_agent()
                elif rest in self.cfg["agents"]:
                    self._set_active_agent(rest)
                else:
                    self.notify(f"Unknown agent: {rest}", severity="error")
                return
            if cmd_head == "/model":
                if not rest:
                    self.action_pick_model()
                else:
                    self.active_model = "" if rest in ("default", "reset") else rest
                    self.notify(f"Model {self.active_agent}: {self.active_model or '(default)'}")
                return
            if cmd_head == "/cwd":
                if not rest:
                    self._append_info_card(f"Current working directory: `{self.cwd}`", title="CWD")
                else:
                    self._change_cwd(rest)
                return
            if cmd_head == "/continue":
                self.cont = rest.lower() != "off"
                self.notify(f"Continue context: {'ON' if self.cont else 'OFF'}")
                return
            if cmd_head == "/reset":
                self.chat_history.clear()
                self.cont = False
                self.notify("Conversation context reset for the next prompt")
                return
            if cmd_head == "/all":
                if not rest:
                    self.notify("Usage: /all <prompt>", severity="warning")
                    return
                self._append_user_card("@all", rest)
                self._run_all_agents(rest)
                return
            if cmd_head == "/api":
                api_cmd = rest or "help"
                self._append_user_card("API", f"/api {api_cmd}")
                self._run_api_bg(api_cmd)
                return
            if cmd_head == "/native":
                target = rest or self.active_agent
                if target in self.cfg["agents"]:
                    a = self.cfg["agents"][target]
                    cmd = ai_hub.build_cmd(a, "", self.active_model if target == self.active_agent else "", False, interactive=True)
                    self._run_native_cmd(cmd, title=target)
                else:
                    self._run_native_cmd(shlex.split(target), title=target)
                return
            if cmd_head == "/clis":
                rows = []
                for sec, key in (("AI CLIs", "ai"), ("GitHub & Dev CLIs", "dev"), ("User Scripts", "scripts")):
                    ready = [f"`{x['name']}`" for x in self.catalog[key] if x["installed"]]
                    rows.append(f"**{sec} ({len(ready)}):** " + (", ".join(ready) or "_none_"))
                self._append_info_card("\n\n".join(rows), title="DISCOVERED CLIs")
                return
            if cmd_head in ("/doctor", "/limits"):
                sub = cmd_head.lstrip("/")
                self._handle_shell(f"NO_COLOR=1 ai {sub}")
                return
            self.notify(f"Unknown command: {cmd_head} (type /help)", severity="warning")
            return

        if line.startswith("@"):
            if line.startswith("@file "):
                expanded, attached = self._expand_file_mentions(line)
                self._append_user_card(self.active_agent, line)
                self._run_ai(self.active_agent, expanded)
                return
            parts = line[1:].split(None, 1)
            target = parts[0].lower()
            prompt = parts[1].strip() if len(parts) > 1 else ""
            if target == "all":
                if not prompt:
                    self.notify("Usage: @all <prompt>", severity="warning")
                    return
                self._append_user_card("@all", prompt)
                self._run_all_agents(prompt)
                return
            if target in self.cfg["agents"]:
                if not prompt:
                    self._set_active_agent(target)
                    return
                expanded, _ = self._expand_file_mentions(prompt)
                self._append_user_card(target, prompt)
                self._run_ai(target, expanded)
                return

        bare_interactive = {"gemini", "claude", "agy", "opencode", "codex", "crush", "hermes", "aider", "lazygit", "dsh", "zsh"}
        if line in bare_interactive and not self.shell_mode:
            if line in self.cfg["agents"]:
                a = self.cfg["agents"][line]
                cmd = ai_hub.build_cmd(a, "", "", False, interactive=True)
                self._run_native_cmd(cmd, title=line)
            else:
                self._run_native_cmd([line], title=line)
            return

        if self.shell_mode:
            self._handle_shell(line)
            return

        expanded, _ = self._expand_file_mentions(line)
        self._append_user_card(self.active_agent, line)
        self._run_ai(self.active_agent, expanded)

    def _change_cwd(self, target: str) -> None:
        p = Path(target).expanduser()
        if not p.is_absolute():
            p = Path(self.cwd) / p
        p = p.resolve()
        if not p.is_dir():
            self.notify(f"Not a directory: {p}", severity="error")
            return
        self.cwd = str(p)
        self.notify(f"CWD: {self.cwd}")

    def _handle_shell(self, sh: str) -> None:
        interactive_tools = {
            "lazygit", "fzf", "btop", "vim", "nvim", "nano", "less", "top", "zsh", "bash",
            "opencode", "gemini", "claude", "agy", "codex", "crush", "hermes", "aider", "copilot", "dsh",
        }
        first = shlex.split(sh)[0] if sh else ""
        if Path(first).name in interactive_tools and len(shlex.split(sh)) == 1:
            shell_bin = os.environ.get("SHELL", "/bin/sh")
            self._run_native_cmd([shell_bin, "-ic", sh], title=sh)
            return
        self._append_user_card("SHELL", f"!{sh}")
        self._run_shell_bg(sh)

    @work
    async def _run_shell_bg(self, sh: str) -> None:
        tw = ThinkingWidget("shell", sh[:70])
        self.active_thinking.append(tw)
        self.busy_label = f"run {sh.split()[0]}"
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        await scroll.mount(tw)
        self._scroll_bottom()
        t0 = time.time()

        def _exec():
            return subprocess.run(
                sh, shell=True, cwd=self.cwd, env=self.env,
                capture_output=True, text=True, timeout=120,
            )

        try:
            proc = await asyncio.to_thread(_exec)
            rc, out, err = proc.returncode, ai_hub.clean(proc.stdout or ""), ai_hub.clean(proc.stderr or "")
        except Exception as e:
            rc, out, err = 1, "", str(e)
        finally:
            if tw in self.active_thinking:
                self.active_thinking.remove(tw)
            await tw.remove()
            self.busy_label = ""
        self._append_shell_card(sh, rc, out, err, round(time.time() - t0, 1))

    @work
    async def _run_api_bg(self, api_line: str) -> None:
        """Run open-source API query; supports piping to AI via `/api <cmd> | <prompt>`."""
        pipe_prompt = ""
        api_cmd = api_line
        if "|" in api_line:
            left, right = api_line.split("|", 1)
            api_cmd = left.strip()
            pipe_prompt = right.strip()
        tw = ThinkingWidget("API", api_cmd[:70])
        self.active_thinking.append(tw)
        self.busy_label = f"api {api_cmd.split()[0] if api_cmd else ''}"
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        await scroll.mount(tw)
        self._scroll_bottom()
        try:
            res = await asyncio.to_thread(api_hub.run_api, api_cmd)
        finally:
            if tw in self.active_thinking:
                self.active_thinking.remove(tw)
            await tw.remove()
            self.busy_label = ""
        self._append_info_card(res["markdown"], title=res["title"])
        if pipe_prompt and res.get("ok"):
            combined = f"{pipe_prompt}\n\nData from API ({res['title']}):\n{res['markdown'][:3500]}"
            self._run_ai(self.active_agent, combined)

    @work
    async def _run_ai(self, agent: str, prompt: str) -> None:
        tw = ThinkingWidget(agent, prompt[:70])
        cancel_ev = threading.Event()
        self._cancel_events.append(cancel_ev)
        self.active_thinking.append(tw)
        self.busy_label = f"{agent}…"
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        await scroll.mount(tw)
        self._scroll_bottom()
        model = self.active_model if agent == self.active_agent else ""
        cont = self.cont if agent == self.active_agent else False
        hist_snapshot = list(self.chat_history[-12:]) if cont else []

        def on_chunk(txt: str) -> None:
            self.call_from_thread(tw.set_stream_text, txt)

        def on_attempt(ag: str, m: str) -> None:
            self.call_from_thread(tw.set_attempt, ag, m)

        try:
            res = await asyncio.to_thread(
                ai_hub.ask_with_fallback,
                self.cfg, agent, prompt, model, cont, self.cwd, self.env, self.timeout,
                None, True, on_chunk, cancel_ev, on_attempt, hist_snapshot,
            )
        finally:
            if cancel_ev in self._cancel_events:
                self._cancel_events.remove(cancel_ev)
            if tw in self.active_thinking:
                self.active_thinking.remove(tw)
            await tw.remove()
            self.busy_label = ""
        if agent == self.active_agent and res.get("ok"):
            self.cont = True
            self.chat_history.append({"role": "user", "content": prompt})
            self.chat_history.append({"role": "assistant", "content": res.get("output", "")})
            self._save_session()
        self._append_ai_card(res)

    @work
    async def _run_all_agents(self, prompt: str) -> None:
        fast_order = ["opencode", "mods", "ollama", "llm", "hermes", "aider"]
        names = [
            n for n in fast_order
            if n in self.cfg["agents"] and ai_hub.find_bin(self.cfg["agents"][n])
        ]
        if not names:
            self.notify("No ready AI agents found", severity="error")
            return
        cancel_ev = threading.Event()
        self._cancel_events.append(cancel_ev)
        tw = ThinkingWidget(f"@all ({len(names)} agents)", prompt[:70])
        self.active_thinking.append(tw)
        self.busy_label = f"@all ({len(names)})"
        scroll = self.query_one("#stream-scroll", VerticalScroll)
        await scroll.mount(tw)
        self._scroll_bottom()

        cloud = [n for n in names if n == "opencode"]
        local_cpu = [n for n in names if n != "opencode"]

        async def _run_local_seq():
            for n in local_cpu:
                if cancel_ev.is_set():
                    break
                res = await asyncio.to_thread(
                    ai_hub.ask, self.cfg, n, prompt, "", False, self.cwd, self.env, self.timeout, None, cancel_ev
                )
                self._append_ai_card(res)

        async def _run_cloud(n: str):
            res = await asyncio.to_thread(
                ai_hub.ask, self.cfg, n, prompt, "", False, self.cwd, self.env, self.timeout, None, cancel_ev
            )
            self._append_ai_card(res)

        try:
            coros = [_run_cloud(n) for n in cloud] + [_run_local_seq()]
            await asyncio.gather(*coros)
        finally:
            if cancel_ev in self._cancel_events:
                self._cancel_events.remove(cancel_ev)
            if tw in self.active_thinking:
                self.active_thinking.remove(tw)
            await tw.remove()
            self.busy_label = ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Nexus Terminal TUI")
    ap.add_argument("--agent", default="opencode")
    ap.add_argument("--model", default="")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--timeout", type=int, default=None)
    args = ap.parse_args()
    app = NexusTerminal(args.agent, args.model, args.cwd, args.timeout)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
