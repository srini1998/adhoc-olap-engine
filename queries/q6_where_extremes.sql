select cust, state, min(quant) as "0_min_quant", max(quant) as "0_max_quant",
       max(quant) filter (where month = 12) as "1_max_quant"
from sales where year = 2020 group by cust, state order by cust, state
