"""Backend read tools — Claude-Code-style READ access to the framework codebase.

The agent can list, read, and grep the source of every app installed on this
bench (frappe, erpnext, custom apps …) the way a developer with an editor would:
DocType JSON schemas, controllers, whitelisted APIs, hooks. That grounding lets
it wire data sources and `call()` endpoints against the REAL backend instead of
guessing. Strictly read-only — there is no write/execute surface here.

Access is jailed and gated:
  - System Manager role required (the Studio developer persona).
  - Paths resolve inside `<bench>/apps/<app>` only; traversal outside is refused.
  - Dotfiles/dirs, build output, and dependency dirs are invisible.
  - Reads are line- and size-capped so a huge file can't blow the context window.
"""

import fnmatch
import os
import re

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.agent.tools.page import text_arg

_SKIP_DIRS = {"node_modules", "__pycache__", "dist", "build", "env", ".git", ".venv"}
_MAX_LIST_PATHS = 500
_MAX_READ_LINES = 500
_MAX_LINE_CHARS = 400
_MAX_FILE_BYTES = 2_000_000
_MAX_MATCHES = 60
_MAX_SCANNED_FILES = 20_000


def run_list_backend_apps(ctx, args: dict) -> str:
	if denied := _denied():
		return denied
	apps = frappe.get_installed_apps()
	return "Apps installed on this site (usable as the 'app' argument):\n" + "\n".join(apps)


def run_list_backend_files(ctx, args: dict) -> str:
	if denied := _denied():
		return denied
	root_or_error = _resolve(args, allow_missing_path=True)
	if isinstance(root_or_error, str):
		return root_or_error
	root, start = root_or_error
	if not os.path.isdir(start):
		return f"FAILED: '{os.path.relpath(start, root)}' is not a directory in this app."
	paths = _walk_paths(root, start)
	if not paths:
		return "No files found under this path."
	note = (
		f"\n… truncated at {_MAX_LIST_PATHS} entries — pass a deeper 'path' to see more."
		if len(paths) >= _MAX_LIST_PATHS
		else ""
	)
	return (
		f"Files under {args.get('app')}/{args.get('path') or ''} (relative to the app repo root):\n"
		+ "\n".join(paths)
		+ note
	)


def run_read_backend_file(ctx, args: dict) -> str:
	if denied := _denied():
		return denied
	target_or_error = _resolve(args)
	if isinstance(target_or_error, str):
		return target_or_error
	root, target = target_or_error
	if not os.path.isfile(target):
		return f"FAILED: file not found: {os.path.relpath(target, root)}"
	if os.path.getsize(target) > _MAX_FILE_BYTES:
		return "FAILED: file is too large to read. Use search_backend to find the relevant part."
	lines = _read_lines(target)
	if lines is None:
		return "FAILED: this looks like a binary file."
	start = max(int(args.get("start_line") or 1), 1)
	window = lines[start - 1 : start - 1 + _MAX_READ_LINES]
	if not window:
		return f"FAILED: start_line {start} is past the end of the file ({len(lines)} lines)."
	numbered = "\n".join(f"{start + i}: {line[:_MAX_LINE_CHARS]}" for i, line in enumerate(window))
	suffix = ""
	if start - 1 + len(window) < len(lines):
		suffix = f"\n… file continues to line {len(lines)} — re-read with start_line={start + len(window)}."
	return f"{os.path.relpath(target, root)} (lines {start}-{start + len(window) - 1} of {len(lines)}):\n{numbered}{suffix}"


def run_search_backend(ctx, args: dict) -> str:
	if denied := _denied():
		return denied
	pattern = text_arg(args.get("pattern"))
	if not pattern:
		return "FAILED: pattern is required."
	try:
		regex = re.compile(pattern, re.IGNORECASE)
	except re.error as e:
		return f"FAILED: invalid regex: {e}"
	root_or_error = _resolve(args, allow_missing_path=True)
	if isinstance(root_or_error, str):
		return root_or_error
	root, start = root_or_error
	file_glob = text_arg(args.get("file_glob"))
	matches, scanned, truncated = _grep(root, start, regex, file_glob)
	if not matches:
		return f"No matches for /{pattern}/ (scanned {scanned} files). Loosen the pattern or drop file_glob."
	note = f"\n… stopped at {_MAX_MATCHES} matches — narrow the pattern or path." if truncated else ""
	return f"{len(matches)} match(es) for /{pattern}/ (path:line: text):\n" + "\n".join(matches) + note


# --- jail & filesystem helpers --------------------------------------------


def _denied() -> str | None:
	if "System Manager" not in frappe.get_roles():
		return "FAILED: backend read access requires the System Manager role."
	return None


def _resolve(args: dict, allow_missing_path: bool = False) -> tuple[str, str] | str:
	"""(app_repo_root, absolute_target) for the call's app + path, or a FAILED string.
	The target must stay inside the app's repo directory — traversal is refused."""
	app = text_arg(args.get("app"))
	if app not in frappe.get_installed_apps():
		return f"FAILED: '{app}' is not an installed app. Call list_backend_apps first."
	# get_app_path → apps/<app>/<app> (the python package); its parent is the repo root,
	# which also holds the frontend/, hooks and config the agent needs to see.
	root = os.path.dirname(os.path.normpath(frappe.get_app_path(app)))
	path = text_arg(args.get("path") or args.get("file_path"))
	if not path and not allow_missing_path:
		return "FAILED: file_path is required."
	target = os.path.normpath(os.path.join(root, path)) if path else root
	if os.path.commonpath([root, target]) != root:
		return "FAILED: path escapes the app directory."
	if _is_hidden(os.path.relpath(target, root)):
		return "FAILED: hidden files and dot-directories are not readable."
	return root, target


