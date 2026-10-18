select cust, prod,
       sum(quant) filter (where year = 2018) as "1_sum_quant",
       sum(quant) filter (where year = 2019) as "2_sum_quant"
from sales group by cust, prod
having sum(quant) filter (where year = 2019) > 1.2 * sum(quant) filter (where year = 2018)
    or not (count(quant) filter (where year = 2018) > 0)
order by cust, prod
