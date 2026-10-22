"""Drift guard for docs/c_python_function_map.md (C <-> Python function map).

The map lists every C function definition of the NR library next to the Python symbol it mirrors.
This file reads the map and checks, without importing any NR module:

  * every Python symbol named in the map still exists (parsed with ``ast``), and every ``#anchor``
    (an identifier that must still occur inside that symbol) is still there;
  * every top-level class/function under python/core and python/denoisers is listed in the map
    (as a mapped symbol or in the Python-only rows);
  * the C function definitions found by a small scanner in c_impl/src/*.c and c_impl/include/*.h
    are exactly the C functions listed in the map (nothing missing, nothing stale, no duplicates),
    and the "declared only" symbols really have no definition;
  * relation words, evidence tags, audit ids and tool paths in the table are well formed;
  * the coverage numbers quoted in section 5 of the map match the table;
  * when the Python<->C parity run keeps a registry of expected-red findings, each S-xx in it is
    findable in the map's gap column (skipped if the registry is absent).

Symbol grammar of the Python column:  ``relative/path.py:Symbol[#anchor]``  where Symbol is a
module-level def/class/assigned name or ``Class.member``; paths are relative to python/.
C column: ``path/relative/to/c_impl:function``; ``(twin: ...)`` lists kernel variants of the row.

Run from the NR root:
    PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider python/tests/test_c_python_map.py
"""
import ast
import json
import re
from pathlib import Path

import pytest

NR_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = NR_ROOT / "python"
C_ROOT = NR_ROOT / "c_impl"
MAP_PATH = NR_ROOT / "docs" / "c_python_function_map.md"

RELATIONS = ("mirror", "partial", "C-only", "Python-only", "未判斷")
EVIDENCE_TAGS = ("CHANGELOG", "README", "註解", "稽核", "測試", "讀碼")
TOOL_SUFFIXES = (".py", ".c", ".h", ".cpp", ".md", ".sh")

C_TOKEN = re.compile(r"`([\w./-]+):(\w+)`")
PY_TOKEN = re.compile(r"^([\w/]+\.py):([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?:#([A-Za-z_]\w*))?$")
ID_TOKEN = re.compile(r"\b([SDTG]-\d{2})\b")
BACKTICKED = re.compile(r"`([^`]+)`")
LEADING_TAGS = re.compile(r"^(?:\[[^\]]+\])+")


# --------------------------------------------------------------------------------------------
# C scanner: names of top-level function definitions (comments, strings, preprocessor lines and
# ``extern "C" {`` wrappers are ignored; a definition is ``name ( ... ) {`` at brace depth 0).
# --------------------------------------------------------------------------------------------
def _strip_c(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text[i] in "\"'":
            quote, j = text[i], i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(re.sub(r"[^\n]", " ", text[i:j]) if quote == '"' else "0" * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    lines, kept, continued = "".join(out).split("\n"), [], False
    for line in lines:
        if continued or line.lstrip().startswith("#"):
            continued = line.rstrip().endswith("\\")
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


def c_definitions(text):
    """Return the function names defined at file scope in C source ``text`` (in order)."""
    names = []
    depth = extern_open = paren_depth = 0
    prev_ident = paren_ident = pending = None
    for match in re.finditer(r"[A-Za-z_]\w*|\(|\)|\{|\}|;|=|[^\sA-Za-z_(){};=]", _strip_c(text)):
        tok = match.group()
        if depth > 0:
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1
                if depth == 0:
                    pending = prev_ident = None
            continue
        if re.match(r"[A-Za-z_]", tok):
            if paren_depth == 0:
                prev_ident = tok
        elif tok == "(":
            if paren_depth == 0:
                paren_ident = prev_ident
            paren_depth += 1
        elif tok == ")":
            paren_depth -= 1
            if paren_depth == 0:
                pending = paren_ident
        elif tok == "{":
            if pending and paren_depth == 0:
                names.append(pending)
                depth += 1
            elif prev_ident == "extern" and paren_depth == 0:
                extern_open += 1
            else:
                depth += 1
            pending = None
        elif tok == "}":
            if extern_open:
                extern_open -= 1
        elif tok in ";=":
            pending = None
    return names


def scan_c_tree():
    """{relative path under c_impl: set of defined function names} for src/*.c, src/*.h, include/*.h."""
    found = {}
    for sub, patterns in (("src", ("*.c", "*.h")), ("include", ("*.h",))):
        for pattern in patterns:
            for path in sorted((C_ROOT / sub).glob(pattern)):
                names = set(c_definitions(path.read_text(encoding="utf-8")))
                if names:
                    found["%s/%s" % (sub, path.name)] = names
    return found


# --------------------------------------------------------------------------------------------
# Python symbol resolution (ast only, nothing is imported)
# --------------------------------------------------------------------------------------------
_TREES = {}


def load_tree(rel_path):
    if rel_path not in _TREES:
        path = PY_ROOT / rel_path
        _TREES[rel_path] = ast.parse(path.read_text(encoding="utf-8")) if path.is_file() else None
    return _TREES[rel_path]


def _assigned_names(node):
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def find_symbol(tree, symbol):
    """AST node of ``name`` (module level) or ``Class.member`` (method or class attribute)."""
    if tree is None:
        return None
    parts = symbol.split(".")
    scope = tree.body
    if len(parts) == 2:
        owner = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == parts[0]), None)
        if owner is None:
            return None
        scope = owner.body
    for node in scope:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == parts[-1]:
            return node
        if parts[-1] in _assigned_names(node):
            return node
    return None


