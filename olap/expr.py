"""Tokenizer, recursive-descent parser and evaluator for Phi-operator predicates.

Predicates are never passed to eval(). They are parsed into a small closed set of
node types, validated against the table schema and the declared aggregates, and
then either interpreted directly or rendered into Python source by codegen.

Grammar (lowest to highest precedence):
    expr    := or
    or      := and ('or' and)*
    and     := not ('and' not)*
    not     := 'not' not | cmp
    cmp     := sum (('='|'<>'|'!='|'<'|'<='|'>'|'>=') sum)?
    sum     := term (('+'|'-') term)*
    term    := unary (('*'|'/') unary)*
    unary   := '-' unary | atom
    atom    := NUMBER | STRING | GVATTR | AGG | NAME | '(' expr ')'

    GVATTR  := <int> '.' <name>          e.g. 1.state  (attribute of the scanned row)
    AGG     := <int|0> '_' <func> '_' <name>   e.g. 1_sum_quant
    NAME    := <name>                     a grouping attribute of the current group
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

AGG_FUNCS = ("count", "sum", "avg", "min", "max")


class PhiSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Num:
    value: float | int


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class GroupAttr:
    """A grouping attribute of the mf-structure row (bare name, e.g. ``cust``)."""

    name: str


@dataclass(frozen=True)
class RowAttr:
    """An attribute of the base-table row currently scanned for grouping variable ``gv``."""

    gv: int
    name: str


@dataclass(frozen=True)
class AggRef:
    """An aggregate of grouping variable ``gv`` (0 means the whole group)."""

    gv: int
    func: str
    attr: str

    @property
    def key(self) -> str:
        return f"{self.gv}_{self.func}_{self.attr}"


@dataclass(frozen=True)
class Unary:
    op: str  # 'neg' | 'not'
    operand: "Node"


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"


Node = Union[Num, Str, GroupAttr, RowAttr, AggRef, Unary, Binary]

_TOKEN = re.compile(
    r"""\s*(?:
      (?P<agg>\d+_(?:count|sum|avg|min|max)_[A-Za-z_][A-Za-z0-9_]*)
    | (?P<gvattr>\d+\.[A-Za-z_][A-Za-z0-9_]*)
    | (?P<num>\d+\.\d+|\d+)
    | (?P<str>'(?:[^']|'')*')
    | (?P<op><=|>=|<>|!=|=|<|>|\+|-|\*|/|\(|\))
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)

_CMP = {"=", "<>", "!=", "<", "<=", ">", ">="}


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise PhiSyntaxError(f"unexpected character at {pos}: {text[pos:pos + 12]!r}")
        kind = m.lastgroup
        value = m.group(kind)
        if kind == "name" and value.lower() in ("and", "or", "not"):
            kind, value = "kw", value.lower()
        tokens.append((kind, value))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.i = 0
        self.text = text

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise PhiSyntaxError(f"unexpected end of expression: {self.text!r}")
        self.i += 1
        return tok

    def accept(self, kind: str, value: str | None = None) -> bool:
        tok = self.peek()
        if tok and tok[0] == kind and (value is None or tok[1] == value):
            self.i += 1
            return True
        return False

    def parse(self) -> Node:
        node = self.or_()
        if self.peek() is not None:
            raise PhiSyntaxError(f"trailing tokens in {self.text!r}: {self.tokens[self.i:]}")
        return node

    def or_(self) -> Node:
        node = self.and_()
        while self.accept("kw", "or"):
            node = Binary("or", node, self.and_())
        return node

    def and_(self) -> Node:
        node = self.not_()
        while self.accept("kw", "and"):
            node = Binary("and", node, self.not_())
        return node

    def not_(self) -> Node:
        if self.accept("kw", "not"):
            return Unary("not", self.not_())
        return self.cmp()

    def cmp(self) -> Node:
        node = self.sum_()
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in _CMP:
            self.i += 1
            op = "<>" if tok[1] == "!=" else tok[1]
            node = Binary(op, node, self.sum_())
        return node

    def sum_(self) -> Node:
        node = self.term()
        while True:
            tok = self.peek()
            if tok and tok[0] == "op" and tok[1] in "+-":
                self.i += 1
                node = Binary(tok[1], node, self.term())
            else:
                return node

    def term(self) -> Node:
        node = self.unary()
        while True:
            tok = self.peek()
            if tok and tok[0] == "op" and tok[1] in "*/":
                self.i += 1
                node = Binary(tok[1], node, self.unary())
            else:
                return node

    def unary(self) -> Node:
        if self.accept("op", "-"):
            return Unary("neg", self.unary())
        return self.atom()

    def atom(self) -> Node:
        kind, value = self.take()
        if kind == "num":
            return Num(float(value) if "." in value else int(value))
        if kind == "str":
            return Str(value[1:-1].replace("''", "'"))
        if kind == "gvattr":
            gv, name = value.split(".", 1)
            return RowAttr(int(gv), name.lower())
        if kind == "agg":
            gv, func, attr = value.split("_", 2)
            return AggRef(int(gv), func, attr.lower())
        if kind == "name":
            return GroupAttr(value.lower())
        if kind == "op" and value == "(":
            node = self.or_()
            if not self.accept("op", ")"):
                raise PhiSyntaxError(f"missing ')' in {self.text!r}")
            return node
        raise PhiSyntaxError(f"unexpected token {value!r} in {self.text!r}")


