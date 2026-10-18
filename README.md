# Ad-Hoc OLAP Query Engine

An engine for **Multi-Feature (MF)** and **Extended Multi-Feature (EMF)** queries, written as the
*Phi operator*. It evaluates them over PostgreSQL **without using the database's GROUP BY**: it streams
the base table through a server-side cursor and builds an in-memory *mf-structure*, one scan per
dependency level. It can interpret a query directly or **generate a standalone Python program** for it.

> Rebuild note: the original coursework source wasn't recoverable, so this is a fresh, scoped
> implementation of the same idea with an independent correctness check.

## Why MF/EMF queries?

"For each customer, compare their average purchase in NY with NJ and CT" needs three differently
filtered aggregates over the same group. In SQL that becomes several joined sub-queries. The Phi
operator says it directly:

```
SELECT ATTRIBUTE(S):           cust, 1_avg_quant, 2_avg_quant, 3_avg_quant
NUMBER OF GROUPING VARIABLES:  3
GROUPING ATTRIBUTES(V):        cust
F-VECT([F]):                   1_avg_quant, 2_avg_quant, 3_avg_quant
SELECT CONDITION-VECT([σ]):
  1.cust = cust and 1.state = 'NY'
  2.cust = cust and 2.state = 'NJ'
  3.cust = cust and 3.state = 'CT'
HAVING_CONDITION(G):           1_avg_quant > 2_avg_quant and 1_avg_quant > 3_avg_quant
```

EMF conditions may relate a row to *other* groups, for example the previous month
(`1.month = month - 1`), or to aggregates of other grouping variables (`3.quant > 1_avg_quant`).

## How it works

1. **Parse and validate.** A recursive-descent parser builds a small, closed AST
   (`olap/expr.py`). Columns are checked against `information_schema`, aggregates against F-VECT,
   and cyclic dependencies are rejected. Nothing is passed to `eval`.
2. **Plan scans.** If grouping variable *i* reads an aggregate of *j*, *i* runs in a later scan
   (`spec.plan_levels`). `olap explain` prints the plan.
3. **Index.** Top-level conjuncts like `1.cust = cust` or `1.month = month - 1` become a hash index
   from row values to mf-structure entries. Conditions without one, like `1.prod <> prod`, fall back
   to probing every group, and the run reports which grouping variables did.
4. **Aggregate with SQL semantics.** NULLs are ignored by aggregates. `sum`/`avg` of nothing is
   NULL and `count` is 0. Predicates use three-valued logic.
5. **Generate (optional).** `olap generate` renders the same plan into a specialized program that
   depends only on `psycopg`. Literals are emitted with `repr`, so query text never becomes code.

## Run it

```bash
./scripts/pg.sh            # throwaway local cluster on :54562 (verified with PostgreSQL 14.17; CI uses 17)
uv sync
uv run olap seed           # 10,000 deterministic synthetic sales rows
uv run olap explain queries/q4_between_neighbors.mf
uv run olap run queries/q3_neighbor_months.mf
uv run olap generate queries/q1_state_averages.mf -o q1.py && OLAP_DSN=postgresql://olap@127.0.0.1:54562/olap python q1.py
uv run olap verify         # interpreter vs generated program vs hand-written SQL
uv run pytest
```

## How correctness is checked

| Check | What it compares |
|---|---|
| `olap verify` | For each of 8 queries in `queries/`: interpreter, generated program, and an independently hand-written SQL query (`.sql` next to each `.mf`). |
| Differential test | 300 random MF/EMF queries over random data with NULLs vs a naive reference that uses no indexes and no scan planning. |
| Generated-code test | 60 random queries: generated program output == interpreter output. |
| Negative control | Deliberately breaking the shifted-key index must make the differential check fail. |
| Injection test | A string literal containing Python code is emitted only as a string constant. |

Results recorded in `docs/verification.json` (10k rows) and `docs/verification-200k.json` (200k rows):
**8/8 queries agree** at both sizes. 17 pytest tests pass.

## Honest performance

At 200k rows the interpreter takes 0.6–3.0 s per query, the generated programs 0.6–1.6 s, and
PostgreSQL's own SQL 0.01–1.2 s. Postgres is far faster for simple grouped filters. The engine is
about expressiveness and a transparent evaluation model, not beating a mature optimizer. On the two
correlated-subquery queries (q4, q8) the gap closes (1.1–1.6 s generated vs 1.2 s SQL).

## Scope and limits

- Data is a **synthetic, seeded** `sales` table in the classic coursework schema, not real sales.
- Single table, aggregates `count/sum/avg/min/max`. No joins, `DISTINCT` aggregates or expressions
  in the select list.
- The mf-structure must fit in memory. Full-probe grouping variables cost rows × groups.
