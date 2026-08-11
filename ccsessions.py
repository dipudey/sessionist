#!/usr/bin/env python3
"""
ccsessions - a terminal UI to browse Claude Code sessions and jump straight in.

Scans ~/.claude/projects/<slug>/<session-id>.jsonl, lists every session grouped
by project with a preview, and on selection execs `claude --resume <id>` in that
project's directory.

Sessions can be given a custom label (rename) and deleted straight from the UI.
Labels live in a sidecar file (~/.claude/ccsessions_meta.json) so the session
JSONL is never rewritten; deleting removes the underlying .jsonl file.

Controls:
    type                filter (by project, label or preview text)
    up / down           move selection
    click a row         open that session
    click ✎ / press e   rename (label) the highlighted session
    click 🗑 / press d   delete the highlighted session (asks first)
    enter               open the highlighted session
    r                   rescan
    q / ctrl-c          quit

The JSONL line format is internal to Claude Code and may change between releases,
so parsing here is deliberately defensive: a session that can't be read simply
shows without a preview instead of crashing the app.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

APP_TITLE = "ccsessions"   # terminal + app window title


def set_terminal_title(title: str) -> None:
    """Set the terminal tab/window title via OSC escape (xterm/iTerm/Terminal)."""
    if sys.stdout.isatty():
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

# ----------------------------------------------------------------------------
# Data layer (no UI dependency, so it's independently testable)
# ----------------------------------------------------------------------------


def claude_dir() -> Path:
    """Honour CLAUDE_CONFIG_DIR like Claude Code does, else default to ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def meta_path() -> Path:
    return claude_dir() / "ccsessions_meta.json"


def load_meta() -> dict:
    """Sidecar {session_id: {"label": str}}. Missing / corrupt file -> empty."""
    try:
        with meta_path().open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_meta(meta: dict) -> None:
    path = meta_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        tmp.replace(path)
    except OSError:
        pass


@dataclass
class Session:
    session_id: str
    file: Path
    project_path: str          # true cwd if we could read it, else the slug dir name
    project_label: str         # short label for the table
    preview: str
    msg_count: int
    mtime: float
    label: str = ""            # user-set custom name (from sidecar)
    pinned: bool = False       # favorite flag (from sidecar)
    size_bytes: int = 0        # .jsonl size on disk
    search_text: str = ""      # lowercased full-conversation text, for deep search

    @property
    def key(self) -> str:
        return str(self.file)

    @property
    def age(self) -> str:
        return _relative_time(self.mtime)

    @property
    def display(self) -> str:
        """What shows in the Preview column: the custom label wins."""
        return self.label or self.preview


def _text_from_content(content) -> str:
    """Content may be a plain string or a list of blocks. Pull out the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def _parse_session(path: Path, meta: dict) -> Session | None:
    session_id = path.stem
    cwd = None
    preview = ""
    summary = ""
    msg_count = 0
    body_parts: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if cwd is None and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                if not summary and obj.get("type") == "summary" and obj.get("summary"):
                    summary = str(obj["summary"])
                t = obj.get("type")
                if t in ("user", "assistant"):
                    msg_count += 1
                    msg = obj.get("message") or {}
                    text = _text_from_content(msg.get("content")).strip()
                    if text:
                        body_parts.append(text)
                    if not preview and t == "user":
                        # skip empty (e.g. tool-result-only) and slash-command noise
                        if text and not text.startswith("<"):
                            preview = " ".join(text.split())
    except OSError:
        return None

    if summary and not preview:
        preview = summary
    if not preview:
        preview = "(no preview)"

    project_path = cwd or path.parent.name
    project_label = Path(project_path).name or project_path

    try:
        stat = path.stat()
        mtime = stat.st_mtime
        size_bytes = stat.st_size
    except OSError:
        mtime = 0.0
        size_bytes = 0

    entry = meta.get(session_id) or {}
    if isinstance(entry, dict):
        label = str(entry.get("label", ""))
        pinned = bool(entry.get("pinned", False))
    else:
        label = ""
        pinned = False

    return Session(
        session_id=session_id,
        file=path,
        project_path=project_path,
        project_label=project_label,
        preview=preview,
        msg_count=msg_count,
        mtime=mtime,
        label=label,
        pinned=pinned,
        size_bytes=size_bytes,
        search_text=" ".join(body_parts).lower(),
    )


def _same_dir(a: str, b: str) -> bool:
    """Path equality that survives symlinks / trailing slashes."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normpath(a) == os.path.normpath(b)


