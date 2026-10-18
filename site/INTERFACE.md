# Football results explorer

The primary site queries 1520 real OpenFootball Premier League matches (CC0), normalized to 3040 team appearances. Each match contributes one home and one away appearance. Queries select season, team/season/venue grouping, goals/points measure, average/total/count and optional home-away partitions. Counting all teams gives twice the number of matches; goal totals do not double count goals scored.

A bounded rule-based translator handles explicit phrases such as “average points by team, compare home and away.” It is not a trained AI. Unknown fields/extra keys/unsupported seasons are rejected. Query changes invalidate old verification/proposals. CSV output is correctly quoted.

The independent check executes actual DuckDB-WASM SQL. Browser checks found that SUM(BIGINT) crossed the Arrow boundary as a quoted HUGEINT string, despite numerically identical results. Football SQL now explicitly casts aggregate output to DOUBLE; counts/sums in this bounded dataset are safely representable. This fixes transport compatibility without weakening the comparison. Two actual independent queries (20-team sum + all-season totals) now agree. Tests verify direct source totals for all 20 teams, venue sums, appearance counts and schema/season injection rejection.

The original CC0 scientific-data explorer remains at /penguins with its six existing tests. Optional fresh cloud query drafting there requires an explicitly confirmed free Groq account; no keys, billing or model downloads configured. Historical backend experiments remain separate.
