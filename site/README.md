# Crosscut
An end-user data comparison tool. `npm ci && npm run dev`. 344 real Palmer Archipelago penguin observations (2007–2009), CC0, attribution and source SHA in src/data/source.json. Missing numeric values are null; missing sex becomes an explicit unknown group. Numeric aggregates ignore nulls, including count(selected measurement).

A bounded TypeScript Phi-style interpreter first seeds its grouped structure then accumulates all/male/female grouping variables. Three group keys, three measures, avg/sum/count only. It is not the full Python MF/EMF grammar or arbitrary dependency planner. `Check with DuckDB` loads pinned DuckDB-WASM 1.32.0 and independently executes equivalent whitelisted SQL. Values are compared at 1e-8 relative tolerance. No arbitrary SQL or evaluated JavaScript/Python from model text.

Optional Gemma3 1B q4 suggests a JSON query on-device. Strict schema rejects unknown fields, expressions and unsupported values. Suggestions must be reviewed and applied before execution. The browser AI does not calculate the displayed numbers. Trace is secondary, CSV download is actual computed output. EN/JA, ThreeUI Community DotMatrix (MIT), GSAP entrance respects reduced motion.

`node tests-phi.mjs`: null/group accumulation, counts, schema injection/extra-field rejection and comparator negative checks. Browser evidence in delivery/evidence/crosscut-browser.json includes two actual independent DuckDB-WASM comparisons, mobile and language flows. Recorded Python eight-query SQL comparison on synthetic sales is labeled separately. No paid APIs.
