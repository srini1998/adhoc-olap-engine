"""Command line: seed, explain, run, generate and verify Phi queries."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from . import codegen, seed
from .engine import evaluate, table_columns
from .spec import parse_phi

log = logging.getLogger("olap")
DEFAULT_DSN = "postgresql://olap@127.0.0.1:54562/olap"


def _dsn(args) -> str:
    return args.dsn or os.environ.get("OLAP_DSN", DEFAULT_DSN)


def _load(path: Path, conn) -> object:
    text = path.read_text()
    table = "sales"
    for line in text.splitlines():
        if line.strip().upper().startswith("TABLE"):
            table = line.split(":", 1)[1].strip().lower()
    return parse_phi(text, table_columns(conn, table))


def normalize(rows: list[dict], columns: list[str]) -> list[tuple]:
    """Make engine and SQL results comparable: same column order, floats rounded."""
    out = []
    for r in rows:
        vals = []
        for c in columns:
            v = r[c]
            if v is not None and type(v).__name__ == "Decimal":
                v = float(v)
            if isinstance(v, float):
                v = round(v, 6)
            vals.append(v)
        out.append(tuple(vals))
    return sorted(out, key=lambda t: tuple((x is None, x) for x in t))


def cmd_seed(args) -> None:
    with psycopg.connect(_dsn(args)) as conn:
        count = seed.load(conn, args.rows, args.seed)
    print(f"loaded {count} synthetic rows into sales (seed={args.seed})")


def cmd_explain(args) -> None:
    with psycopg.connect(_dsn(args)) as conn:
        q = _load(Path(args.query), conn)
    from .engine import equality_keys

    print(f"table: {q.table}\ngrouping attributes: {', '.join(q.group_by)}\nscans: {q.scans}")
    for level in range(1, q.scans):
        for gv in q.gvs_at_level(level):
            if gv == 0:
                how = "whole group (hash on V)"
            else:
                keys = equality_keys(q.sigma[gv], gv)
                how = f"hash on {', '.join(k for k, _ in keys)}" if keys else "full probe of every group"
            aggs = ", ".join(a.key for a in q.aggregates_for(gv))
            print(f"  scan {level}: gv {gv} [{how}] -> {aggs}")


def cmd_run(args) -> None:
    with psycopg.connect(_dsn(args)) as conn:
        q = _load(Path(args.query), conn)
        t0 = time.perf_counter()
        rows, stats = evaluate(q, conn)
    print(json.dumps(rows, indent=2, default=str))
    print(
        f"-- {len(rows)} rows, {stats.groups} groups, {stats.scans} scans, "
        f"{stats.rows_read} rows read, {time.perf_counter() - t0:.3f}s",
        file=sys.stderr,
    )


def cmd_generate(args) -> None:
    with psycopg.connect(_dsn(args)) as conn:
        q = _load(Path(args.query), conn)
    src = codegen.generate(q)
    if args.output:
        Path(args.output).write_text(src)
        print(f"wrote {args.output}")
    else:
        print(src)


def cmd_verify(args) -> None:
    """For every queries/*.mf: interpreter == generated program == hand-written SQL."""
    dsn = _dsn(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    failures = 0
    with psycopg.connect(dsn) as conn:
        total_rows = conn.execute("select count(*) from sales").fetchone()[0]
        for mf in sorted(Path(args.queries).glob("*.mf")):
            q = _load(mf, conn)
            t0 = time.perf_counter()
            engine_rows, stats = evaluate(q, conn)
            engine_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            cur = conn.execute(mf.with_suffix(".sql").read_text())
            sql_cols = [d.name for d in cur.description]
            sql_rows = [dict(zip(sql_cols, r)) for r in cur.fetchall()]
            sql_s = time.perf_counter() - t0

            prog = out_dir / f"{mf.stem}.py"
            prog.write_text(codegen.generate(q))
            t0 = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, str(prog)], env={**os.environ, "OLAP_DSN": dsn},
                capture_output=True, text=True, timeout=300,
            )
            gen_s = time.perf_counter() - t0
            gen_rows = json.loads(proc.stdout) if proc.returncode == 0 else None

            a = normalize(engine_rows, q.select)
            b = normalize(sql_rows, q.select)
            c = normalize(gen_rows, q.select) if gen_rows is not None else None
            ok = a == b and c == a
            failures += not ok
            entry = {
                "query": mf.name,
                "rows": len(engine_rows),
                "groups": stats.groups,
                "scans": stats.scans,
                "indexed_gvs": stats.indexed_gvs,
                "full_probe_gvs": stats.full_probe_gvs,
                "interpreter_matches_sql": a == b,
                "generated_matches_interpreter": c == a,
                "seconds": {"interpreter": round(engine_s, 3), "generated": round(gen_s, 3), "postgres_sql": round(sql_s, 3)},
            }
            if proc.returncode != 0:
                entry["generated_error"] = proc.stderr[-2000:]
            report.append(entry)
            mark = "PASS" if ok else "FAIL"
            print(f"{mark} {mf.name}: {len(engine_rows)} rows, {stats.scans} scans, "
                  f"interp {engine_s:.2f}s / generated {gen_s:.2f}s / SQL {sql_s:.3f}s")
    summary = {"base_rows": total_rows, "queries": len(report), "failures": failures, "results": report}
    Path(args.report).write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{len(report) - failures}/{len(report)} queries agree across interpreter, generated program and SQL")
    sys.exit(1 if failures else 0)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="olap", description=__doc__)
    p.add_argument("--dsn", help=f"PostgreSQL DSN (default $OLAP_DSN or {DEFAULT_DSN})")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="load the deterministic synthetic sales table")
    s.add_argument("--rows", type=int, default=10_000)
    s.add_argument("--seed", type=int, default=562)
    s.set_defaults(fn=cmd_seed)
    for name, fn, help_ in (("explain", cmd_explain, "show the scan plan"), ("run", cmd_run, "evaluate a query"),
                            ("generate", cmd_generate, "emit a standalone Python program")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("query")
        if name == "generate":
            s.add_argument("-o", "--output")
        s.set_defaults(fn=fn)
    s = sub.add_parser("verify", help="check every query against its hand-written SQL")
    s.add_argument("--queries", default="queries")
    s.add_argument("--out", default="generated")
    s.add_argument("--report", default="docs/verification.json")
    s.set_defaults(fn=cmd_verify)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
