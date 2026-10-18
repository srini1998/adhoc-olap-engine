"""Deterministic synthetic ``sales`` table in the classic MF/EMF coursework schema.

The data is generated, not collected: it exists so every query and its SQL
equivalent can be re-run byte-for-byte on any machine.
"""

from __future__ import annotations

import datetime as dt
import random

CUSTOMERS = ["Bloom", "Chae", "Dimitri", "Emily", "Helen", "Knuth", "Mia", "Sam", "Wally", "Yuki"]
PRODUCTS = ["Apple", "Butter", "Cherry", "Dates", "Eggs", "Fish", "Grapes", "Ham", "Ice", "Jelly"]
STATES = ["NY", "NJ", "CT", "PA"]
SCHEMA = """
create table sales (
    cust  varchar(20) not null,
    prod  varchar(20) not null,
    day   integer     not null,
    month integer     not null,
    year  integer     not null,
    state char(2)     not null,
    quant integer     not null,
    date  date        not null
)
"""


def rows(n: int = 10_000, seed: int = 562):
    rng = random.Random(seed)
    for _ in range(n):
        year = rng.choice([2016, 2017, 2018, 2019, 2020])
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        yield (
            rng.choice(CUSTOMERS),
            rng.choice(PRODUCTS),
            day,
            month,
            year,
            rng.choices(STATES, weights=[4, 3, 2, 1])[0],
            rng.randint(1, 1000),
            dt.date(year, month, day),
        )


def load(conn, n: int = 10_000, seed: int = 562) -> int:
    with conn.transaction():
        conn.execute("drop table if exists sales")
        conn.execute(SCHEMA)
        with conn.cursor().copy("copy sales (cust, prod, day, month, year, state, quant, date) from stdin") as cp:
            for r in rows(n, seed):
                cp.write_row(r)
        conn.execute("analyze sales")
    return conn.execute("select count(*) from sales").fetchone()[0]
