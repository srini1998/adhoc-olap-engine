with g as (select cust, month, avg(quant) a from sales group by cust, month)
select g.cust, g.month, p.a as "1_avg_quant", g.a as "0_avg_quant", n.a as "2_avg_quant"
from g
left join g p on p.cust = g.cust and p.month = g.month - 1
left join g n on n.cust = g.cust and n.month = g.month + 1
order by g.cust, g.month
