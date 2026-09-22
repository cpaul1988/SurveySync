from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Reduced orchestration ceilings after the 9.3.0 domain extraction.
# Further features must extend domain modules, not regrow these entry points.
MONOLITH_LIMITS = {
    "surveysync/router.py": {"lines": 1207, "routes": 124},
    "fieldbook_sync/app.py": {"lines": 4410, "routes": 124},
    "surveysync/control.py": {"lines": 985, "routes": 0},
}

# No silent broad handlers remain. Existing explicit boundary handlers are
# capped while their exception contracts are narrowed incrementally.
SILENT_EXCEPTION_LIMITS = {
    "surveysync": 0,
    "fieldbook_sync": 0,
}
BROAD_EXCEPTION_LIMITS = {
    "surveysync": 127,
    "fieldbook_sync": 149,
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
]

ROUTE_METHODS = {"get", "post", "put", "delete", "patch"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def python_files_under(folder: str) -> list[Path]:
    return sorted((ROOT / folder).rglob("*.py"))


def parse(path: Path, errors: list[str]) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception as exc:
        fail(errors, f"Could not parse {path.relative_to(ROOT)}: {exc}")
        return None


def count_broad_handlers(folder: str, errors: list[str]) -> tuple[int, int, list[str]]:
    broad_count = 0
    count = 0
    locations: list[str] = []
    for path in python_files_under(folder):
        tree = parse(path, errors)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = isinstance(node.type, ast.Name) and node.type.id == "Exception"
            silent = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if broad:
                broad_count += 1
            if broad and silent:
                count += 1
                locations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return broad_count, count, locations


def route_key(decorator: ast.expr) -> tuple[str, str] | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = decorator.func.attr.lower()
    if method not in ROUTE_METHODS or not decorator.args:
        return None
    arg = decorator.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return method.upper(), arg.value
    return None


def check_monolith(path_text: str, limits: dict, errors: list[str]) -> None:
    path = ROOT / path_text
    text = path.read_text(encoding="utf-8")
    lines = len(text.splitlines())
    if lines > limits["lines"]:
        fail(errors, f"{path_text} grew to {lines} lines (temporary ceiling {limits['lines']}; extract another domain before adding code).")

    tree = parse(path, errors)
    if tree is None:
        return
    routes: list[tuple[str, str]] = []
    module_names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_names.append(node.name)
            for decorator in node.decorator_list:
                key = route_key(decorator)
                if key:
                    routes.append(key)
    if len(routes) > limits["routes"]:
        fail(errors, f"{path_text} grew to {len(routes)} route handlers (temporary ceiling {limits['routes']}).")
    duplicate_routes = [key for key, n in Counter(routes).items() if n > 1]
    if duplicate_routes:
        fail(errors, f"{path_text} contains duplicate route registrations: {duplicate_routes[:10]}")
    duplicate_names = [name for name, n in Counter(module_names).items() if n > 1]
    if duplicate_names:
        fail(errors, f"{path_text} contains duplicate module-level function names: {duplicate_names[:10]}")


def check_ast_safety(path: Path, errors: list[str]) -> None:
    tree = parse(path, errors)
    if tree is None:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif node.module:
                names = [node.module]
            if any(name == "pickle" or name.startswith("pickle.") for name in names):
                fail(errors, f"Forbidden pickle import in {path.relative_to(ROOT)}:{node.lineno}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                fail(errors, f"Forbidden {node.func.id}() call in {path.relative_to(ROOT)}:{node.lineno}")
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    fail(errors, f"Forbidden shell=True call in {path.relative_to(ROOT)}:{node.lineno}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]
            if any(isinstance(default, (ast.List, ast.Dict, ast.Set)) for default in defaults):
                fail(errors, f"Mutable default argument in {path.relative_to(ROOT)}:{node.lineno} ({node.name})")


def check_secret_literals(errors: list[str]) -> None:
    for folder in ("surveysync", "fieldbook_sync", "installer", "scripts"):
        root = ROOT / folder
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".json", ".ps1", ".go"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    fail(errors, f"Possible committed secret matching {pattern.pattern!r} in {path.relative_to(ROOT)}")


def main() -> None:
    errors: list[str] = []
    silent_summary: dict[str, int] = {}
    broad_summary: dict[str, int] = {}
    for folder, limit in SILENT_EXCEPTION_LIMITS.items():
        broad_count, count, locations = count_broad_handlers(folder, errors)
        silent_summary[folder] = count
        broad_summary[folder] = broad_count
        if count > limit:
            fail(errors, f"{folder} has {count} blind 'except Exception: pass' handlers (limit {limit}). New sites are not allowed. Examples: {locations[:8]}")
        if broad_count > BROAD_EXCEPTION_LIMITS[folder]:
            fail(errors, f"{folder} has {broad_count} broad Exception handlers (baseline ceiling {BROAD_EXCEPTION_LIMITS[folder]}). Add a specific exception or reduce the baseline instead of increasing it.")

    for path_text, limits in MONOLITH_LIMITS.items():
        check_monolith(path_text, limits, errors)

    for folder in ("surveysync", "fieldbook_sync"):
        for path in python_files_under(folder):
            check_ast_safety(path, errors)
    check_secret_literals(errors)

    if errors:
        print("SurveySync static quality gate FAILED:")
        for error in errors:
            print(f" - {error}")
        raise SystemExit(1)

    print(
        "SurveySync static quality gate passed "
        f"(blind broad handlers: surveysync={silent_summary['surveysync']}, "
        f"fieldbook_sync={silent_summary['fieldbook_sync']}; broad handlers: "
        f"surveysync={broad_summary['surveysync']}, fieldbook_sync={broad_summary['fieldbook_sync']}; "
        "remaining orchestration growth frozen after 9.3.0 domain extraction)."
    )


if __name__ == "__main__":
    main()
