with g as (select distinct cust, year from sales),
     a as (select cust, avg(quant) a from sales group by cust)
select g.cust, g.year,
       (select count(quant) from sales s where s.cust = g.cust and s.year < g.year) as "1_count_quant",
       (select count(quant) from sales s join a on a.cust = s.cust
        where s.cust = g.cust and s.year = g.year and s.quant > a.a) as "3_count_quant"
from g order by g.cust, g.year