def find_sessions(scope: str | None = None) -> list[Session]:
    """All sessions, newest first.

    scope: if given, keep only sessions whose true cwd is that directory.
    """
    root = claude_dir() / "projects"
    if not root.is_dir():
        return []
    meta = load_meta()
    sessions: list[Session] = []
    for jsonl in root.glob("*/*.jsonl"):
        s = _parse_session(jsonl, meta)
        if s is None:
            continue
        if scope is not None and not _same_dir(s.project_path, scope):
            continue
        sessions.append(s)
    sessions.sort(key=lambda s: s.mtime, reverse=True)
    return sessions


def _get_entry(meta: dict, session_id: str) -> dict:
    entry = meta.get(session_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _put_entry(meta: dict, session_id: str, entry: dict) -> None:
    """Store entry, dropping empty keys; remove the entry entirely if bare."""
    entry = {k: v for k, v in entry.items() if v}
    if entry:
        meta[session_id] = entry
    else:
        meta.pop(session_id, None)


def set_label(session: Session, label: str) -> None:
    """Persist a custom label (empty string clears it), preserving other keys."""
    label = label.strip()
    meta = load_meta()
    entry = _get_entry(meta, session.session_id)
    entry["label"] = label
    _put_entry(meta, session.session_id, entry)
    save_meta(meta)
    session.label = label


def set_pin(session: Session, pinned: bool) -> None:
    """Persist the pinned flag, preserving the label."""
    meta = load_meta()
    entry = _get_entry(meta, session.session_id)
    entry["pinned"] = bool(pinned)
    _put_entry(meta, session.session_id, entry)
    save_meta(meta)
    session.pinned = bool(pinned)


def read_transcript(path: Path) -> str:
    """Full user/assistant conversation as plain text. Read-only, never resumes."""
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                t = obj.get("type")
                if t not in ("user", "assistant"):
                    continue
                msg = obj.get("message") or {}
                text = _text_from_content(msg.get("content")).strip()
                if not text:
                    continue
                role = "You" if t == "user" else "Claude"
                lines.append(f"[b]{role}:[/b] {text}")
    except OSError as exc:
        return f"(could not read transcript: {exc})"
    return "\n\n".join(lines) if lines else "(empty transcript)"


def _human_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n}{unit}" if unit == "B" else f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}G"


def delete_session(session: Session) -> bool:
    """Remove the .jsonl file and drop its sidecar entry. True on success."""
    try:
        session.file.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    meta = load_meta()
    if meta.pop(session.session_id, None) is not None:
        save_meta(meta)
    return True


def _relative_time(ts: float) -> str:
    if not ts:
        return "?"
    delta = max(0, time.time() - ts)
    for limit, div, unit in (
        (60, 1, "s"),
        (3600, 60, "m"),
        (86400, 3600, "h"),
        (7 * 86400, 86400, "d"),
    ):
        if delta < limit:
            return f"{int(delta // div)}{unit} ago"
    return f"{int(delta // 86400)}d ago"


# ----------------------------------------------------------------------------
# UI layer
# ----------------------------------------------------------------------------

