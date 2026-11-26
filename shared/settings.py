#!/usr/bin/env python3
"""One table and one resolver for every Proofs setting. Python 3 standard library only.

    python3 <plugin root>/shared/settings.py --print
    python3 <plugin root>/shared/settings.py --json
    python3 <plugin root>/shared/settings.py --set KEY=VALUE [--scope user|project|local]
    python3 <plugin root>/shared/settings.py --unset KEY [--scope user|project|local]
    python3 <plugin root>/shared/settings.py --spec [--out PATH]
    python3 <plugin root>/shared/settings.py --apply ROWS_DIR [--dry-run]

--print shows every setting, its effective value and where the value came from; --json
prints the same as {KEY: {"value", "source", "default", "note"}}. --set and --unset write the
`env` block of a Claude Code settings file, only for keys in settings.json (all start with
PROOFS_), and keep every other key in the file as it is. --spec prints a review-page builder
spec of the effective settings (mode "settings": the settings page). Without --scope a
setting goes where the table says: user is ~/.claude/settings.json (or $CLAUDE_CONFIG_DIR/settings.json),
project is .claude/settings.json (committed), local is .claude/settings.local.json.

--apply writes the changes the settings page saved: ROWS_DIR is the folder ArtifactData `list`
wrote with out_dir (or its proofs-answers folder). Each row of kind "setting" with an answer is
validated and written with --set's rules, at the row's scope. A row with no `from`, or whose
`from` is no longer the current value (the setting changed since the page was built), whose
value fails validation or whose key is unknown is skipped and listed. So is a row a narrower
settings file still overrides after the write ("still overridden by project file (...)"). A
row with a null answer (an undone change) is ignored. --dry-run prints what would happen and
writes nothing.

`auto` for an auto setting, and the default of the pr-qa base folder, mean "not set": --set
and --apply remove the key instead of writing that value.

Exit codes: 0 ok, 2 invalid value, unknown key or bad usage, 3 a settings file that cannot be
read (nothing is written to it).

Resolution order: local file, project file, user file, the process environment, the default.
Files beat the environment because Claude Code copies the files into the environment only at
startup, so a --set made mid-session must still win; the entry then carries a note that the
running hooks need a restart to see it. The project root is the nearest folder above the
working directory that holds .claude or .git (never the home folder).

From another script:  import settings; settings.get("PROOFS_PORT")  (typed: an int is an int)
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent / "settings.json"
PREFIX = "PROOFS_"
SCOPES = ("user", "project", "local")
SOURCES = ("local", "project", "user")  # files, strongest first
GROUP_TITLES = {
    "read": "Reading and cost",
    "checks": "Checks on this site",
    "app": "Running the app",
    "prs": "Pull requests",
    "computer": "This computer",
}
RESTART_NOTE = "restart Claude Code to pass the new value to hooks"
BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off")
# Refused in every value: these end up in commands Claude runs. The page and settings.cjs use
# the same character range.
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


class SettingError(Exception):
    """A value or key the settings refuse; the message is what the page and CLI show."""


class SettingsFileError(SettingError):
    """A settings file that cannot be read or does not have the shape Claude Code expects."""


def load_table():
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def _row(key):
    for row in load_table():
        if row["key"] == key:
            return row
    raise SettingError("%s is not a Proofs setting." % key)


# ---------------------------------------------------------------- validation

def _unit(row):
    return (" " + row["unit"]) if row.get("unit") else ""


def _int(row, raw, what=None):
    text = str(raw).strip()
    label = what or row["label"]
    try:
        # ASCII digits only (str.isdigit also takes "²" and "٣"), so the settings page's own
        # check, built from this same table, refuses exactly what this one refuses.
        if (not text.isascii() or text.lstrip("+-") != text.lstrip("+-").strip()
                or not text.lstrip("+-").isdigit()):
            raise ValueError
        n = int(text)
    except ValueError:
        raise SettingError("%s must be a whole number from %s to %s." % (label, row["min"], row["max"]))
    if row.get("raise_only") and n < row["default"]:
        raise SettingError("%s can only go up from %s%s." % (row["label"], row["default"], _unit(row)))
    if n < row["min"] or n > row["max"]:
        raise SettingError("%s must be a whole number from %s to %s%s." % (label, row["min"], row["max"], _unit(row)))
    return n


def _split(raw):
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def _path(row, text):
    """path_kind "project": a path inside the project (no absolute path, no .. segment).
    path_kind "absolute": an absolute path, or the default (which means "not set")."""
    kind = row.get("path_kind")
    if kind == "project":
        if text.startswith(("/", "\\", "~")) or DRIVE.match(text):
            raise SettingError("%s must be a path inside the project, not an absolute one." % row["label"])
        if ".." in re.split(r"[\\/]", text):
            raise SettingError("%s cannot use .. to leave the project." % row["label"])
    elif kind == "absolute" and text != row["default"] and not text.startswith("/"):
        raise SettingError("%s must be an absolute folder path (starting with /), or %s."
                           % (row["label"], row["default"]))
    return text


def _parse(row, raw):
    kind = row["type"]
    if raw is not None and CONTROL_CHARS.search(str(raw)):
        raise SettingError("%s cannot contain control characters such as a line break." % row["label"])
    text = "" if raw is None else str(raw).strip()
    if kind == "int":
        return _int(row, text)
    if kind == "choice":
        if text not in row["choices"]:
            raise SettingError("%s must be one of: %s." % (row["label"], ", ".join(row["choices"])))
        return int(text) if all(c.isdigit() for c in row["choices"]) else text
    if kind == "bool":
        low = text.lower()
        if low in BOOL_TRUE:
            return True
        if low in BOOL_FALSE:
            return False
        raise SettingError("%s must be on or off (1 or 0)." % row["label"])
    if kind == "list":
        items = _split(text)
        if row.get("item_type") == "int":
            return [_int(row, i, "%s (each width)" % row["label"]) for i in items]
        if not items and row["default"]:
            raise SettingError("%s needs at least one entry, separated by commas." % row["label"])
        return items
    # text, path, auto: any non-empty string
    if not text:
        raise SettingError("%s cannot be empty." % row["label"])
    return _path(row, text)


def validate(key, raw):
    """The typed value for raw, or SettingError with the message the page and CLI show."""
    return _parse(_row(key), raw)


def _means_unset(row, value):
    """True for a value that is the same as leaving the setting out: `auto` for an auto setting
    (a literal "auto" would reach the browser launch as a channel name) and the default of an
    absolute-path setting (pr-qa reads any value it is given as an absolute path)."""
    return ((row["type"] == "auto" and value == "auto")
            or (row.get("path_kind") == "absolute" and value == row["default"]))


def _canonical(row, value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------- files

def _home(home):
    return Path(home) if home else Path(os.environ.get("HOME") or Path.home())


def _env(env):
    return os.environ if env is None else env


def _user_file(env, home):
    cfg = _env(env).get("CLAUDE_CONFIG_DIR")
    base = Path(os.path.expanduser(cfg)) if cfg else _home(home) / ".claude"
    return base / "settings.json"


def _project_root(cwd, home):
    """Nearest folder from cwd upward that holds .claude or .git, or None. Never the home folder."""
    here = Path(cwd or os.getcwd()).resolve()
    skip = _home(home).resolve()
    for folder in [here, *here.parents]:
        if folder == skip:
            continue
        if (folder / ".claude").is_dir() or (folder / ".git").exists():
            return folder
    return None


def settings_path(scope, *, cwd=None, env=None, home=None):
    """The settings file for a scope. With no project root above cwd, project and local use cwd."""
    if scope == "user":
        return _user_file(env, home)
    root = _project_root(cwd, home) or Path(cwd or os.getcwd()).resolve()
    return root / ".claude" / ("settings.json" if scope == "project" else "settings.local.json")


def _read_file(path):
    """The parsed settings object, or None for a file that is not there. SettingsFileError otherwise."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise SettingsFileError("Cannot read %s: %s." % (path, e))
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as e:
        raise SettingsFileError("%s is not valid JSON (%s). Fix it by hand; nothing was changed." % (path, e))
    if not isinstance(data, dict):
        raise SettingsFileError("%s must hold a JSON object. Nothing was changed." % path)
    if "env" in data and not isinstance(data["env"], dict):
        raise SettingsFileError('The "env" entry in %s must be an object. Nothing was changed.' % path)
    return data