def parse_expr(text: str) -> Node:
    return _Parser(text).parse()


def walk(node: Node):
    yield node
    if isinstance(node, Unary):
        yield from walk(node.operand)
    elif isinstance(node, Binary):
        yield from walk(node.left)
        yield from walk(node.right)


def _arith(op: str, a, b):
    if a is None or b is None:
        return None
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0:
        return None  # SQL semantics: division by zero is treated as unknown here
    return a / b


def _compare(op: str, a, b):
    if a is None or b is None:
        return None  # SQL three-valued logic: comparisons with NULL are unknown
    if op == "=":
        return a == b
    if op == "<>":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def evaluate(node: Node, group: dict, row: dict | None = None, gv: int | None = None):
    """Evaluate with SQL three-valued logic (None = unknown).

    ``group`` holds grouping attributes and computed aggregates of the mf-structure
    entry; ``row`` is the base-table tuple being scanned for grouping variable ``gv``.
    """
    if isinstance(node, Num) or isinstance(node, Str):
        return node.value
    if isinstance(node, GroupAttr):
        return group[node.name]
    if isinstance(node, RowAttr):
        if row is None or node.gv != gv:
            raise PhiSyntaxError(f"{node.gv}.{node.name} is not available in this context")
        return row[node.name]
    if isinstance(node, AggRef):
        return group[node.key]
    if isinstance(node, Unary):
        v = evaluate(node.operand, group, row, gv)
        if node.op == "neg":
            return None if v is None else -v
        return None if v is None else not v
    if node.op == "and":
        left = evaluate(node.left, group, row, gv)
        if left is False:
            return False
        right = evaluate(node.right, group, row, gv)
        if right is False:
            return False
        return None if left is None or right is None else True
    if node.op == "or":
        left = evaluate(node.left, group, row, gv)
        if left is True:
            return True
        right = evaluate(node.right, group, row, gv)
        if right is True:
            return True
        return None if left is None or right is None else False
    left = evaluate(node.left, group, row, gv)
    right = evaluate(node.right, group, row, gv)
    if node.op in _CMP:
        return _compare(node.op, left, right)
    return _arith(node.op, left, right)


def to_python(node: Node, group: str = "g", row: str = "r") -> str:
    """Render a validated AST into a Python expression calling the runtime helpers
    ``_and``, ``_or``, ``_not``, ``_cmp`` and ``_ar`` that codegen emits."""
    if isinstance(node, Num):
        return repr(node.value)
    if isinstance(node, Str):
        return repr(node.value)
    if isinstance(node, GroupAttr):
        return f"{group}[{node.name!r}]"
    if isinstance(node, RowAttr):
        return f"{row}[{node.name!r}]"
    if isinstance(node, AggRef):
        return f"{group}[{node.key!r}]"
    if isinstance(node, Unary):
        inner = to_python(node.operand, group, row)
        return f"_neg({inner})" if node.op == "neg" else f"_not({inner})"
    left = to_python(node.left, group, row)
    right = to_python(node.right, group, row)
    if node.op == "and":
        return f"_and(lambda: {left}, lambda: {right})"
    if node.op == "or":
        return f"_or(lambda: {left}, lambda: {right})"
    if node.op in _CMP:
        return f"_cmp({node.op!r}, {left}, {right})"
    return f"_ar({node.op!r}, {left}, {right})"