def identifiers_in(node):
    """Identifiers occurring in the subtree: names, attributes, args, keywords, string constants."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
        elif isinstance(sub, ast.arg):
            found.add(sub.arg)
        elif isinstance(sub, ast.keyword) and sub.arg:
            found.add(sub.arg)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(sub.name)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            found.add(sub.value)
    return found


# --------------------------------------------------------------------------------------------
# Map parsing
# --------------------------------------------------------------------------------------------
class Row:
    def __init__(self, line_no, cells):
        self.line_no = line_no
        c_cell, py_cell, rel_cell, gap_cell, tool_cell, note_cell = cells
        self.c_cell, self.py_cell, self.rel_cell = c_cell, py_cell, rel_cell
        self.gap_cell, self.tool_cell, self.note_cell = gap_cell, tool_cell, note_cell
        self.relation = re.split(r"[（\s]", rel_cell, maxsplit=1)[0]
        self.declared_only = "宣告無實作" in rel_cell
        head, _, tail = c_cell.partition("twin：")
        self.primary = C_TOKEN.findall(head)
        last_file = self.primary[-1][0] if self.primary else None
        self.twins = [(last_file, name) for name in re.findall(r"`(\w+)`", tail)]
        self.py_raw = [t for t in BACKTICKED.findall(py_cell)]
        self.py_tokens = [PY_TOKEN.match(t) for t in self.py_raw]


def _region(text, begin, end):
    start = text.index(begin) + len(begin)
    return text[start:text.index(end, start)], text[:start].count("\n") + 1


def _table_rows(region, first_line):
    rows = []
    for offset, line in enumerate(region.split("\n")):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r"-+", c) for c in cells) or cells[0].startswith("C 檔") or cells[0] == "編號":
            continue
        rows.append((first_line + offset, cells))
    return rows


@pytest.fixture(scope="module")
def map_text():
    assert MAP_PATH.is_file(), "missing %s" % MAP_PATH
    return MAP_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def table(map_text):
    region, first_line = _region(map_text, "<!-- MAP:BEGIN -->", "<!-- MAP:END -->")
    rows, errors = [], []
    for line_no, cells in _table_rows(region, first_line):
        if len(cells) != 6:
            errors.append("line %d: expected 6 cells, got %d" % (line_no, len(cells)))
            continue
        rows.append(Row(line_no, cells))
    assert not errors, "\n".join(errors)
    return rows


@pytest.fixture(scope="module")
def defined_ids(map_text):
    region, first_line = _region(map_text, "<!-- IDS:BEGIN -->", "<!-- IDS:END -->")
    ids = set()
    for _, cells in _table_rows(region, first_line):
        ids.update(ID_TOKEN.findall(cells[0]))
    return ids


def _mapped_rows(table):
    return [r for r in table if r.relation in ("mirror", "partial", "C-only") and not r.declared_only]


# --------------------------------------------------------------------------------------------
# Tests: Python side
# --------------------------------------------------------------------------------------------
def test_table_is_not_vacuous(table):
    # Guards against a format drift that would make every other check pass over zero rows.
    assert len(table) >= 60, "only %d table rows parsed" % len(table)
    assert sum(len(r.py_tokens) for r in table) >= 60
    # Lowered from 100 on 2026-10-21 (P3c-NR): 10 twin names legitimately left this
    # table when their kernel bodies moved out of c_impl/src into the shared
    # audiolib/common/utility/simd_nr.h (now documented in Audio_ALG's map instead,
    # AC-SIMD-08) -- not a format drift, see c_python_function_map.md's
    # gain_prepare/noise_estimator_min_ordered/_ring_min/_restart_inert rows.
    assert sum(len(r.primary) + len(r.twins) for r in table) >= 80


def test_python_symbols_in_map_exist(table):
    errors = []
    for row in table:
        for raw, match in zip(row.py_raw, row.py_tokens):
            if match is None:
                errors.append("line %d: malformed Python token `%s`" % (row.line_no, raw))
                continue
            rel_path, symbol, anchor = match.groups()
            tree = load_tree(rel_path)
            if tree is None:
                errors.append("line %d: file python/%s does not exist (`%s`)" % (row.line_no, rel_path, raw))
                continue
            node = find_symbol(tree, symbol)
            if node is None:
                errors.append("line %d: symbol %s not found in python/%s" % (row.line_no, symbol, rel_path))
            elif anchor and anchor not in identifiers_in(node):
                errors.append("line %d: anchor #%s not found inside %s (python/%s)"
                              % (row.line_no, anchor, symbol, rel_path))
    assert not errors, "\n".join(errors)


def _python_toplevel_symbols():
    symbols = {}
    for sub in ("core", "denoisers"):
        for path in sorted((PY_ROOT / sub).rglob("*.py")):
            if path.name == "__init__.py" or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(PY_ROOT).as_posix()
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols[(rel, node.name)] = node
    return symbols


def test_every_toplevel_python_symbol_is_listed(table):
    listed = set()
    for row in table:
        for match in row.py_tokens:
            if match:
                listed.add((match.group(1), match.group(2).split(".")[0]))
    missing = sorted("python/%s:%s" % key for key in _python_toplevel_symbols() if key not in listed)
    assert not missing, ("top-level symbols under core/ and denoisers/ missing from the map "
                         "(add a mapped row or a Python-only row):\n" + "\n".join(missing))


# --------------------------------------------------------------------------------------------
# Tests: C side
# --------------------------------------------------------------------------------------------
def test_c_functions_in_map_match_scanned_definitions(table):
    scanned = scan_c_tree()
    scanned_pairs = {(f, n) for f, names in scanned.items() for n in names}
    listed, errors = [], []
    for row in _mapped_rows(table):
        if not row.primary:
            errors.append("line %d: no C function in the first cell" % row.line_no)
        listed.extend(row.primary + row.twins)
    duplicates = sorted({"%s:%s" % p for p in listed if listed.count(p) > 1})
    errors += ["listed more than once: " + d for d in duplicates]
    listed_set = set(listed)
    errors += ["in the map but not defined in c_impl: %s:%s" % p for p in sorted(listed_set - scanned_pairs)]
    errors += ["defined in c_impl but missing from the map: %s:%s" % p for p in sorted(scanned_pairs - listed_set)]
    assert len(scanned_pairs) >= 80, "C scanner found only %d definitions" % len(scanned_pairs)
    assert not errors, "\n".join(errors)


def test_declared_only_symbols_have_no_definition(table):
    scanned = scan_c_tree()
    defined = {n for names in scanned.values() for n in names}
    errors, count = [], 0
    for row in table:
        if not row.declared_only:
            continue
        for rel_path, name in row.primary:
            count += 1
            header = C_ROOT / rel_path
            if not header.is_file() or not re.search(r"\b%s\s*\(" % re.escape(name), _strip_c(header.read_text(encoding="utf-8"))):
                errors.append("line %d: %s is not declared in c_impl/%s" % (row.line_no, name, rel_path))
            if name in defined:
                errors.append("line %d: %s now has a definition; move it to a normal row" % (row.line_no, name))
    assert not errors, "\n".join(errors)


# --------------------------------------------------------------------------------------------
# Tests: table shape
# --------------------------------------------------------------------------------------------
def test_rows_are_well_formed(table, defined_ids):
    errors = []
    for row in table:
        at = "line %d" % row.line_no
        if row.relation not in RELATIONS:
            errors.append("%s: unknown relation %r" % (at, row.rel_cell))
            continue
        n_py = len(row.py_tokens)
        if row.relation == "Python-only":
            if row.c_cell.strip() != "—" or n_py == 0:
                errors.append("%s: Python-only row needs C cell '—' and at least one Python token" % at)
        else:
            if not row.primary:
                errors.append("%s: no C function token" % at)
            if row.relation in ("mirror", "partial") and n_py == 0:
                errors.append("%s: %s row without a Python token" % (at, row.relation))
            if row.relation == "C-only" and n_py != 0:
                errors.append("%s: C-only row must not name a Python symbol" % at)
        if row.relation == "未判斷":
            errors.append("%s: undetermined row; list it explicitly in section 5 and fix the count" % at)
        if not LEADING_TAGS.match(row.note_cell):
            errors.append("%s: last cell must start with evidence tags like [讀碼]" % at)
        else:
            for tag in re.findall(r"\[([^\]]+)\]", LEADING_TAGS.match(row.note_cell).group()):
                if tag not in EVIDENCE_TAGS:
                    errors.append("%s: unknown evidence tag [%s]" % (at, tag))
        if row.gap_cell.strip() != "—" and not ID_TOKEN.search(row.gap_cell):
            errors.append("%s: gap cell must be '—' or audit ids" % at)
        for used in ID_TOKEN.findall(" ".join((row.gap_cell, row.note_cell))):
            if used not in defined_ids:
                errors.append("%s: audit id %s is not defined in appendix A" % (at, used))
        for token in BACKTICKED.findall(row.tool_cell):
            if "/" in token and token.endswith(TOOL_SUFFIXES) and not (NR_ROOT / token).is_file():
                errors.append("%s: tool path does not exist: %s" % (at, token))
    assert not errors, "\n".join(errors)


# --------------------------------------------------------------------------------------------
# Tests: coverage numbers quoted in the map
# --------------------------------------------------------------------------------------------
def _computed_numbers(table):
    n = dict(mirror=0, partial=0, c_only_plain=0, twin=0, undetermined=0, declared=0,
             pyonly_rows=0, pyonly_syms=0, rows=len(table), read_only=0)
    for row in table:
        if row.relation == "Python-only":
            n["pyonly_rows"] += 1
            n["pyonly_syms"] += len(row.py_tokens)
        elif row.declared_only:
            n["declared"] += len(row.primary)
        elif row.relation == "mirror":
            n["mirror"] += len(row.primary)
        elif row.relation == "partial":
            n["partial"] += len(row.primary)
        elif row.relation == "C-only":
            n["c_only_plain"] += len(row.primary)
        elif row.relation == "未判斷":
            n["undetermined"] += len(row.primary)
        n["twin"] += len(row.twins) if not row.declared_only else 0
        if LEADING_TAGS.match(row.note_cell) and LEADING_TAGS.match(row.note_cell).group() == "[讀碼]":
            n["read_only"] += 1
    n["c_only"] = n["c_only_plain"] + n["twin"]
    n["total"] = n["mirror"] + n["partial"] + n["c_only"] + n["undetermined"]
    return n


def test_coverage_numbers_in_section5_match_the_table(map_text, table):
    n = _computed_numbers(table)
    expected = ("**涵蓋率**：C 函式定義 %(total)d；mirror %(mirror)d；partial %(partial)d；"
                "C-only %(c_only)d（其中 SIMD twin／dispatcher %(twin)d）；未能判斷 %(undetermined)d；"
                "另有宣告無實作 %(declared)d；Python-only %(pyonly_syms)d 個符號（%(pyonly_rows)d 列）") % n
    assert expected in map_text, "section 5 coverage line is stale; it should read:\n" + expected
    mapped_line = ("「已對應」= mirror + partial = %d；C-only 中 %d 個是 twin"
                   % (n["mirror"] + n["partial"], n["twin"]))
    assert mapped_line in map_text, "section 5 'mapped' line is stale; it should contain:\n" + mapped_line
    read_line = "`[讀碼]` 標籤的 %d 列（全表 %d 列）" % (n["read_only"], n["rows"])
    assert read_line in map_text, "section 5 read-only line is stale; it should contain:\n" + read_line
    assert n["undetermined"] == 0 and "**未能判斷：0**" in map_text


def test_per_file_counts_in_section5_match_the_scanner(map_text):
    scanned = scan_c_tree()
    counts = {
        "anr.c": len(scanned.get("src/anr.c", ())),
        "noise_estimator.c": len(scanned.get("src/noise_estimator.c", ())),
        "spp_estimator.c": len(scanned.get("src/spp_estimator.c", ())),
        "anr_types.h": len(scanned.get("include/anr_types.h", ())),
    }
    other = sorted(set(scanned) - {"src/anr.c", "src/noise_estimator.c", "src/spp_estimator.c",
                                   "include/anr_types.h"})
    assert not other, "definitions found in files the section 5 breakdown does not name: %s" % other
    expected = "分項：`anr.c` %d、`noise_estimator.c` %d、`spp_estimator.c` %d、`anr_types.h` %d，合計 %d" % (
        counts["anr.c"], counts["noise_estimator.c"], counts["spp_estimator.c"], counts["anr_types.h"],
        sum(counts.values()))
    assert expected in map_text, "per-file breakdown is stale; it should read:\n" + expected


def test_expected_red_ids_of_the_parity_registry_are_locatable(table):
    """Every S-xx the Python<->C parity run registers as expected-red must appear in the gap column.

    The registry belongs to the parity tooling (c_impl/test/pyc_parity/expected_red.json). When it is
    absent or not in the expected shape this check is skipped, never failed.
    """
    registry = C_ROOT / "test" / "pyc_parity" / "expected_red.json"
    if not registry.is_file():
        pytest.skip("no parity registry at c_impl/test/pyc_parity/expected_red.json")
    try:
        keys = list(json.loads(registry.read_text(encoding="utf-8"))["expected_red"])
    except (ValueError, KeyError, TypeError):
        pytest.skip("parity registry has an unexpected shape")
    registered = set(ID_TOKEN.findall(" ".join(str(k) for k in keys)))
    in_table = set(ID_TOKEN.findall(" ".join(row.gap_cell for row in table)))
    missing = sorted(registered - in_table)
    assert not missing, "expected-red ids not present in any gap cell of the map: %s" % missing


# --------------------------------------------------------------------------------------------
# Self-checks: the two helpers above must be able to say "no".
# --------------------------------------------------------------------------------------------
def test_symbol_resolver_rejects_missing_names():
    tree = ast.parse(
        "X = 1\n"
        "def f(a):\n    return a.attr + g(key=1)\n"
        "class C:\n    K = 2\n    def m(self):\n        return self.state\n"
    )
    assert find_symbol(tree, "f") is not None
    assert find_symbol(tree, "X") is not None
    assert find_symbol(tree, "C") is not None
    assert find_symbol(tree, "C.m") is not None
    assert find_symbol(tree, "C.K") is not None
    for missing in ("g", "C.n", "D.m", "f.a", "Y"):
        assert find_symbol(tree, missing) is None, missing
    assert {"a", "attr", "g", "key"} <= identifiers_in(find_symbol(tree, "f"))
    assert "state" in identifiers_in(find_symbol(tree, "C.m"))
    assert "state" not in identifiers_in(find_symbol(tree, "f"))
    assert find_symbol(None, "f") is None


def test_c_scanner_handles_wrappers_twins_and_non_functions():
    source = r'''
    #include <x.h>
    #define MACRO(a) { a; }
    /* static void in_comment(void) { } */
    #ifdef __cplusplus
    extern "C" {
    #endif
    typedef struct { int a; } S;
    static const int table[3] = {1, 2, 3};
    static inline int one(int x) { return x ? 1 : 0; }
    ANR_TWIN void twin_scalar(const float* p,
                              float* q) { if (p) { *q = 1.0f; } }
    #ifdef A
    void dup(void) { }
    #else
    void dup(void) { }
    #endif
    int declared_only(int x);
    const char *msg = "not_a_fn(void) { }";
    #ifdef __cplusplus
    }
    #endif
    '''
    assert c_definitions(source) == ["one", "twin_scalar", "dup", "dup"]
    assert c_definitions("int x;\nstruct T { int a; };\n") == []