def _file_env(path):
    data = _read_file(path)
    return (data or {}).get("env", {}) if data else {}


# ---------------------------------------------------------------- resolving

def effective(*, cwd=None, env=None, home=None):
    """{key: {"value", "source", "default", "note"}} for every setting in the table."""
    environ = _env(env)
    files = {s: _file_env(settings_path(s, cwd=cwd, env=environ, home=home)) for s in SOURCES}
    if _project_root(cwd, home) is None:
        files["project"] = files["local"] = {}
    out = {}
    for row in load_table():
        key = row["key"]
        candidates = [(s, files[s].get(key)) for s in SOURCES] + [("environment", environ.get(key))]
        value, source, notes, winning_raw = row["default"], "default", [], None
        file_hit = None
        for src, raw in candidates:
            if raw is None or (isinstance(raw, str) and raw == "" and row["type"] != "list"):
                continue
            try:
                value, source, winning_raw = _parse(row, raw), src, raw
            except SettingError as e:
                notes.append("ignored %s value %r from %s: %s" % (key, raw, src, e))
                continue
            break
        if source in SOURCES:
            file_hit = winning_raw
        env_raw = environ.get(key)
        if file_hit is not None and env_raw is not None and str(env_raw).strip() != str(file_hit).strip():
            notes.append(RESTART_NOTE)
        out[key] = {"value": value, "source": source, "default": row["default"], "note": "; ".join(notes)}
    return out


