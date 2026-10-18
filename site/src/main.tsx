import { createRoot } from "react-dom/client";
import { useMemo, useState, useRef, useEffect, lazy, Suspense } from "react";
import matches from "./data/football.json";
import source from "./data/football-provenance.json";
import {
  teamRows,
  execute,
  sql,
  translate,
  dimensions,
  measures,
  operations,
  seasons,
  type Spec,
  type Result,
} from "./football-query";
import { Shell, Trace } from "./ui";
import "./styles.css";
const Penguin = lazy(() =>
    import("./PenguinLab").then((m) => ({ default: m.PenguinLab })),
  ),
  rows = teamRows(matches),
  initial: Spec = {
    groupBy: "team",
    measure: "goals_for",
    operation: "sum",
    compare: true,
    season: "2024-25",
  };
const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
function App() {
  const [spec, setSpec] = useState(initial),
    [question, setQuestion] = useState(
      "Compare total goals scored by team, home and away",
    ),
    [proposal, setProposal] = useState<Spec | null>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [entries, setEntries] = useState<unknown[]>([]);
  const revision = useRef(0),
    stop = useRef(() => {});
  useEffect(() => () => stop.current(), []);
  const results = useMemo(() => execute(rows, spec), [spec]);
  const names = ["group", "all", ...(spec.compare ? ["home", "away"] : [])];
  const log = (e: unknown) => setEntries((a) => [...a, e]);
  function update(p: Partial<Spec>) {
    stop.current();
    revision.current++;
    setBusy(false);
    setMessage("");
    setProposal(null);
    setSpec((s) => ({ ...s, ...p }));
  }
  async function verify() {
    const rev = ++revision.current;
    setBusy(true);
    setMessage("Opening DuckDB and running the equivalent SQL…");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const { check } = await import("./duck");
      const other = await Promise.race([
        check(sql(spec), rows, (c) => (stop.current = c), "matches"),
        new Promise<never>(
          (_, reject) =>
            (timer = setTimeout(() => {
              stop.current();
              reject(Error("DuckDB check timed out. Try again."));
            }, 60000)),
        ),
      ]);
      if (rev !== revision.current) return;
      const pass =
        results.length === other.length &&
        results.every((r, i) =>
          names.every((k) => {
            const a = r[k as keyof Result],
              b = other[i][k as keyof (typeof other)[number]];
            return typeof a === "number" && typeof b === "number"
              ? Math.abs(a - b) <= 1e-8 * Math.max(1, Math.abs(a))
              : a === b;
          }),
        );
      setMessage(
        pass
          ? "Matched: every group and value agrees with independent DuckDB SQL."
          : "Mismatch: inspect the run details before using these numbers.",
      );
      log({
        action: "independent-SQL-check",
        spec,
        sql: sql(spec),
        phi: results,
        duckdb: other,
        pass,
      });
    } catch (e) {
      if (rev === revision.current) setMessage(String(e));
    } finally {
      clearTimeout(timer);
      if (rev === revision.current) setBusy(false);
    }
  }
  function download() {
    const quote = (v: unknown) =>
      '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const csv = [
      names.map(quote).join(","),
      ...results.map((r) =>
        names.map((k) => quote(r[k as keyof Result])).join(","),
      ),
    ].join("\n");
    const u = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = u;
    a.download = "crosscut-football.csv";
    a.click();
    URL.revokeObjectURL(u);
  }
  return (
    <Shell
      name="crosscut / match stats"
      number="05"
      ja={false}
      toggle={() => {}}
    >
      <section className="hero football-hero">
        <div>
          <p className="eyebrow">THE FOOTBALL DATA, WITHOUT THE SPREADSHEET</p>
          <h1>
            Who scored?
            <br />
            Where? How often?
          </h1>
          <p className="intro">
            Compare Premier League teams across four seasons. Break down goals
            and points at home and away, then check every number with a second
            query engine.
          </p>
          <a className="cta" href="#explore">
            Explore the match stats ↗
          </a>
          <p className="note">
            Real results. Instant queries. No AI download or account.
          </p>
        </div>
        <div className="scoreboard" aria-hidden="true">
          <span>OPENFOOTBALL / PREMIER LEAGUE</span>
          <strong>
            HOME<span>:</span>AWAY
          </strong>
          <div>
            <span>GOALS</span>
            <span>POINTS</span>
            <span>4 SEASONS</span>
          </div>
          <p>
            1,520 completed matches
            <br />
            2021/22 — 2024/25
          </p>
        </div>
      </section>
      <main id="explore">
        <div className="section-head">
          <div>
            <p className="eyebrow">YOUR MATCHDAY QUESTION</p>
            <h2>Get straight to the numbers.</h2>
          </div>
          <span>HISTORICAL SNAPSHOT</span>
        </div>
        <section className="query-row">
          <div>
            <label htmlFor="question">Ask a supported question</label>
            <textarea
              id="question"
              value={question}
              maxLength={400}
              onChange={(e) => {
                setQuestion(e.target.value);
                setProposal(null);
                setMessage("");
              }}
            />
            <p className="note">
              Try “Average points by team, compare home and away” or “Total
              goals conceded by season.” This is a small rule-based query
              translator, not an AI model. It handles the listed fields only.
            </p>
            <button
              onClick={() => {
                try {
                  setProposal(translate(question, spec.season));
                  setMessage(
                    "Query draft ready. Review the fields before applying.",
                  );
                } catch (e) {
                  setProposal(null);
                  setMessage(String(e));
                }
              }}
            >
              Turn into a query
            </button>
            {proposal && (
              <div className="query-proposal">
                <pre>{JSON.stringify(proposal, null, 2)}</pre>
                <button
                  onClick={() => {
                    update(proposal);
                    log({ action: "apply-reviewed-query", proposal });
                  }}
                >
                  Apply reviewed query
                </button>
              </div>
            )}
          </div>
          <section className="query-controls">
            <label htmlFor="season">Season</label>
            <select
              id="season"
              value={spec.season}
              onChange={(e) => update({ season: e.target.value })}
            >
              <option value="all">All four seasons</option>
              {seasons.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <label htmlFor="group">Group by</label>
            <select
              id="group"
              value={spec.groupBy}
              onChange={(e) =>
                update({ groupBy: e.target.value as Spec["groupBy"] })
              }
            >
              {dimensions.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <label htmlFor="measure">Measure</label>
            <select
              id="measure"
              value={spec.measure}
              onChange={(e) =>
                update({ measure: e.target.value as Spec["measure"] })
              }
            >
              {measures.map((s) => (
                <option key={s} value={s}>
                  {s.replaceAll("_", " ")}
                </option>
              ))}
            </select>
            <label htmlFor="aggregate">Calculation</label>
            <select
              id="aggregate"
              value={spec.operation}
              onChange={(e) =>
                update({ operation: e.target.value as Spec["operation"] })
              }
            >
              {operations.map((s) => (
                <option key={s} value={s}>
                  {s === "avg"
                    ? "Average"
                    : s === "sum"
                      ? "Total"
                      : "Count appearances"}
                </option>
              ))}
            </select>
            <label className="check">
              <input
                type="checkbox"
                checked={spec.compare}
                onChange={(e) => update({ compare: e.target.checked })}
              />{" "}
              Show home / away split
            </label>
          </section>
        </section>
        <section className="football-results">
          <div className="section-head">
            <h3>
              {spec.operation === "avg"
                ? "Average"
                : spec.operation === "sum"
                  ? "Total"
                  : "Count"}{" "}
              {spec.measure.replaceAll("_", " ")} by {spec.groupBy}
            </h3>
            <div className="actions">
              <button className="cta" disabled={busy} onClick={verify}>
                {busy ? "Checking…" : "Check with DuckDB SQL"}
              </button>
              <button onClick={download}>Export CSV</button>
            </div>
          </div>
          <output role="status">{message}</output>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {names.map((n) => (
                    <th key={n}>
                      {n === "all"
                        ? "All appearances"
                        : n === "home"
                          ? "At home"
                          : n === "away"
                            ? "Away"
                            : spec.groupBy}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.group}>
                    {names.map((n) => (
                      <td key={n}>
                        {n === "group"
                          ? r.group
                          : fmt(r[n as keyof Result] as number | null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">
            One row per team appearance: each real match contributes one home
            and one away row. Counting across all teams gives twice the match
            count. All {source.rows} matches become {rows.length} team
            appearances; the selected season is {spec.season}.
          </p>
          <details className="sql-details">
            <summary>See the exact SQL</summary>
            <pre>{sql(spec)}</pre>
          </details>
        </section>
        <section id="how" className="how">
          <p className="eyebrow">WHY TWO ENGINES?</p>
          <h2>Useful answers deserve a second check.</h2>
          <p>
            Imagine comparing Arsenal’s home scoring with its away scoring. The
            first engine groups the rows and keeps separate totals. The optional
            check runs equivalent SQL in actual DuckDB-WASM and compares every
            output value. The translator cannot execute arbitrary SQL.
          </p>
          <p>
            Results are from{" "}
            <a href="https://github.com/openfootball/football.json">
              OpenFootball’s CC0 match archive ↗
            </a>
            . They are historical match totals, not player statistics, live
            standings, attendance or betting predictions. Counts measure
            appearances. Average points includes draws as one point.
          </p>
          <p>
            <a href="/FOOTBALL-LICENSE.md">Dataset license ↗</a> ·{" "}
            <a href="/penguins">Original scientific-data explorer ↗</a>
          </p>
          <details>
            <summary>Source snapshot and hashes</summary>
            <pre>{JSON.stringify(source, null, 2)}</pre>
          </details>
        </section>
      </main>
      <Trace entries={entries} ja={false} />
    </Shell>
  );
}
createRoot(document.getElementById("root")!).render(
  location.pathname === "/penguins" ? (
    <Suspense fallback={<p>Opening scientific-data explorer…</p>}>
      <Penguin />
    </Suspense>
  ) : (
    <App />
  ),
);
