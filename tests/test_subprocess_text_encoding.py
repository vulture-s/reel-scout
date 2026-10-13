"""Gate: every text-mode subprocess call must name its ``encoding``.

``text=True`` (or ``universal_newlines=True``) on its own decodes with
``locale.getpreferredencoding()`` -- cp950 on a Traditional-Chinese Windows
console. ffmpeg / ffprobe / yt-dlp emit UTF-8, so a CJK title or path either
comes back as mojibake or raises ``UnicodeDecodeError`` inside the reader
thread. There were ~20 such call sites; fixing them without a gate would only
guarantee the next one. This test walks the AST of every ``.py`` file in the
repo (package, scripts, hooks *and* tests) and fails on any call to
``subprocess.run / check_output / Popen / call / check_call`` -- however it was
imported -- that turns on text mode without an ``encoding=`` keyword.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBPROCESS_FUNCS = {"run", "check_output", "Popen", "call", "check_call"}
TEXT_KWARGS = {"text", "universal_newlines"}
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "node_modules",
             "__pycache__", ".tox", ".eggs", "site"}


def _python_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if any(part in SKIP_DIRS or part.endswith(".egg-info")
               for part in rel.parts[:-1]):
            continue
        yield path


def _is_false_constant(node):
    return isinstance(node, ast.Constant) and node.value in (False, None, 0)


def find_violations(source, filename="<src>"):
    """Return ``[(lineno, call_text)]`` for text-mode calls lacking encoding."""
    tree = ast.parse(source, filename=filename)
    module_aliases = set()      # import subprocess [as sp]
    func_aliases = set()        # from subprocess import run [as r]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "subprocess":
                    module_aliases.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for a in node.names:
                if a.name in SUBPROCESS_FUNCS:
                    func_aliases.add(a.asname or a.name)

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        hit = (
            (isinstance(f, ast.Attribute) and f.attr in SUBPROCESS_FUNCS
             and isinstance(f.value, ast.Name) and f.value.id in module_aliases)
            or (isinstance(f, ast.Name) and f.id in func_aliases)
        )
        if not hit:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg is not None}
        text_on = any(name in kw and not _is_false_constant(kw[name])
                      for name in TEXT_KWARGS)
        if text_on and "encoding" not in kw:
            out.append((node.lineno, ast.get_source_segment(source, node)
                        or "<call>"))
    return out


def test_no_text_mode_subprocess_call_without_encoding():
    problems = []
    for path in _python_files():
        src = path.read_text(encoding="utf-8")
        for lineno, _ in find_violations(src, str(path)):
            problems.append("%s:%d" % (path.relative_to(REPO).as_posix(), lineno))
    assert not problems, (
        "text=True / universal_newlines=True without encoding= decodes with the "
        "console codepage (cp950 on zh-TW Windows). Add "
        "encoding=\"utf-8\", errors=\"replace\" (or explain why strict):\n  "
        + "\n  ".join(sorted(problems)))


# --- the gate's own negative tests: it must catch every import shape ---------

def test_gate_catches_module_attribute_form():
    src = "import subprocess\nsubprocess.run(['x'], capture_output=True, text=True)\n"
    assert [ln for ln, _ in find_violations(src)] == [2]


def test_gate_catches_module_alias_and_all_entry_points():
    src = ("import subprocess as sp\n"
           "sp.check_output(['x'], text=True)\n"
           "sp.Popen(['x'], universal_newlines=True)\n"
           "sp.call(['x'], text=True)\n"
           "sp.check_call(['x'], text=True)\n")
    assert [ln for ln, _ in find_violations(src)] == [2, 3, 4, 5]


def test_gate_catches_from_import_form():
    src = ("from subprocess import run, Popen as P\n"
           "run(['x'], text=True)\n"
           "P(['x'], universal_newlines=True)\n")
    assert [ln for ln, _ in find_violations(src)] == [2, 3]


def test_gate_treats_non_constant_text_flag_as_on():
    src = "import subprocess\nsubprocess.run(['x'], text=flag)\n"
    assert [ln for ln, _ in find_violations(src)] == [2]


def test_gate_passes_compliant_and_binary_calls():
    src = ("import subprocess\nfrom subprocess import run\n"
           "subprocess.run(['x'], text=True, encoding='utf-8', errors='replace')\n"
           "subprocess.run(['x'], capture_output=True)\n"
           "subprocess.run(['x'], text=False)\n"
           "run(['x'], universal_newlines=True, encoding='utf-8')\n"
           "other.run(['x'], text=True)\n")
    assert find_violations(src) == []


def test_gate_scans_the_files_it_claims_to():
    files = {p.relative_to(REPO).as_posix() for p in _python_files()}
    assert "reel_scout/ffprobe.py" in files
    assert "reel_scout/crawl/youtube.py" in files
    assert "tests/test_subprocess_text_encoding.py" in files
