import * as duckdb from "@duckdb/duckdb-wasm";
import type { Result } from "./phi";
export async function check(
  sql: string,
  rows: unknown[],
  onStop: (stop: () => void) => void,
  tableName: "penguins" | "matches" = "penguins",
) {
  if (!["penguins", "matches"].includes(tableName))
    throw new Error("Unsupported table");
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const blob = URL.createObjectURL(
    new Blob([`importScripts(${JSON.stringify(bundle.mainWorker)});`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(blob);
  URL.revokeObjectURL(blob);
  const db = new duckdb.AsyncDuckDB(
    new duckdb.ConsoleLogger(duckdb.LogLevel.ERROR),
    worker,
  );
  onStop(() => {
    void db.terminate();
    worker.terminate();
  });
  let conn: duckdb.AsyncDuckDBConnection | undefined;
  try {
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    await db.registerFileText(tableName + ".json", JSON.stringify(rows));
    conn = await db.connect();
    await conn.query(
      `CREATE TABLE ${tableName} AS SELECT * FROM read_json_auto('${tableName}.json')`,
    );
    const table = await conn.query(sql);
    return table
      .toArray()
      .map((r: any) => {
        const o = r.toJSON();
        return Object.fromEntries(
          Object.entries(o).map(([k, v]) => [
            k,
            typeof v === "bigint" ? Number(v) : v,
          ]),
        ) as Result;
      })
      .sort((a, b) => a.group.localeCompare(b.group));
  } finally {
    await conn?.close().catch(() => {});
    await db.terminate();
    worker.terminate();
  }
}

// Runs one already-guarded read-only query against a fresh in-browser DuckDB holding only `matches`.
export async function runQuery(
  sql: string,
  rows: unknown[],
  onStop: (stop: () => void) => void,
) {
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const blob = URL.createObjectURL(
    new Blob([`importScripts(${JSON.stringify(bundle.mainWorker)});`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(blob);
  URL.revokeObjectURL(blob);
  const db = new duckdb.AsyncDuckDB(
    new duckdb.ConsoleLogger(duckdb.LogLevel.ERROR),
    worker,
  );
  onStop(() => {
    void db.terminate();
    worker.terminate();
  });
  let conn: duckdb.AsyncDuckDBConnection | undefined;
  try {
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    await db.registerFileText("matches.json", JSON.stringify(rows));
    conn = await db.connect();
    await conn.query(
      "CREATE TABLE matches AS SELECT * FROM read_json_auto('matches.json')",
    );
    const table = await conn.query(sql);
    const columns = table.schema.fields.map((f) => f.name);
    const out = table.toArray().map((r: any) => {
      const o = r.toJSON();
      return Object.fromEntries(
        columns.map((k) => {
          const v = o[k];
          return [k, typeof v === "bigint" ? Number(v) : v];
        }),
      ) as Record<string, unknown>;
    });
    return { columns, rows: out };
  } finally {
    await conn?.close().catch(() => {});
    await db.terminate();
    worker.terminate();
  }
}
