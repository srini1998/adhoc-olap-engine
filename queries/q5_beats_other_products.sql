with g as (select prod, avg(quant) a from sales group by prod)
select g.prod, g.a as "0_avg_quant",
       (select count(s.quant) from sales s where s.prod <> g.prod and s.quant > g.a) as "1_count_quant"
from g order by g.prod