def run_ui(sessions: list[Session], scope: str | None = None) -> Session | None:
    import subprocess

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

    # Column indices for the action cells (used to route clicks).
    # Columns: Mark · Project · When · Msgs · Size · Name/preview · ✎ · 🗑
    COL_EDIT = 6
    COL_DEL = 7

    SORT_MODES = ("recent", "msgs", "project")

    class RenameScreen(ModalScreen):
        """Prompt for a custom label for a session."""

        BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

        def __init__(self, session: Session):
            super().__init__()
            self.session = session

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Label(f"Rename session  ({self.session.session_id[:8]}…)", id="dtitle")
                yield Static(self.session.preview[:120], id="dhint")
                yield Input(
                    value=self.session.label,
                    placeholder="Custom name — empty clears it",
                    id="name",
                )
                with Horizontal(id="dbtns"):
                    yield Button("Save", variant="primary", id="save")
                    yield Button("Cancel", id="cancel")

        def on_mount(self) -> None:
            self.query_one("#name", Input).focus()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "save":
                self._save()
            else:
                self.dismiss(None)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            self._save()

        def action_cancel(self) -> None:
            self.dismiss(None)

        def _save(self) -> None:
            self.dismiss(self.query_one("#name", Input).value)

    class ConfirmScreen(ModalScreen):
        """Confirm an irreversible delete of one or many sessions."""

        BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

        def __init__(self, session: Session | None, bulk_count: int = 0):
            super().__init__()
            self.session = session
            self.bulk_count = bulk_count

        def compose(self) -> ComposeResult:
            if self.bulk_count:
                title = f"Delete {self.bulk_count} sessions?"
                body = (
                    f"[b]{self.bulk_count} marked session(s)[/b]\n\n"
                    f"[$error]This permanently removes their .jsonl files. "
                    f"Cannot be undone.[/$error]"
                )
            else:
                name = self.session.label or self.session.preview[:80]
                title = "Delete session?"
                body = (
                    f"[b]{name}[/b]\n"
                    f"{self.session.project_label} · {self.session.msg_count} msgs · {self.session.age}\n\n"
                    f"[$error]This permanently removes the .jsonl file. Cannot be undone.[/$error]"
                )
            with Vertical(id="dialog"):
                yield Label(title, id="dtitle")
                yield Static(body, id="dhint")
                with Horizontal(id="dbtns"):
                    yield Button("Delete", variant="error", id="ok")
                    yield Button("Cancel", variant="primary", id="cancel")

        def on_mount(self) -> None:
            self.query_one("#cancel", Button).focus()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            self.dismiss(event.button.id == "ok")

        def action_cancel(self) -> None:
            self.dismiss(False)

    class TranscriptScreen(ModalScreen):
        """Read-only scroll of a session's full conversation. Never resumes."""

        BINDINGS = [
            Binding("escape", "close", "Close", show=True),
            Binding("q", "close", "Close", show=False),
        ]

        def __init__(self, session: Session):
            super().__init__()
            self.session = session

        def compose(self) -> ComposeResult:
            head = self.session.label or self.session.preview[:70]
            with Vertical(id="tdialog"):
                yield Label(f"{self.session.project_label} — {head}", id="ttitle")
                with VerticalScroll(id="tbody"):
                    yield Static(read_transcript(self.session.file), id="ttext")
                yield Label("[dim]esc/q close · ↑↓ scroll[/dim]", id="tfoot")

        def on_mount(self) -> None:
            self.query_one("#tbody", VerticalScroll).focus()

        def action_close(self) -> None:
            self.dismiss(None)

    class SessionPicker(App):
        CSS = """
        Screen { layout: vertical; }
        #filter { dock: top; margin: 0 1; border: tall $accent; }
        DataTable { height: 1fr; }
        DataTable > .datatable--cursor { background: $accent 40%; }
        #details {
            dock: bottom; height: 6; padding: 0 1;
            border-top: solid $accent; color: $text-muted;
        }
        #details .k { color: $accent; }

        RenameScreen, ConfirmScreen, TranscriptScreen { align: center middle; }
        #dialog {
            width: 64; height: auto; padding: 1 2;
            background: $surface; border: thick $accent;
        }
        #dtitle { text-style: bold; color: $accent; width: 100%; }
        #dhint { color: $text-muted; margin: 1 0; }
        #name { margin: 1 0; }
        #dbtns { height: auto; align: right middle; }
        #dbtns Button { margin: 0 0 0 2; }

        #tdialog {
            width: 90%; height: 90%; padding: 1 2;
            background: $surface; border: thick $accent;
        }
        #ttitle { text-style: bold; color: $accent; width: 100%; }
        #tbody { height: 1fr; margin: 1 0; }
        #tfoot { color: $text-muted; width: 100%; text-align: right; }
        """
        BINDINGS = [
            Binding("enter", "open", "Open", show=True),
            Binding("v", "view", "View", show=True),
            Binding("e", "rename", "Rename", show=True),
            Binding("p", "pin", "Pin", show=True),
            Binding("space", "mark", "Mark", show=True),
            Binding("d", "delete", "Delete", show=True),
            Binding("s", "sort", "Sort", show=True),
            Binding("a", "toggle_scope", "Scope", show=True),
            Binding("y", "copy_id", "Copy id", show=True),
            Binding("Y", "copy_path", "Copy path", show=False),
            Binding("r", "rescan", "Rescan", show=True),
            Binding("q", "quit", "Quit", show=True),
            Binding("escape", "quit", "Quit", show=False),
            Binding("ctrl+c", "quit", "Quit", show=False),
        ]

        def __init__(self, sessions: list[Session], scope: str | None = None):
            super().__init__()
            self.all_sessions = sessions
            self.scope = scope
            self.sort_mode = 0                 # index into SORT_MODES
            self.marked: set[str] = set()      # session keys marked for bulk delete
            self.rows: dict[str, Session] = {}
            self.chosen: Session | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Input(placeholder="Filter by project, name or text…", id="filter")
            table = DataTable(id="table", cursor_type="cell", zebra_stripes=True)
            table.add_column("", width=3)   # ★ pinned / ✓ marked
            table.add_column("Project", width=22)
            table.add_column("When", width=9)
            table.add_column("Msgs", width=5)
            table.add_column("Size", width=6)
            table.add_column("Name / preview", width=54)
            table.add_column("", width=3)   # ✎  edit
            table.add_column("", width=3)   # 🗑  delete
            yield table
            yield Static("", id="details")
            yield Footer()

        def on_mount(self) -> None:
            self.title = "Claude Code sessions"
            self._populate(self.all_sessions)
            self.query_one(DataTable).focus()

        def _current_filter(self) -> str:
            return self.query_one("#filter", Input).value.strip().lower()

        def _visible(self) -> list[Session]:
            q = self._current_filter()
            if not q:
                return self.all_sessions
            return [
                s for s in self.all_sessions
                if q in s.project_path.lower()
                or q in s.preview.lower()
                or q in s.label.lower()
                or q in s.search_text
            ]

        def _sorted(self, sessions: list[Session]) -> list[Session]:
            """Pinned always float to top, then the active sort mode."""
            mode = SORT_MODES[self.sort_mode]
            if mode == "msgs":
                key = lambda s: (not s.pinned, -s.msg_count)
            elif mode == "project":
                key = lambda s: (not s.pinned, s.project_label.lower(), -s.mtime)
            else:  # recent
                key = lambda s: (not s.pinned, -s.mtime)
            return sorted(sessions, key=key)

        def _mark_cell(self, s: Session) -> str:
            flags = ("★" if s.pinned else "") + ("✓" if s.key in self.marked else "")
            return flags

        def _populate(self, sessions: list[Session]) -> None:
            sessions = self._sorted(sessions)
            table = self.query_one(DataTable)
            table.clear()
            self.rows.clear()
            for s in sessions:
                text = s.display
                text = text if len(text) <= 52 else text[:51] + "…"
                if s.label:
                    text = f"[b]{text}[/b]"
                table.add_row(
                    self._mark_cell(s), s.project_label, s.age, str(s.msg_count),
                    _human_size(s.size_bytes), text, "✎", "🗑", key=s.key
                )
                self.rows[s.key] = s
            where = Path(self.scope).name if self.scope else "all projects"
            extra = f" · {len(self.marked)} marked" if self.marked else ""
            self.sub_title = (
                f"{len(sessions)} session(s) · {where} · "
                f"sort:{SORT_MODES[self.sort_mode]}{extra}"
            )
            if sessions:
                self._show_details(sessions[0])
            else:
                self.query_one("#details", Static).update("No sessions found.")

        def on_input_changed(self, event: Input.Changed) -> None:
            self._populate(self._visible())

        def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
            s = self.rows.get(event.cell_key.row_key.value)
            if s:
                self._show_details(s)

        def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
            s = self.rows.get(event.cell_key.row_key.value)
            if not s:
                return
            col = event.coordinate.column
            if col == COL_EDIT:
                self._rename(s)
            elif col == COL_DEL:
                self._delete(s)
            else:
                self.chosen = s
                self.exit(s)

        def _show_details(self, s: Session) -> None:
            name = f"[b]{s.label}[/b]  " if s.label else ""
            star = "★ " if s.pinned else ""
            self.query_one("#details", Static).update(
                f"{star}{name}[b]path[/b]  {s.project_path}\n"
                f"[b]id[/b]    {s.session_id}\n"
                f"[b]{s.msg_count} msgs · {_human_size(s.size_bytes)} · {s.age}[/b]"
                f"   [dim](v view · e rename · p pin · space mark · d delete)[/dim]\n"
                f"{s.preview}"
            )

        def _highlighted(self) -> Session | None:
            table = self.query_one(DataTable)
            if not table.row_count:
                return None
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            return self.rows.get(key.value)

        def action_open(self) -> None:
            s = self._highlighted()
            if s:
                self.chosen = s
                self.exit(s)

        def action_rename(self) -> None:
            s = self._highlighted()
            if s:
                self._rename(s)

        def action_view(self) -> None:
            s = self._highlighted()
            if s:
                self.push_screen(TranscriptScreen(s))

        def action_pin(self) -> None:
            s = self._highlighted()
            if not s:
                return
            set_pin(s, not s.pinned)
            self._populate(self._visible())
            self.notify("Pinned" if s.pinned else "Unpinned")

        def action_mark(self) -> None:
            s = self._highlighted()
            if not s:
                return
            if s.key in self.marked:
                self.marked.discard(s.key)
            else:
                self.marked.add(s.key)
            self._populate(self._visible())

        def action_sort(self) -> None:
            self.sort_mode = (self.sort_mode + 1) % len(SORT_MODES)
            self._populate(self._visible())
            self.notify(f"Sort: {SORT_MODES[self.sort_mode]}")

        def action_toggle_scope(self) -> None:
            self.scope = None if self.scope else os.getcwd()
            self.all_sessions = find_sessions(self.scope)
            self.marked.clear()
            self._populate(self._visible())
            where = Path(self.scope).name if self.scope else "all projects"
            self.notify(f"Scope: {where}")

        def _copy(self, text: str, what: str) -> None:
            try:
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
                self.notify(f"Copied {what}")
            except (OSError, subprocess.CalledProcessError):
                self.notify("pbcopy unavailable", severity="error")

        def action_copy_id(self) -> None:
            s = self._highlighted()
            if s:
                self._copy(s.session_id, "session id")

        def action_copy_path(self) -> None:
            s = self._highlighted()
            if s:
                self._copy(s.project_path, "project path")

        def action_delete(self) -> None:
            if self.marked:
                self._delete_bulk()
                return
            s = self._highlighted()
            if s:
                self._delete(s)

        def _rename(self, s: Session) -> None:
            def done(value: str | None) -> None:
                if value is not None:
                    set_label(s, value)
                    self._populate(self._visible())
                    self.notify(f"Renamed to “{s.label}”" if s.label else "Label cleared")
            self.push_screen(RenameScreen(s), done)

        def _delete(self, s: Session) -> None:
            def done(ok: bool) -> None:
                if ok:
                    if delete_session(s):
                        self.all_sessions = [x for x in self.all_sessions if x.key != s.key]
                        self.marked.discard(s.key)
                        self._populate(self._visible())
                        self.notify(f"Deleted {s.session_id[:8]}…", severity="warning")
                    else:
                        self.notify("Delete failed", severity="error")
            self.push_screen(ConfirmScreen(s), done)

        def _delete_bulk(self) -> None:
            targets = [x for x in self.all_sessions if x.key in self.marked]
            if not targets:
                self.marked.clear()
                self._populate(self._visible())
                self.notify("No marked sessions to delete")
                return

            def done(ok: bool) -> None:
                if not ok:
                    return
                gone, failed = 0, 0
                for s in targets:
                    if delete_session(s):
                        gone += 1
                    else:
                        failed += 1
                self.all_sessions = [x for x in self.all_sessions if x.key not in self.marked]
                self.marked.clear()
                self._populate(self._visible())
                msg = f"Deleted {gone}"
                if failed:
                    msg += f", {failed} failed"
                self.notify(msg, severity="warning")
            self.push_screen(ConfirmScreen(None, bulk_count=len(targets)), done)

        def action_rescan(self) -> None:
            self.all_sessions = find_sessions(self.scope)
            self.marked.clear()
            self.query_one(Input).value = ""
            self._populate(self.all_sessions)

    app = SessionPicker(sessions, scope)
    if os.environ.get("CCSESSIONS_SMOKE"):
        import asyncio

        async def _smoke() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                first = next(iter(app.rows.values()))
                app._rename(first)          # push RenameScreen
                await pilot.pause()
                app.pop_screen()
                await pilot.pause()
                app._delete(first)          # push ConfirmScreen
                await pilot.pause()
                app.pop_screen()
                await pilot.pause()
                app.push_screen(TranscriptScreen(first))   # transcript view
                await pilot.pause()
                app.pop_screen()
                await pilot.pause()
                app.action_sort()           # cycle sort
                app.marked.add(first.key)   # mark then bulk-confirm
                app._delete_bulk()
                await pilot.pause()
                app.pop_screen()
                await pilot.pause()
                app.action_toggle_scope()   # flip scope last
                await pilot.pause()
        asyncio.run(_smoke())
        return None
    return app.run()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main() -> int:
    set_terminal_title(APP_TITLE)
    show_all = "--all" in sys.argv[1:] or "-a" in sys.argv[1:]
    scope = None if show_all else os.getcwd()

    sessions = find_sessions(scope)
    if not sessions and scope is not None:
        # Nothing for this project — fall back to every project.
        print(f"No sessions for {scope} — showing all projects (use --all to skip this).")
        scope = None
        sessions = find_sessions()

    if not sessions:
        print(f"No Claude Code sessions found under {claude_dir() / 'projects'}")
        return 1

    chosen = run_ui(sessions, scope)
    if chosen is None:
        return 0

    target = Path(chosen.project_path)
    if target.is_dir():
        os.chdir(target)
    else:
        print(f"Warning: project dir not found: {target} — resuming from here.")

    print(f"Resuming {chosen.session_id} in {os.getcwd()} …")
    try:
        os.execvp("claude", ["claude", "--resume", chosen.session_id])
    except FileNotFoundError:
        print("Error: `claude` not found on PATH. Is Claude Code installed?")
        return 127


if __name__ == "__main__":
    sys.exit(main())
