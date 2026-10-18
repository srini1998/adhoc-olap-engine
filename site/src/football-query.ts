export const dimensions = ["team", "season", "venue"] as const,
  measures = ["goals_for", "goals_against", "points"] as const,
  operations = ["avg", "sum", "count"] as const,
  seasons = ["2021-22", "2022-23", "2023-24", "2024-25"] as const;
export type Spec = {
  groupBy: (typeof dimensions)[number];
  measure: (typeof measures)[number];
  operation: (typeof operations)[number];
  compare: boolean;
  season: string;
};
export type Match = {
  season: string;
  date: string;
  home: string;
  away: string;
  hg: number;
  ag: number;
};
export type TeamRow = {
  season: string;
  date: string;
  team: string;
  opponent: string;
  venue: string;
  goals_for: number;
  goals_against: number;
  points: number;
};
export type Result = {
  group: string;
  all: number | null;
  home?: number | null;
  away?: number | null;
};
export function teamRows(matches: Match[]): TeamRow[] {
  return matches.flatMap((m) => [
    {
      season: m.season,
      date: m.date,
      team: m.home,
      opponent: m.away,
      venue: "home",
      goals_for: m.hg,
      goals_against: m.ag,
      points: m.hg > m.ag ? 3 : m.hg === m.ag ? 1 : 0,
    },
    {
      season: m.season,
      date: m.date,
      team: m.away,
      opponent: m.home,
      venue: "away",
      goals_for: m.ag,
      goals_against: m.hg,
      points: m.ag > m.hg ? 3 : m.ag === m.hg ? 1 : 0,
    },
  ]);
}
export function validate(x: unknown): Spec {
  if (!x || typeof x !== "object" || Array.isArray(x))
    throw Error("Expected query object");
  const s = x as Spec;
  if (
    Object.keys(s).some(
      (k) =>
        !["groupBy", "measure", "operation", "compare", "season"].includes(k),
    ) ||
    !dimensions.includes(s.groupBy) ||
    !measures.includes(s.measure) ||
    !operations.includes(s.operation) ||
    typeof s.compare !== "boolean" ||
    !(
      s.season === "all" ||
      seasons.includes(s.season as (typeof seasons)[number])
    )
  )
    throw Error("Use only the listed group, metric, operation and season.");
  return s;
}
export function execute(rows: TeamRow[], s: Spec): Result[] {
  validate(s);
  const groups = new Map<
    string,
    Record<"all" | "home" | "away", { n: number; sum: number }>
  >();
  const selected = rows.filter(
    (r) => s.season === "all" || r.season === s.season,
  );
  for (const r of selected)
    if (!groups.has(r[s.groupBy]))
      groups.set(r[s.groupBy], {
        all: { n: 0, sum: 0 },
        home: { n: 0, sum: 0 },
        away: { n: 0, sum: 0 },
      });
  for (const r of selected) {
    const g = groups.get(r[s.groupBy])!;
    for (const k of ["all", r.venue] as ("all" | "home" | "away")[]) {
      g[k].n++;
      g[k].sum += r[s.measure];
    }
  }
  const value = (a: { n: number; sum: number }) =>
    s.operation === "count"
      ? a.n
      : !a.n
        ? null
        : s.operation === "sum"
          ? a.sum
          : a.sum / a.n;
  return [...groups]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([group, g]) => ({
      group,
      all: value(g.all),
      ...(s.compare ? { home: value(g.home), away: value(g.away) } : {}),
    }));
}
export function sql(s: Spec) {
  validate(s);
  const expr = (venue?: string) =>
    `CAST(${s.operation.toUpperCase()}(${venue ? `CASE WHEN venue='${venue}' THEN "${s.measure}" END` : `"${s.measure}"`}) AS DOUBLE)`;
  return `SELECT "${s.groupBy}" AS "group", ${expr()} AS "all"${s.compare ? `, ${expr("home")} AS home, ${expr("away")} AS away` : ""}\nFROM matches${s.season === "all" ? "" : `\nWHERE season='${s.season}'`}\nGROUP BY "${s.groupBy}"\nORDER BY "group"`;
}
export function translate(question: string, season: string): Spec {
  const q = question.toLowerCase();
  if (q.length > 400) throw Error("Use a short request.");
  if (!/team|season|venue/.test(q))
    throw Error("Include “by team”, “by season” or “by venue”.");
  if (
    /player|odds|injur|predict|win probability|stadium|ticket|possession|shots|corners|cards/.test(
      q,
    )
  )
    throw Error(
      "This dataset has team results only: goals, points, season and venue.",
    );
  const groupBy = /by season/.test(q)
    ? "season"
    : /by venue/.test(q)
      ? "venue"
      : /by team/.test(q)
        ? "team"
        : null;
  if (!groupBy)
    throw Error("Use an explicit grouping: by team, by season or by venue.");
  const operation = /average|mean/.test(q)
    ? "avg"
    : /count|number of/.test(q)
      ? "count"
      : /total|sum|most/.test(q)
        ? "sum"
        : null;
  if (!operation) throw Error("Ask for an average, total or count.");
  const measure = /point/.test(q)
    ? "points"
    : /conceded|against/.test(q)
      ? "goals_against"
      : /goal|match|game/.test(q)
        ? "goals_for"
        : null;
  if (!measure)
    throw Error(
      "Ask about goals scored, goals conceded, points or match counts.",
    );
  return validate({
    groupBy,
    measure,
    operation,
    compare: /compare|home.*away|away.*home/.test(q),
    season,
  });
}
