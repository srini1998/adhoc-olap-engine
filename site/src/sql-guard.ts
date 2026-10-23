// Deterministic guard for SQL proposed by the optional cloud agent.
// Only one read-only SELECT over the in-browser `matches` table may run, and it is wrapped in a row limit.
export const MATCH_COLUMNS = ["season", "date", "team", "opponent", "venue", "goals_for", "goals_against", "points"] as const;
export const SCHEMA_TEXT = `Table matches: one row per team per Premier League match, seasons 2021-22..2024-25 (OpenFootball CC0).
Columns: season VARCHAR ('2021-22','2022-23','2023-24','2024-25'), date VARCHAR ('YYYY-MM-DD'), team VARCHAR, opponent VARCHAR, venue VARCHAR ('home'|'away'), goals_for INTEGER, goals_against INTEGER, points INTEGER (3 win, 1 draw, 0 loss).`;
export const ROW_LIMIT = 200;
const FORBIDDEN = /\b(insert|update|delete|create|drop|alter|attach|detach|copy|export|import|install|load|pragma|call|set|reset|checkpoint|vacuum|use|grant|truncate|replace|merge|execute|prepare|describe|summarize|show)\b/i;
const FORBIDDEN_FUNCS = /\b(read_\w+|glob|\w*_scan|query_table|query|getenv|current_setting|duckdb_\w+|sqlite_\w+|pg_\w+|http\w*)\s*\(/i;
export type Guard = { ok: boolean; sql: string; checks: { name: string; ok: boolean; detail?: string }[] };
export function extractSql(text: string) {
  const fenced = text.match(/```(?:sql)?\s*\n?([\s\S]*?)```/i)?.[1];
  const raw = (fenced ?? text.slice(Math.max(0, text.search(/\b(with|select)\b/i)))).trim();
  return raw.replace(/;\s*$/, "").trim();
}
export function guardSql(sql: string): Guard {
  const stripped = sql.replace(/'(?:[^']|'')*'/g, "''"); // ignore string literal contents for keyword checks
  const ctes = [...stripped.matchAll(/(?:\bwith\b|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(/gi)].map((m) => m[1].toLowerCase());
  const sources = [...stripped.matchAll(/\b(?:from|join)\s+("?[a-z_][a-z0-9_.]*"?(?![a-z0-9_."])(?!\s*\()|\()/gi)].map((m) => m[1].replaceAll('"', "").toLowerCase());
  const columns: readonly string[] = MATCH_COLUMNS;
  // EXTRACT(year FROM date) style column references are not table sources.
  const badSources = sources.filter((s) => s !== "(" && s !== "matches" && !ctes.includes(s) && !columns.includes(s));
  if (/\b(?:from|join)\s+''/i.test(stripped)) badSources.push("file/string source");
  const checks = [
    { name: "Single statement", ok: sql.length > 0 && !stripped.includes(";") },
    { name: "Read-only SELECT", ok: /^\s*(select|with)\b/i.test(stripped) && !FORBIDDEN.test(stripped), detail: stripped.match(FORBIDDEN)?.[0] },
    { name: "No file, network or system functions", ok: !FORBIDDEN_FUNCS.test(stripped) && !/:\/\/|\$\w/.test(sql), detail: stripped.match(FORBIDDEN_FUNCS)?.[0] },
    { name: "Reads only the matches table", ok: sources.length > 0 && badSources.length === 0, detail: badSources.join(", ") || undefined },
    { name: "Short (≤ 1,500 characters)", ok: sql.length <= 1500 },
  ];
  return { ok: checks.every((c) => c.ok), sql, checks };
}
export const limited = (sql: string) => `SELECT * FROM (\n${sql}\n) AS agent_query LIMIT ${ROW_LIMIT}`;
export function agentPrompt(question: string) {
  return `${SCHEMA_TEXT}
Write ONE DuckDB SELECT query (no other statements) over the table matches that answers the request. Use only the columns listed. Give result columns short readable aliases. Return only the SQL in a \`\`\`sql code fence.
Request: ${question.slice(0, 400)}`;
}
