-- 国別の上位 1% 資産シェア・所得シェアの観測カバレッジ（記述統計、H1 の適格性判定の元表）。
-- パラメータ（出現順に ? バインド）: 1) 前期の終了年（exclusive, 例 1990）, 2) 後期の開始年（例 2001）, 3) 窓の開始年（例 1950）
select iso3,
       count(top1_wealth_share)                                                 as n_wealth,
       min(case when top1_wealth_share is not null then year end)               as wealth_first_year,
       count(case when top1_wealth_share is not null and year < ? then 1 end)   as wealth_pre,
       count(case when top1_wealth_share is not null and year >= ? then 1 end)  as wealth_post,
       count(top1_income_share)                                                 as n_income,
       min(case when top1_income_share is not null then year end)               as income_first_year
from marts.wealth_population_panel
where year >= ?
group by iso3
order by iso3;
