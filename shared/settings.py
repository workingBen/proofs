#!/usr/bin/env python3
"""One table and one resolver for every Proofs setting. Python 3 standard library only.

    python3 <plugin root>/shared/settings.py --print
    python3 <plugin root>/shared/settings.py --json
    python3 <plugin root>/shared/settings.py --set KEY=VALUE [--scope user|project|local]
    python3 <plugin root>/shared/settings.py --unset KEY [--scope user|project|local]

--print shows every setting, its effective value and where the value came from; --json
prints the same as {KEY: {"value", "source", "default", "note"}}. --set and --unset write the
`env` block of a Claude Code settings file, only for keys in settings.json (all start with
PROOFS_), and keep every other key in the file as it is. Without --scope a setting goes where
the table says: user is ~/.claude/settings.json (or $CLAUDE_CONFIG_DIR/settings.json),
project is .claude/settings.json (committed), local is .claude/settings.local.json.

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
        if text.lstrip("+-") != text.lstrip("+-").strip() or not text.lstrip("+-").isdigit():
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


def _parse(row, raw):
    kind = row["type"]
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
    return text


def validate(key, raw):
    """The typed value for raw, or SettingError with the message the page and CLI show."""
    return _parse(_row(key), raw)


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
    when it cannot be parsed."""
    path = Path(path)
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
    Returns the file's path."""
    row = _row(key)
    value = _parse(row, raw)
    path = settings_path(_scope(row, scope), cwd=cwd, env=env, home=home)
    stored = _canonical(row, value)
    _write_env(path, lambda block: block.__setitem__(key, stored))
    return path


def unset(key, scope=None, *, cwd=None, env=None, home=None):
    """Remove one key from the scope's env block. Returns the file's path."""
    row = _row(key)
    path = settings_path(_scope(row, scope), cwd=cwd, env=env, home=home)
    if Path(path).exists():
        _write_env(path, lambda block: block.pop(key, None))
    return path


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
    parser.add_argument("--scope", choices=SCOPES)
    args = parser.parse_args(argv[1:])  # argparse exits 2 on bad usage
    if args.scope and not (args.set or args.unset):
        parser.error("--scope goes with --set or --unset")
    try:
        if args.as_json:
            print(json.dumps(effective(), indent=2, ensure_ascii=False))
        elif args.show:
            _print_table()
        elif args.set is not None:
            if "=" not in args.set:
                raise SettingError("Use --set KEY=VALUE.")
            key, raw = args.set.split("=", 1)
            path = set_value(key.strip(), raw, args.scope)
            print("%s saved to %s" % (key.strip(), path))
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
