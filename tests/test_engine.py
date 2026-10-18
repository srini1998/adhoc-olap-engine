import random

import pytest

from olap.codegen import generate
from olap.engine import evaluate_rows
from olap.expr import AggRef, PhiSyntaxError, evaluate, parse_expr, walk
from olap.spec import PhiValidationError, parse_phi

COLUMNS = {"cust": "text", "prod": "text", "month": "number", "year": "number", "state": "text", "quant": "number"}

ROWS = [
    {"cust": "a", "prod": "x", "month": 1, "year": 2019, "state": "NY", "quant": 10},
    {"cust": "a", "prod": "x", "month": 2, "year": 2019, "state": "NJ", "quant": 30},
    {"cust": "a", "prod": "y", "month": 2, "year": 2020, "state": "NY", "quant": None},
    {"cust": "b", "prod": "x", "month": 1, "year": 2020, "state": "NY", "quant": 5},
    {"cust": "b", "prod": "y", "month": 3, "year": 2020, "state": "CT", "quant": 7},
]


def phi(select, n, v, f, sigma, having=None, where=None):
    parts = [
        "SELECT ATTRIBUTE(S):", select,
        "NUMBER OF GROUPING VARIABLES(n):", str(n),
        "GROUPING ATTRIBUTES(V):", v,
        "F-VECT([F]):", f,
        "SELECT CONDITION-VECT([σ]):", *sigma,
    ]
    if having:
        parts += ["HAVING_CONDITION(G):", having]
    if where:
        parts += ["WHERE:", where]
    return parse_phi("\n".join(parts), COLUMNS)


def run(q, rows=ROWS):
    return evaluate_rows(q, lambda: iter(rows))


# ---------------------------------------------------------------- parsing


def test_precedence_and_three_valued_logic():
    assert evaluate(parse_expr("1 + 2 * 3 = 7 and not 2 > 3"), {}) is True
    # unknown AND false is false, unknown OR true is true, unknown alone stays unknown
    assert evaluate(parse_expr("x > 1 and 1 = 2"), {"x": None}) is False
    assert evaluate(parse_expr("x > 1 or 1 = 1"), {"x": None}) is True
    assert evaluate(parse_expr("x > 1"), {"x": None}) is None
    assert evaluate(parse_expr("x / 0 = 1"), {"x": 4}) is None


def test_string_literals_with_quotes_round_trip():
    node = parse_expr("1.state = 'O''Brien'")
    assert node.right.value == "O'Brien"


@pytest.mark.parametrize("bad", ["1.state = ", "quant >> 3", "(1 = 1", "1.state = 'NY' extra", "__import__('os')"])
def test_rejects_malformed_or_unsupported_expressions(bad):
    with pytest.raises(PhiSyntaxError):
        parse_expr(bad)


def test_validation_errors_name_the_problem():
    with pytest.raises(PhiValidationError, match="unknown column 'colour'"):
        phi("cust, 1_sum_quant", 1, "cust", "1_sum_quant", ["1.cust = cust and 1.colour = 'red'"])
    with pytest.raises(PhiValidationError, match="no condition"):
        phi("cust, 2_sum_quant", 2, "cust", "2_sum_quant", ["1.cust = cust"])
    with pytest.raises(PhiValidationError, match="not declared in F-VECT"):
        phi("cust, 1_sum_quant", 2, "cust", "1_sum_quant", ["1.cust = cust", "2.quant > 1_avg_quant"])
    with pytest.raises(PhiValidationError, match="circular"):
        phi("cust", 2, "cust", "1_sum_quant, 2_sum_quant",
            ["1.cust = cust and 1.quant > 2_sum_quant", "2.cust = cust and 2.quant > 1_sum_quant"])
    with pytest.raises(PhiValidationError, match="must be a grouping attribute"):
        phi("cust, 1_sum_quant", 1, "cust", "1_sum_quant", ["1.cust = cust and state = 'NY'"])
    with pytest.raises(PhiValidationError, match="numeric column"):
        phi("cust, 1_sum_state", 1, "cust", "1_sum_state", ["1.cust = cust"])


