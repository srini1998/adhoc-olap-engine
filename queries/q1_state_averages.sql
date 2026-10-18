with ny as (select cust, avg(quant) a from sales where state = 'NY' group by cust),
     nj as (select cust, avg(quant) a from sales where state = 'NJ' group by cust),
     ct as (select cust, avg(quant) a from sales where state = 'CT' group by cust)
select c.cust, ny.a as "1_avg_quant", nj.a as "2_avg_quant", ct.a as "3_avg_quant"
from (select distinct cust from sales) c
left join ny using (cust) left join nj using (cust) left join ct using (cust)
where ny.a > nj.a and ny.a > ct.a
order by c.cust