def get(key, *, cwd=None, env=None, home=None):
    _row(key)
    return effective(cwd=cwd, env=env, home=home)[key]["value"]


# ---------------------------------------------------------------- writing

def _indent_of(text):
    """The indent the file already uses (spaces or a tab), so a write does not reformat it."""
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped and stripped != line:
            return line[:len(line) - len(stripped)]
    return 2


def _write_env(path, mutate):
    """Apply mutate(env_dict) to the file's env block and write it back, keeping every other key.
    Returns True when the file was written. Raises SettingsFileError and leaves the file alone
    when it cannot be parsed. A symlinked file (a dotfiles checkout) is written through: the
    link stays a link and its target gets the new text."""
    path = Path(path).resolve()
    data = _read_file(path)
    original_text = path.read_text(encoding="utf-8") if data is not None else ""
    indent = _indent_of(original_text) if data is not None else 2
    new = dict(data) if data is not None else {}
    env_block = dict(new.get("env", {}))
    before = dict(env_block)
    mutate(env_block)
    if data is not None and env_block == before:
        return False
    new["env"] = env_block
    text = json.dumps(new, indent=indent, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def _scope(row, scope):
    scope = scope or row["scope"]
    if scope not in SCOPES:
        raise SettingError("Scope must be one of: %s." % ", ".join(SCOPES))
    return scope


def set_value(key, raw, scope=None, *, cwd=None, env=None, home=None):
    """Validate raw and write it to the scope's settings file (default: the table's scope).
    A value that means "not set" (`auto`, or the default of the pr-qa base folder) removes the
    key instead, so the file never holds it. Returns the file's path."""
    row = _row(key)
    value = _parse(row, raw)
    path = settings_path(_scope(row, scope), cwd=cwd, env=env, home=home)
    if _means_unset(row, value):
        if Path(path).exists():
            _write_env(path, lambda block: block.pop(key, None))
        return path
    stored = _canonical(row, value)
    _write_env(path, lambda block: block.__setitem__(key, stored))
    return path


def removes_key(key, raw):
    """True when set_value(key, raw) removes the key rather than writing raw."""
    row = _row(key)
    return _means_unset(row, _parse(row, raw))


def unset(key, scope=None, *, cwd=None, env=None, home=None):
    """Remove one key from the scope's env block. Returns the file's path."""
    row = _row(key)
    path = settings_path(_scope(row, scope), cwd=cwd, env=env, home=home)
    if Path(path).exists():
        _write_env(path, lambda block: block.pop(key, None))
    return path


# ---------------------------------------------------------------- the settings page

def _display_path(path, home):
    path, base = Path(path), _home(home).resolve()
    try:
        return "~/" + str(path.resolve().relative_to(base))
    except ValueError:
        return str(path)


def page_spec(*, cwd=None, env=None, home=None):
    """A review-page builder spec (mode "settings") of every setting: its table row plus the
    effective value, where it came from and any note. Build it with
    shared/review_page/review_page.py to get the settings page."""
    environ = _env(env)
    eff = effective(cwd=cwd, env=environ, home=home)
    root = _project_root(cwd, home) or Path(cwd or os.getcwd()).resolve()
    rows = [dict(row, value=eff[row["key"]]["value"], source=eff[row["key"]]["source"], note=eff[row["key"]]["note"])
            for row in load_table()]
    return {
        "mode": "settings", "title": "Proofs settings", "project": {"name": root.name},
        "files": {"user": _display_path(_user_file(environ, home), home),
                  "project": ".claude/settings.json", "local": ".claude/settings.local.json"},
        "settings": rows,
        "send_wait_ms": eff["PROOFS_SEND_WAIT_MIN"]["value"] * 60000,
    }


# ---------------------------------------------------------------- applying saved rows

def _row_files(path):
    path = Path(path)
    if path.is_dir():
        return [f for n in sorted(os.listdir(path)) for f in _row_files(path / n)]
    return [path] if path.suffix == ".json" else []


def _unwrap(value):
    """The row bodies in a parsed rows file: the body itself, {"data": body}, or a list or
    {"documents": [...]} of them (the same shapes shared/review_page/answers.cjs reads)."""
    if isinstance(value, list):
        return [b for v in value for b in _unwrap(v)]
    if not isinstance(value, dict):
        return []
    for k in ("documents", "docs"):
        if isinstance(value.get(k), list):
            return _unwrap(value[k])
    if isinstance(value.get("data"), dict) and value["data"].get("kind"):
        return [value["data"]]
    return [value] if value.get("kind") else []


def saved_rows(path):
    """The kind "setting" rows with an answer from a rows folder or file, in file order.
    A null answer is an undone change and is left out."""
    if not Path(path).exists():
        raise SettingError("%s does not exist." % path)
    out = []
    for f in _row_files(path):
        try:
            bodies = _unwrap(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise SettingsFileError("Cannot read %s: %s." % (f, e))
        out += [b for b in bodies if b.get("kind") == "setting" and b.get("answer") is not None]
    return out


def _override(key, scope, new, *, cwd, env, home):
    """For --dry-run: (source, path) of the file that would still decide key after writing new
    to scope, when it holds another valid value; else None. That is a narrower file, or, for a
    value that removes the key, the next file down too. The environment is never counted:
    files beat it."""
    row = _row(key)
    removing = _means_unset(row, _parse(row, new))
    others = [s for s in SOURCES if s != scope] if removing else SOURCES[:SOURCES.index(scope)]
    if _project_root(cwd, home) is None:
        others = [s for s in others if s == "user"]
    for src in others:
        path = settings_path(src, cwd=cwd, env=env, home=home)
        raw = _file_env(path).get(key)
        if raw is None or (isinstance(raw, str) and raw == "" and row["type"] != "list"):
            continue
        try:
            held = _canonical(row, _parse(row, raw))
        except SettingError:
            continue  # an invalid value is skipped by the resolver too
        return None if held == new else (src, path)
    return None


def apply_rows(path, dry_run=False, *, cwd=None, env=None, home=None):
    """Apply the saved rows. Returns (lines, skipped): the report lines and how many rows were skipped.
    A row is skipped when it has no `from` (the value the page showed), when `from` is no longer
    the current value, when its value or key is refused, and when a narrower settings file
    still overrides the key after the write (the write happened but changes nothing)."""
    lines, skipped = [], 0
    for r in saved_rows(path):
        key = str(r.get("id") or r.get("key") or "")
        try:
            row = _row(key)
            raw = str(r["answer"])
            new_value = validate(key, raw)
            scope = _scope(row, r.get("scope"))
            current = effective(cwd=cwd, env=env, home=home)[key]["value"]
            now = _canonical(row, current)
            shown = r.get("from")
            if shown is None:
                raise SettingError("no shown value; reopen the page.")
            if str(shown) != now:
                raise SettingError("the page showed %s but it is now %s; open the page again." % (shown, now))
            target = settings_path(scope, cwd=cwd, env=env, home=home)
            new = _canonical(row, new_value)
            if dry_run:
                hit = _override(key, scope, new, cwd=cwd, env=env, home=home)
            else:
                set_value(key, raw, scope, cwd=cwd, env=env, home=home)
                after = effective(cwd=cwd, env=env, home=home)[key]
                hit = None
                if after["source"] in SOURCES and _canonical(row, after["value"]) != new:
                    hit = (after["source"], settings_path(after["source"], cwd=cwd, env=env, home=home))
            if hit:
                raise SettingError("still overridden by %s file (%s)" % hit)
            where = ("removed from %s %s" if _means_unset(row, new_value) else "%s %s") % (scope, target)
            lines.append("%s %s %s \u2192 %s (%s)" % ("WOULD APPLY" if dry_run else "APPLIED", key, now, new, where))
        except SettingError as e:
            skipped += 1
            lines.append("SKIPPED %s: %s" % (key or "(no key)", e))
    return lines, skipped


# ---------------------------------------------------------------- CLI

def _show(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ",".join(str(v) for v in value) or "none"
    return str(value)


def _print_table():
    eff = effective()
    table = load_table()
    for group, title in GROUP_TITLES.items():
        rows = [r for r in table if r["group"] == group]
        print(title)
        for r in rows:
            e = eff[r["key"]]
            flag = " (advanced)" if r["advanced"] else ""
            changed = "" if e["source"] == "default" else " [default %s]" % _show(e["default"])
            shown = _show(e["value"]) + ("" if e["value"] == [] else _unit(r))
            line = "  %-30s %-22s %-12s%s%s" % (r["key"], shown, e["source"], changed, flag)
            print(line.rstrip())
            if e["note"]:
                print("      note: " + e["note"])
        print()


def main(argv):
    parser = argparse.ArgumentParser(prog="settings.py", description="Show or change Proofs settings.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", dest="show", action="store_true", help="a table of every setting")
    mode.add_argument("--json", dest="as_json", action="store_true", help="the same, as JSON")
    mode.add_argument("--set", metavar="KEY=VALUE")
    mode.add_argument("--unset", metavar="KEY")
    mode.add_argument("--spec", action="store_true", help="a builder spec for the settings page")
    mode.add_argument("--apply", metavar="ROWS_DIR", help="write the changes the settings page saved")
    parser.add_argument("--scope", choices=SCOPES)
    parser.add_argument("--out", metavar="PATH", help="with --spec: write the spec to PATH instead of printing it")
    parser.add_argument("--dry-run", action="store_true", help="with --apply: report, write nothing")
    args = parser.parse_args(argv[1:])  # argparse exits 2 on bad usage
    if args.scope and not (args.set or args.unset):
        parser.error("--scope goes with --set or --unset")
    if args.out and not args.spec:
        parser.error("--out goes with --spec")
    if args.dry_run and not args.apply:
        parser.error("--dry-run goes with --apply")
    if args.scope and args.apply:
        parser.error("--apply uses each row's own scope")
    try:
        if args.apply:
            lines, skipped = apply_rows(args.apply, args.dry_run)
            for line in lines:
                print(line)
            return 1 if skipped else 0
        if args.as_json:
            print(json.dumps(effective(), indent=2, ensure_ascii=False))
        elif args.spec:
            text = json.dumps(page_spec(), indent=2, ensure_ascii=False)
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(text + "\n", encoding="utf-8")
                print("settings page spec saved to %s" % args.out)
            else:
                print(text)
        elif args.show:
            _print_table()
        elif args.set is not None:
            if "=" not in args.set:
                raise SettingError("Use --set KEY=VALUE.")
            key, raw = args.set.split("=", 1)
            key = key.strip()
            path = set_value(key, raw, args.scope)
            if removes_key(key, raw):
                print("%s reset to %s (removed from %s)" % (key, raw.strip(), path))
            else:
                print("%s saved to %s" % (key, path))
        else:
            path = unset(args.unset.strip(), args.scope)
            print("%s removed from %s" % (args.unset.strip(), path))
    except SettingsFileError as e:
        print("settings: %s" % e, file=sys.stderr)
        return 3
    except SettingError as e:
        print("settings: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
