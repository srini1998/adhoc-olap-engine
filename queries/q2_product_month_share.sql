select prod, month,
       count(*) filter (where day <= 14) as "1_count_quant",
       count(quant) as "0_count_quant",
       sum(quant) as "0_sum_quant"
from sales group by prod, month order by prod, month