def _is_hidden(rel_path: str) -> bool:
	return any(part.startswith(".") and part != "." for part in rel_path.split(os.sep))


def _skip(name: str) -> bool:
	return name.startswith(".") or name in _SKIP_DIRS


def _walk_paths(root: str, start: str) -> list[str]:
	paths = []
	for dirpath, dirnames, filenames in os.walk(start):
		dirnames[:] = sorted(d for d in dirnames if not _skip(d))
		for name in sorted(filenames):
			if name.startswith(".") or name.endswith(".pyc"):
				continue
			paths.append(os.path.relpath(os.path.join(dirpath, name), root))
			if len(paths) >= _MAX_LIST_PATHS:
				return paths
	return paths


def _read_lines(target: str) -> list[str] | None:
	with open(target, "rb") as f:
		raw = f.read()
	if b"\x00" in raw[:8192]:
		return None
	return raw.decode("utf-8", errors="replace").splitlines()


def _grep(root: str, start: str, regex, file_glob: str) -> tuple[list[str], int, bool]:
	matches: list[str] = []
	scanned = 0
	for dirpath, dirnames, filenames in os.walk(start):
		dirnames[:] = sorted(d for d in dirnames if not _skip(d))
		for name in sorted(filenames):
			if name.startswith(".") or name.endswith(".pyc"):
				continue
			if file_glob and not fnmatch.fnmatch(name, file_glob):
				continue
			scanned += 1
			if scanned > _MAX_SCANNED_FILES:
				return matches, scanned, True
			full = os.path.join(dirpath, name)
			if os.path.getsize(full) > _MAX_FILE_BYTES:
				continue
			lines = _read_lines(full)
			if lines is None:
				continue
			rel = os.path.relpath(full, root)
			for lineno, line in enumerate(lines, 1):
				if regex.search(line):
					matches.append(f"{rel}:{lineno}: {line.strip()[:_MAX_LINE_CHARS]}")
					if len(matches) >= _MAX_MATCHES:
						return matches, scanned, True
	return matches, scanned, False


# --- tool definitions -----------------------------------------------------

_APP_PROP = {"type": "string", "description": "The installed app to read, e.g. 'frappe', 'erpnext'."}
_PATH_PROP = {
	"type": "string",
	"description": "Path relative to the app's repo root. Omit to start at the root.",
}

list_backend_apps = Tool(
	name="list_backend_apps",
	side="server",
	handler=run_list_backend_apps,
	description=(
		"List the Frappe apps installed on this site. Their backend source (DocType schemas, "
		"controllers, whitelisted APIs) is readable with list_backend_files / read_backend_file / "
		"search_backend."
	),
	parameters={"type": "object", "properties": {}},
)

list_backend_files = Tool(
	name="list_backend_files",
	side="server",
	handler=run_list_backend_files,
	description=(
		"List the files of an installed app's source tree (read-only). Use it to locate a DocType's "
		"folder (<app>/<module>/doctype/<doctype_name>/), controllers, or API modules before reading them."
	),
	parameters={
		"type": "object",
		"properties": {"app": _APP_PROP, "path": _PATH_PROP},
		"required": ["app"],
	},
)

read_backend_file = Tool(
	name="read_backend_file",
	side="server",
	handler=run_read_backend_file,
	description=(
		"Read a backend source file (read-only, numbered lines, capped window). Ground yourself in "
		"the REAL code before wiring data: a DocType's .json schema for exact fields, its .py "
		"controller for whitelisted methods, an app's api.py for `call()` endpoints. For long files "
		"pass start_line to continue."
	),
	parameters={
		"type": "object",
		"properties": {
			"app": _APP_PROP,
			"file_path": {"type": "string", "description": "File path relative to the app's repo root."},
			"start_line": {"type": "integer", "description": "1-based line to start from (default 1)."},
		},
		"required": ["app", "file_path"],
	},
)

search_backend = Tool(
	name="search_backend",
	side="server",
	handler=run_search_backend,
	description=(
		"Grep an installed app's source with a regex (case-insensitive, read-only), returning "
		"path:line: text matches. The fastest way to find where something lives — a whitelisted "
		"method (`def get_dashboard`), a hook, a DocType fieldname — before read_backend_file."
	),
	parameters={
		"type": "object",
		"properties": {
			"app": _APP_PROP,
			"pattern": {"type": "string", "description": "Regular expression to search for."},
			"path": {
				"type": "string",
				"description": "Limit the search to this subdirectory of the app. Omit for the whole app.",
			},
			"file_glob": {
				"type": "string",
				"description": "Filename glob filter, e.g. '*.py' or '*.json'. Omit for all text files.",
			},
		},
		"required": ["app", "pattern"],
	},
)

TOOLS = [list_backend_apps, list_backend_files, read_backend_file, search_backend]