def test_dependency_levels_drive_scan_count():
    q = phi("cust, 2_count_quant", 2, "cust", "1_avg_quant, 2_count_quant",
            ["1.cust = cust", "2.cust = cust and 2.quant > 1_avg_quant"])
    assert q.levels == {1: 1, 2: 2}
    assert q.scans == 3


# ---------------------------------------------------------------- semantics


def test_nulls_are_ignored_by_aggregates_like_sql():
    q = phi("cust, 0_count_quant, 0_sum_quant, 0_avg_quant, 0_min_quant, 0_max_quant", 0, "cust",
            "0_count_quant, 0_sum_quant, 0_avg_quant, 0_min_quant, 0_max_quant", [])
    rows, _ = run(q)
    a = rows[0]
    assert (a["0_count_quant"], a["0_sum_quant"], a["0_avg_quant"]) == (2, 40, 20)
    assert (a["0_min_quant"], a["0_max_quant"]) == (10, 30)


def test_empty_grouping_variable_gives_null_sum_and_zero_count():
    q = phi("cust, 1_sum_quant, 1_count_quant", 1, "cust", "1_sum_quant, 1_count_quant",
            ["1.cust = cust and 1.state = 'CT'"])
    rows, _ = run(q)
    assert rows == [
        {"cust": "a", "1_sum_quant": None, "1_count_quant": 0},
        {"cust": "b", "1_sum_quant": 7, "1_count_quant": 1},
    ]


def test_shifted_equality_uses_index_and_full_probe_is_reported():
    q = phi("cust, month, 1_sum_quant", 1, "cust, month", "1_sum_quant", ["1.cust = cust and 1.month = month - 1"])
    rows, stats = run(q)
    assert stats.indexed_gvs == [1] and stats.full_probe_gvs == []
    assert {(r["cust"], r["month"]): r["1_sum_quant"] for r in rows}[("a", 2)] == 10

    q = phi("cust, 1_count_quant", 1, "cust", "1_count_quant", ["1.cust <> cust"])
    rows, stats = run(q)
    assert stats.full_probe_gvs == [1]
    assert rows == [{"cust": "a", "1_count_quant": 2}, {"cust": "b", "1_count_quant": 2}]


def test_where_filters_before_grouping():
    q = phi("cust, 0_count_quant", 0, "cust", "0_count_quant", [], where="year = 2020")
    rows, _ = run(q)
    assert rows == [{"cust": "a", "0_count_quant": 0}, {"cust": "b", "0_count_quant": 2}]


