with g as (select prod, month, avg(quant) a from sales group by prod, month),
     b as (select g.prod, g.month, p.a prev_a, n.a next_a
           from g left join g p on p.prod = g.prod and p.month = g.month - 1
                  left join g n on n.prod = g.prod and n.month = g.month + 1)
select b.prod, b.month,
       (select count(s.quant) from sales s
        where s.prod = b.prod and s.month = b.month and s.quant > b.prev_a and s.quant < b.next_a) as "3_count_quant"
from b order by b.prod, b.month
