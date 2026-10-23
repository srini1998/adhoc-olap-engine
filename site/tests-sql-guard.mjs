import assert from 'node:assert/strict';import{guardSql,extractSql,limited}from'./src/sql-guard.ts';
const ok=['SELECT team, SUM(points) AS pts FROM matches WHERE season=\'2024-25\' GROUP BY team ORDER BY pts DESC','WITH t AS (SELECT team, AVG(goals_for) g FROM matches GROUP BY team) SELECT * FROM t ORDER BY g DESC','SELECT EXTRACT(year FROM CAST(date AS DATE)) y, COUNT(*) n FROM matches GROUP BY y'];
for(const q of ok)assert.equal(guardSql(q).ok,true,q);
const bad=['DROP TABLE matches','SELECT 1; DROP TABLE matches','SELECT * FROM read_csv(\'https://x.example/a.csv\')',"SELECT * FROM 'https://x.example/a.parquet'","SELECT * FROM 'matches.json'",'COPY matches TO \'out.csv\'','SELECT * FROM duckdb_settings()','INSTALL httpfs','SELECT getenv(\'HOME\')','SELECT * FROM other_table','ATTACH \'x.db\'','PRAGMA version'];
for(const q of bad)assert.equal(guardSql(q).ok,false,q);
assert.equal(extractSql('Here:\n```sql\nSELECT team FROM matches;\n```'),'SELECT team FROM matches');
assert.match(limited('SELECT 1'),/LIMIT 200$/);
console.log(`sql-guard: ${ok.length} valid queries accepted, ${bad.length} unsafe queries rejected`);