def test_generated_program_never_embeds_query_text_as_code():
    q = phi("cust, 1_count_quant", 1, "cust", "1_count_quant",
            ["1.cust = cust and 1.state = 'x\"); import os; os.system(\"echo pwned'"])
    import ast

    def shape(src):
        tree = ast.parse(src)
        imports = sorted(ast.dump(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        return imports, calls, consts

    benign = phi("cust, 1_count_quant", 1, "cust", "1_count_quant", ["1.cust = cust and 1.state = 'NY'"])
    imports, calls, consts = shape(generate(q))
    base_imports, base_calls, _ = shape(generate(benign))
    assert imports == base_imports and calls == base_calls and "system" not in calls
    assert 'x"); import os; os.system("echo pwned' in consts  # present only as a string value


# ---------------------------------------------------------------- differential test


def naive(q, rows):
    """Independent reference: no hash indexes, no pass planning, a full filter per
    (group, grouping variable). Dependencies are resolved by recursion."""
    rows = [r for r in rows if q.where is None or evaluate(q.where, r) is True]
    groups = []
    for r in rows:
        g = {a: r[a] for a in q.group_by}
        if g not in groups:
            groups.append(g)

    def agg_value(func, vals):
        vals = [v for v in vals if v is not None]
        if func == "count":
            return len(vals)
        if not vals:
            return None
        return {"sum": sum(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[func]

    def compute(g, gv):
        if gv == 0:
            members = [r for r in rows if all(r[a] == g[a] for a in q.group_by)]
        else:
            for x in walk(q.sigma[gv]):
                if isinstance(x, AggRef) and x.key not in g:
                    compute(g, x.gv)
            members = [r for r in rows if evaluate(q.sigma[gv], g, r, gv) is True]
        for a in q.aggregates_for(gv):
            g[a.key] = agg_value(a.func, [r[a.attr] for r in members])

    for g in groups:
        for gv in sorted({a.gv for a in q.aggregates}):
            if q.aggregates_for(gv)[0].key not in g:
                compute(g, gv)
    out = [{c: g[c] for c in q.select} for g in groups if q.having is None or evaluate(q.having, g) is True]
    return sorted(out, key=lambda r: tuple((r[a] is None, r[a]) for a in q.group_by if a in r))


def random_rows(rng, n):
    return [
        {
            "cust": rng.choice("abcd"),
            "prod": rng.choice("xyz"),
            "month": rng.randint(1, 4),
            "year": rng.choice([2019, 2020]),
            "state": rng.choice(["NY", "NJ", "CT"]),
            "quant": None if rng.random() < 0.1 else rng.randint(1, 50),
        }
        for _ in range(n)
    ]


def random_query(rng):
    v = rng.sample(["cust", "prod", "month"], rng.randint(1, 2))
    n = rng.randint(1, 3)
    aggs, sigma = ["0_avg_quant"], []
    for gv in range(1, n + 1):
        func = rng.choice(["count", "sum", "avg", "min", "max"])
        aggs.append(f"{gv}_{func}_quant")
        conj = []
        for a in v:
            r = rng.random()
            if r < 0.6:
                conj.append(f"{gv}.{a} = {a}")
            elif r < 0.8 and a == "month":
                conj.append(f"{gv}.month = month {rng.choice(['-', '+'])} 1")
            else:
                conj.append(f"{gv}.{a} <> {a}")
        conj.append(rng.choice([f"{gv}.state = 'NY'", f"{gv}.year = 2020", f"{gv}.quant > 20", f"{gv}.quant <= 35"]))
        if gv > 1 and rng.random() < 0.5:
            conj.append(f"{gv}.quant > 0_avg_quant")
        sigma.append(" and ".join(conj))
    having = rng.choice([None, "0_avg_quant > 20", f"{aggs[1]} >= 1 or not (0_avg_quant < 25)"])
    return phi(", ".join(v + aggs), n, ", ".join(v), ", ".join(aggs), sigma, having)


def test_engine_matches_naive_reference_on_random_queries():
    rng = random.Random(7)
    for _ in range(300):
        q = random_query(rng)
        rows = random_rows(rng, rng.randint(0, 60))
        got, _ = run(q, rows)
        assert got == naive(q, rows), q.source


def test_generated_program_matches_interpreter_on_random_queries():
    rng = random.Random(11)
    for _ in range(60):
        q = random_query(rng)
        rows = random_rows(rng, 40)
        ns: dict = {}
        exec(compile(generate(q), "<generated>", "exec"), ns)
        ns["_scan"] = lambda conn, cols, table: iter([{c: r[c] for c in cols} for r in rows])
        expected, _ = run(q, rows)
        assert ns["run"](None) == expected, q.source


def test_differential_check_catches_a_seeded_bug(monkeypatch):
    """Negative control: break the shifted-key index and the comparison must fail."""
    import olap.engine as eng

    original = eng.equality_keys
    monkeypatch.setattr(eng, "equality_keys", lambda cond, gv: [(n, parse_expr("month")) if n == "month" else (n, e)
                                                              for n, e in original(cond, gv)])
    q = phi("cust, month, 1_sum_quant", 1, "cust, month", "1_sum_quant", ["1.cust = cust and 1.month = month - 1"])
    got, _ = run(q)
    assert got != naive(q, ROWS)
