// The node reader for Proofs settings: the same table (settings.json) and the same
// resolution order as settings.py, so the two never disagree.
//
//   const settings = require("<plugin root>/shared/settings.cjs");
//   settings.get("PROOFS_MIN_TEXT")                    // 16, a number
//   settings.get("PROOFS_EXTRA_WIDTHS", { cwd, env, home })
//
// Order: local file, project file, user file, the process environment, the default. The
// files are the `env` block of .claude/settings.local.json, .claude/settings.json and
// ~/.claude/settings.json ($CLAUDE_CONFIG_DIR/settings.json). A value that fails validation
// is skipped for the next source, as in settings.py. A settings file that cannot be read
// throws a SettingsFileError with a one-line message naming the file, as settings.py does.
// validate(key, raw) refuses exactly what settings.py's validate() refuses, with the same
// message. Reading only: writing goes through settings.py --set.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");

const TABLE_PATH = path.join(__dirname, "settings.json");
const SOURCES = ["local", "project", "user"];
const BOOL_TRUE = ["1", "true", "yes", "on"];
const BOOL_FALSE = ["0", "false", "no", "off"];

class SettingError extends Error {}
class SettingsFileError extends SettingError {}
// Refused in every value, as in settings.py: these end up in commands Claude runs.
const CONTROL_CHARS = /[\x00-\x1f\x7f]/;

function loadTable() {
  return JSON.parse(fs.readFileSync(TABLE_PATH, "utf8"));
}

function row(key) {
  const r = loadTable().find((x) => x.key === key);
  if (!r) throw new SettingError(`${key} is not a Proofs setting.`);
  return r;
}

const unit = (r) => (r.unit ? ` ${r.unit}` : "");

function parseInt10(r, text, what) {
  const label = what || r.label;
  if (!/^[+-]?[0-9]+$/.test(text)) throw new SettingError(`${label} must be a whole number from ${r.min} to ${r.max}.`);
  const n = parseInt(text, 10);
  if (r.raise_only && n < r.default) throw new SettingError(`${r.label} can only go up from ${r.default}${unit(r)}.`);
  if (n < r.min || n > r.max) throw new SettingError(`${label} must be a whole number from ${r.min} to ${r.max}${unit(r)}.`);
  return n;
}

// path_kind "project": inside the project; "absolute": an absolute path or the default.
function checkPath(r, text) {
  if (r.path_kind === "project") {
    if (/^[/\\~]/.test(text) || /^[A-Za-z]:[\\/]/.test(text)) throw new SettingError(`${r.label} must be a path inside the project, not an absolute one.`);
    if (text.split(/[\\/]/).includes("..")) throw new SettingError(`${r.label} cannot use .. to leave the project.`);
  } else if (r.path_kind === "absolute" && text !== r.default && !text.startsWith("/")) {
    throw new SettingError(`${r.label} must be an absolute folder path (starting with /), or ${r.default}.`);
  }
  return text;
}

const split = (raw) => String(raw).split(",").map((p) => p.trim()).filter(Boolean);

function parse(r, raw) {
  if (raw !== null && raw !== undefined && CONTROL_CHARS.test(String(raw))) {
    throw new SettingError(`${r.label} cannot contain control characters such as a line break.`);
  }
  const text = raw === null || raw === undefined ? "" : String(raw).trim();
  switch (r.type) {
    case "int": return parseInt10(r, text);
    case "choice":
      if (!r.choices.includes(text)) throw new SettingError(`${r.label} must be one of: ${r.choices.join(", ")}.`);
      return r.choices.every((c) => /^\d+$/.test(c)) ? parseInt(text, 10) : text;
    case "bool": {
      const low = text.toLowerCase();
      if (BOOL_TRUE.includes(low)) return true;
      if (BOOL_FALSE.includes(low)) return false;
      throw new SettingError(`${r.label} must be on or off (1 or 0).`);
    }
    case "list": {
      const items = split(text);
      if (r.item_type === "int") return items.map((i) => parseInt10(r, i, `${r.label} (each width)`));
      if (!items.length && r.default.length) throw new SettingError(`${r.label} needs at least one entry, separated by commas.`);
      return items;
    }
    default:
      if (!text) throw new SettingError(`${r.label} cannot be empty.`);
      return checkPath(r, text);
  }
}

function realpath(p) {
  try { return fs.realpathSync(p); } catch (_) { return path.resolve(p); }
}

function homeDir(home, env) {
  return home ? String(home) : (env.HOME || os.homedir());
}

function userFile(env, home) {
  const cfg = env.CLAUDE_CONFIG_DIR;
  const base = cfg ? cfg.replace(/^~(?=$|\/)/, os.homedir()) : path.join(homeDir(home, env), ".claude");
  return path.join(base, "settings.json");
}

function projectRoot(cwd, env, home) {
  const here = realpath(cwd || process.cwd());
  const skip = realpath(homeDir(home, env));
  let folder = here;
  for (;;) {
    if (folder !== skip) {
      let dir = false;
      try { dir = fs.statSync(path.join(folder, ".claude")).isDirectory(); } catch (_) { /* none */ }
      if (dir || fs.existsSync(path.join(folder, ".git"))) return folder;
    }
    const up = path.dirname(folder);
    if (up === folder) return null;
    folder = up;
  }
}

function readEnvBlock(file) {
  let text;
  try { text = fs.readFileSync(file, "utf8"); } catch (e) {
    if (e.code === "ENOENT") return {};
    throw new SettingsFileError(`Cannot read ${file}: ${e.message}.`);
  }
  let data;
  try { data = text.trim() ? JSON.parse(text) : {}; } catch (e) {
    throw new SettingsFileError(`${file} is not valid JSON (${String(e.message).split("\n")[0]}). Fix it by hand.`);
  }
  if (data === null || typeof data !== "object" || Array.isArray(data)) throw new SettingsFileError(`${file} must hold a JSON object.`);
  if ("env" in data && (data.env === null || typeof data.env !== "object" || Array.isArray(data.env))) {
    throw new SettingsFileError(`The "env" entry in ${file} must be an object.`);
  }
  return data.env || {};
}

// The typed value for `key`, resolved like settings.py's get().
function get(key, { cwd, env, home } = {}) {
  const environ = env || process.env;
  const r = row(key);
  const root = projectRoot(cwd, environ, home);
  const files = {
    user: readEnvBlock(userFile(environ, home)),
    project: root ? readEnvBlock(path.join(root, ".claude", "settings.json")) : {},
    local: root ? readEnvBlock(path.join(root, ".claude", "settings.local.json")) : {},
  };
  const candidates = SOURCES.map((s) => files[s][key]).concat([environ[key]]);
  for (const raw of candidates) {
    if (raw === undefined || raw === null || (typeof raw === "string" && raw === "" && r.type !== "list")) continue;
    try { return parse(r, raw); } catch (e) { if (!(e instanceof SettingError)) throw e; }
  }
  return r.default;
}

// The typed value for raw, or a SettingError with the message settings.py's validate() gives.
function validate(key, raw) {
  return parse(row(key), raw);
}

module.exports = { get, validate, loadTable, SettingError, SettingsFileError };
