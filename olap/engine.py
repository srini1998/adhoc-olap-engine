"""Interpreter for Phi queries: multi-pass scans over an in-memory mf-structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from .expr import AggRef, Binary, GroupAttr, Node, Num, RowAttr, Str, evaluate as eval_expr, walk
from .spec import PhiQuery

RowSource = Callable[[], Iterable[dict]]


@dataclass
class RunStats:
    scans: int = 0
    rows_read: int = 0
    groups: int = 0
    indexed_gvs: list[int] = field(default_factory=list)
    full_probe_gvs: list[int] = field(default_factory=list)


class _Acc:
    """Running aggregate state for one (group, grouping-variable) pair."""

    __slots__ = ("count", "sums", "mins", "maxs", "counts")

    def __init__(self) -> None:
        self.count = 0
        self.sums: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self.mins: dict[str, object] = {}
        self.maxs: dict[str, object] = {}

    def add(self, row: dict, attrs: Iterable[str]) -> None:
        self.count += 1
        for a in attrs:
            v = row[a]
            if v is None:
                continue  # SQL aggregates ignore NULLs
            self.counts[a] = self.counts.get(a, 0) + 1
            if isinstance(v, (int, float)):
                self.sums[a] = self.sums.get(a, 0) + v
            if a not in self.mins or v < self.mins[a]:
                self.mins[a] = v
            if a not in self.maxs or v > self.maxs[a]:
                self.maxs[a] = v

    def value(self, agg: AggRef):
        a = agg.attr
        n = self.counts.get(a, 0)
        if agg.func == "count":
            return n
        if n == 0:
            return None
        if agg.func == "sum":
            return self.sums[a]
        if agg.func == "avg":
            return self.sums[a] / n
        if agg.func == "min":
            return self.mins[a]
        return self.maxs[a]


def _conjuncts(node: Node) -> Iterator[Node]:
    if isinstance(node, Binary) and node.op == "and":
        yield from _conjuncts(node.left)
        yield from _conjuncts(node.right)
    else:
        yield node


def _group_side(node: Node) -> bool:
    """True when an expression only depends on the mf-structure entry (not on the row)."""
    return not any(isinstance(x, RowAttr) for x in walk(node))


def equality_keys(cond: Node, gv: int) -> list[tuple[str, Node]]:
    """Find top-level conjuncts ``gv.attr = <group expression>`` usable as a hash index.

    For MF queries these are the usual ``1.cust = cust`` joins; for EMF queries they
    can be shifted, e.g. ``1.month = month - 1``.
    """
    keys: list[tuple[str, Node]] = []
    for c in _conjuncts(cond):
        if not (isinstance(c, Binary) and c.op == "="):
            continue
        for row_side, grp_side in ((c.left, c.right), (c.right, c.left)):
            if isinstance(row_side, RowAttr) and row_side.gv == gv and _group_side(grp_side):
                keys.append((row_side.name, grp_side))
                break
    return keys


def _key(value):
    # Normalize ints/floats so 3 and 3.0 hash to the same bucket, as SQL '=' would match them.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def evaluate_rows(query: PhiQuery, source: RowSource) -> tuple[list[dict], RunStats]:
    stats = RunStats()
    v = query.group_by

    def scan() -> Iterator[dict]:
        stats.scans += 1
        for row in source():
            stats.rows_read += 1
            if query.where is not None and eval_expr(query.where, row) is not True:
                continue
            yield row

    # Scan 0: discover every distinct grouping-attribute combination.
    groups: dict[tuple, dict] = {}
    for row in scan():
        k = tuple(row[a] for a in v)
        if k not in groups:
            groups[k] = {a: row[a] for a in v}
    stats.groups = len(groups)
    entries = list(groups.values())

    for level in range(1, (max(query.levels.values()) if query.levels else 0) + 1):
        gvs = query.gvs_at_level(level)
        accs: dict[int, list[_Acc]] = {gv: [_Acc() for _ in entries] for gv in gvs}
        attrs = {gv: sorted({a.attr for a in query.aggregates_for(gv)}) for gv in gvs}
        conds: dict[int, Node] = {}
        indexes: dict[int, tuple[list[str], dict[tuple, list[int]]]] = {}
        for gv in gvs:
            if gv == 0:
                # Whole-group aggregates: the row belongs to the entry with the same V values.
                conds[0] = None
                idx: dict[tuple, list[int]] = {}
                for i, e in enumerate(entries):
                    idx.setdefault(tuple(_key(e[a]) for a in v), []).append(i)
                indexes[0] = (list(v), idx)
                continue
            cond = query.sigma[gv]
            conds[gv] = cond
            keys = equality_keys(cond, gv)
            if keys:
                idx = {}
                for i, e in enumerate(entries):
                    vals = tuple(_key(eval_expr(expr, e)) for _, expr in keys)
                    if any(x is None for x in vals):
                        continue  # NULL never equals anything
                    idx.setdefault(vals, []).append(i)
                indexes[gv] = ([name for name, _ in keys], idx)
                stats.indexed_gvs.append(gv)
            else:
                stats.full_probe_gvs.append(gv)

        everyone = range(len(entries))
        for row in scan():
            for gv in gvs:
                if gv in indexes:
                    names, idx = indexes[gv]
                    candidates = idx.get(tuple(_key(row[n]) for n in names), ())
                else:
                    candidates = everyone
                cond = conds[gv]
                for i in candidates:
                    if cond is None or eval_expr(cond, entries[i], row, gv) is True:
                        accs[gv][i].add(row, attrs[gv])

        for gv in gvs:
            for i, e in enumerate(entries):
                for agg in query.aggregates_for(gv):
                    e[agg.key] = accs[gv][i].value(agg)

    out = []
    for e in entries:
        if query.having is not None and eval_expr(query.having, e) is not True:
            continue
        out.append({col: e[col] for col in query.select})
    out.sort(key=lambda r: tuple((r[a] is None, r[a]) for a in v if a in r))
    return out, stats


def table_columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = current_schema() and table_name = %s order by ordinal_position",
        (table,),
    ).fetchall()
    numeric = {"integer", "bigint", "smallint", "numeric", "real", "double precision"}
    return {name: ("number" if dtype in numeric else "text") for name, dtype in rows}


def postgres_source(conn, query: PhiQuery, batch: int = 5000) -> RowSource:
    """Stream the base table through a server-side cursor; no GROUP BY is sent to Postgres."""
    from psycopg import sql
    from psycopg.rows import dict_row

    needed = set(query.group_by) | {a.attr for a in query.aggregates}
    for node in list(query.sigma.values()) + [query.where]:
        if node is not None:
            needed |= {x.name for x in walk(node) if isinstance(x, (RowAttr, GroupAttr))}
    cols = sorted(needed)

    def scan() -> Iterator[dict]:
        stmt = sql.SQL("select {} from {}").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in cols), sql.Identifier(query.table)
        )
        with conn.cursor(name=f"olap_scan", row_factory=dict_row) as cur:
            cur.itersize = batch
            cur.execute(stmt)
            for row in cur:
                yield {k: (float(x) if type(x).__name__ == "Decimal" else x) for k, x in row.items()}

    return scan


def evaluate(query: PhiQuery, conn) -> tuple[list[dict], RunStats]:
    with conn.transaction():
        return evaluate_rows(query, postgres_source(conn, query))


__all__ = ["evaluate", "evaluate_rows", "postgres_source", "table_columns", "RunStats", "Num", "Str", "GroupAttr"]
