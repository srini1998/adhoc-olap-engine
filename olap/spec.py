"""Phi-operator query specification: parsing, validation and pass planning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .expr import (
    AGG_FUNCS,
    AggRef,
    Binary,
    GroupAttr,
    Node,
    PhiSyntaxError,
    RowAttr,
    parse_expr,
    walk,
)

_SECTIONS = [
    ("table", r"TABLE"),
    ("select", r"SELECT\s+ATTRIBUTE"),
    ("n", r"NUMBER\s+OF\s+GROUPING\s+VARIABLES"),
    ("group_by", r"GROUPING\s+ATTRIBUTES"),
    ("fvect", r"F-VECT"),
    ("sigma", r"SELECT\s+CONDITION-VECT"),
    ("having", r"HAVING[_\s]CONDITION"),
    ("where", r"WHERE"),
]
_HEADER = re.compile(
    r"^\s*(?:" + "|".join(f"(?P<{k}>{p})" for k, p in _SECTIONS) + r")\b[^:]*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


class PhiValidationError(ValueError):
    pass


@dataclass
class PhiQuery:
    select: list[str]
    n: int
    group_by: list[str]
    aggregates: list[AggRef]
    sigma: dict[int, Node]
    having: Node | None = None
    where: Node | None = None
    table: str = "sales"
    source: str = ""
    levels: dict[int, int] = field(default_factory=dict)

    @property
    def scans(self) -> int:
        """Base-table scans: one to build groups plus one per dependency level."""
        return 1 + (max(self.levels.values()) if self.levels else 0)

    def aggregates_for(self, gv: int) -> list[AggRef]:
        return [a for a in self.aggregates if a.gv == gv]

    def gvs_at_level(self, level: int) -> list[int]:
        return sorted(gv for gv, lv in self.levels.items() if lv == level)


def _split_list(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def parse_phi(text: str, columns: dict[str, str] | None = None) -> PhiQuery:
    """Parse the classic six-part Phi operator file and validate it.

    ``columns`` maps column name -> 'number' | 'text'. When supplied, every
    attribute reference is checked against the table schema before evaluation.
    """
    raw: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        m = _HEADER.match(stripped)
        if m:
            current = next(k for k, _ in _SECTIONS if m.group(k))
            raw.setdefault(current, [])
            if m.group("rest").strip():
                raw[current].append(m.group("rest").strip())
            continue
        if current is None:
            raise PhiSyntaxError(f"content before any section header: {stripped!r}")
        raw[current].append(stripped.strip())

    for required in ("select", "n", "group_by", "fvect", "sigma"):
        if required not in raw:
            raise PhiSyntaxError(f"missing section: {required}")

    try:
        n = int(" ".join(raw["n"]))
    except ValueError as exc:
        raise PhiSyntaxError(f"number of grouping variables must be an integer: {raw['n']}") from exc

    aggregates: list[AggRef] = []
    for item in _split_list(" ".join(raw["fvect"])):
        node = parse_expr(item)
        if not isinstance(node, AggRef):
            raise PhiSyntaxError(f"F-VECT entry is not an aggregate like 1_sum_quant: {item!r}")
        if node not in aggregates:
            aggregates.append(node)

    sigma: dict[int, Node] = {}
    for line in raw["sigma"]:
        node = parse_expr(line)
        gvs = {x.gv for x in walk(node) if isinstance(x, RowAttr)}
        if len(gvs) != 1:
            raise PhiValidationError(f"each condition must range over exactly one grouping variable: {line!r}")
        gv = gvs.pop()
        sigma[gv] = Binary("and", sigma[gv], node) if gv in sigma else node

    query = PhiQuery(
        select=[s.lower() for s in _split_list(" ".join(raw["select"]))],
        n=n,
        group_by=[g.lower() for g in _split_list(" ".join(raw["group_by"]))],
        aggregates=aggregates,
        sigma=sigma,
        having=parse_expr(" ".join(raw["having"])) if raw.get("having") else None,
        where=parse_expr(" ".join(raw["where"])) if raw.get("where") else None,
        table=" ".join(raw.get("table", ["sales"])).strip().lower(),
        source=text,
    )
    validate(query, columns)
    query.levels = plan_levels(query)
    return query


def validate(q: PhiQuery, columns: dict[str, str] | None) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", q.table):
        raise PhiValidationError(f"invalid table name: {q.table!r}")
    if q.n < 0:
        raise PhiValidationError("n must be >= 0")
    if not q.group_by:
        raise PhiValidationError("at least one grouping attribute is required")
    cols = set(columns) if columns is not None else None

    def check_col(name: str, where: str) -> None:
        if cols is not None and name not in cols:
            raise PhiValidationError(f"unknown column {name!r} in {where}")

    for g in q.group_by:
        check_col(g, "grouping attributes")
    agg_keys = {a.key for a in q.aggregates}
    for a in q.aggregates:
        if a.func not in AGG_FUNCS:
            raise PhiValidationError(f"unsupported aggregate {a.func!r}")
        if not 0 <= a.gv <= q.n:
            raise PhiValidationError(f"{a.key}: grouping variable {a.gv} is outside 0..{q.n}")
        check_col(a.attr, "F-VECT")
        if columns is not None and a.func in ("sum", "avg") and columns[a.attr] != "number":
            raise PhiValidationError(f"{a.key}: {a.func} needs a numeric column")

    for gv in range(1, q.n + 1):
        if gv not in q.sigma:
            raise PhiValidationError(f"grouping variable {gv} has no condition in SELECT CONDITION-VECT")
    for gv in q.sigma:
        if not 1 <= gv <= q.n:
            raise PhiValidationError(f"condition references grouping variable {gv} outside 1..{q.n}")

    for gv, node in q.sigma.items():
        for x in walk(node):
            if isinstance(x, RowAttr):
                check_col(x.name, f"condition {gv}")
            elif isinstance(x, GroupAttr) and x.name not in q.group_by:
                raise PhiValidationError(
                    f"condition {gv}: bare name {x.name!r} must be a grouping attribute (use {gv}.{x.name} for the row)"
                )
            elif isinstance(x, AggRef):
                if x.gv == gv:
                    raise PhiValidationError(f"condition {gv} cannot depend on its own aggregate {x.key}")
                if x.key not in agg_keys:
                    raise PhiValidationError(f"condition {gv} uses {x.key}, which is not declared in F-VECT")

    for item in q.select:
        if item in q.group_by or item in agg_keys:
            continue
        raise PhiValidationError(f"select item {item!r} is neither a grouping attribute nor a declared aggregate")

    if q.having is not None:
        for x in walk(q.having):
            if isinstance(x, RowAttr):
                raise PhiValidationError("HAVING cannot reference row attributes like 1.quant")
            if isinstance(x, GroupAttr) and x.name not in q.group_by:
                raise PhiValidationError(f"HAVING name {x.name!r} is not a grouping attribute")
            if isinstance(x, AggRef) and x.key not in agg_keys:
                raise PhiValidationError(f"HAVING uses undeclared aggregate {x.key}")

    if q.where is not None:
        for x in walk(q.where):
            if isinstance(x, (RowAttr, AggRef)):
                raise PhiValidationError("WHERE may only use plain column names and literals")
            if isinstance(x, GroupAttr):
                check_col(x.name, "WHERE")


def plan_levels(q: PhiQuery) -> dict[int, int]:
    """Assign each grouping variable (and the implicit whole-group variable 0) to a scan level.

    A variable whose condition reads another variable's aggregate must be computed
    in a later scan. Cycles are rejected because no scan order could satisfy them.
    """
    deps: dict[int, set[int]] = {0: set()}
    for gv in range(1, q.n + 1):
        deps[gv] = {x.gv for x in walk(q.sigma[gv]) if isinstance(x, AggRef)}
    levels: dict[int, int] = {}
    visiting: set[int] = set()

    def level(gv: int) -> int:
        if gv in levels:
            return levels[gv]
        if gv in visiting:
            raise PhiValidationError(f"circular dependency between grouping variable conditions involving {gv}")
        visiting.add(gv)
        lv = 1 + max((level(d) for d in deps[gv]), default=0)
        visiting.discard(gv)
        levels[gv] = lv
        return lv

    for gv in deps:
        level(gv)
    if not q.aggregates_for(0):
        levels.pop(0)
    return levels
