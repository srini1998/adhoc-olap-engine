export const dimensions = ["species", "island", "sex"] as const;
export const measures = [
  "body_mass_g",
  "flipper_length_mm",
  "bill_length_mm",
] as const;
export const operations = ["avg", "sum", "count"] as const;
export type Phi = {
  groupBy: (typeof dimensions)[number];
  measure: (typeof measures)[number];
  operation: (typeof operations)[number];
  compare: boolean;
};
export type Row = {
  species: string;
  island: string;
  sex: string | null;
  body_mass_g: number | null;
  flipper_length_mm: number | null;
  bill_length_mm: number | null;
  [key: string]: unknown;
};
export type Result = {
  group: string;
  all: number | null;
  male?: number | null;
  female?: number | null;
};
export function validate(x: unknown): Phi {
  if (!x || typeof x !== "object" || Array.isArray(x))
    throw new Error("Expected query object");
  const p = x as Record<string, unknown>;
  if (
    Object.keys(p).some(
      (k) => !["groupBy", "measure", "operation", "compare"].includes(k),
    ) ||
    !dimensions.includes(p.groupBy as any) ||
    !measures.includes(p.measure as any) ||
    !operations.includes(p.operation as any) ||
    typeof p.compare !== "boolean"
  )
    throw new Error(
      "Unsupported query. Choose a listed group, measurement, aggregate and boolean comparison.",
    );
  return p as Phi;
}
export function execute(rows: Row[], spec: Phi) {
  validate(spec);
  type A = { n: number; sum: number };
  const groups = new Map<string, { all: A; male: A; female: A }>();
  const acc = () => ({ n: 0, sum: 0 });
  for (const r of rows) {
    const key = String(r[spec.groupBy] ?? "unknown");
    if (!groups.has(key))
      groups.set(key, { all: acc(), male: acc(), female: acc() });
  }
  for (const r of rows) {
    const g = groups.get(String(r[spec.groupBy] ?? "unknown"))!,
      v = r[spec.measure];
    if (v === null || typeof v !== "number" || !Number.isFinite(v)) continue;
    for (const gv of [
      "all",
      ...(r.sex === "male" ? ["male"] : r.sex === "female" ? ["female"] : []),
    ] as ("all" | "male" | "female")[]) {
      g[gv].n++;
      g[gv].sum += v;
    }
  }
  const value = (a: A) =>
    spec.operation === "count"
      ? a.n
      : a.n === 0
        ? null
        : spec.operation === "avg"
          ? a.sum / a.n
          : a.sum;
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([group, g]) => ({
      group,
      all: value(g.all),
      ...(spec.compare ? { male: value(g.male), female: value(g.female) } : {}),
    }));
}
export function sql(spec: Phi) {
  validate(spec);
  const expr = (segment?: string) =>
    `${spec.operation.toUpperCase()}(${segment ? `CASE WHEN sex='${segment}' THEN "${spec.measure}" END` : `"${spec.measure}"`})`;
  return `SELECT COALESCE("${spec.groupBy}",'unknown') AS "group", ${expr()} AS "all"${spec.compare ? `, ${expr("male")} AS male, ${expr("female")} AS female` : ""}\nFROM penguins\nGROUP BY "${spec.groupBy}"\nORDER BY "group"`;
}
export function same(a: Result[], b: Result[]) {
  return (
    a.length === b.length &&
    a.every((r, i) =>
      Object.keys(r).every((k) => {
        const x = (r as any)[k],
          y = (b[i] as any)[k];
        return typeof x === "number" && typeof y === "number"
          ? Math.abs(x - y) <= 1e-8 * Math.max(1, Math.abs(x))
          : x === y;
      }),
    )
  );
}
