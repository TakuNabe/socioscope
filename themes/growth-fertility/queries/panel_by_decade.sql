-- 所得水準 × TFR の年代別要約（記述統計）。パラメータ: ? = 開始年
select (year / 10) * 10 as decade,
       count(*)                                  as n,
       quantile_cont(gdp_pcap_ppp, 0.5)           as median_gdp_pcap_ppp,
       quantile_cont(tfr, 0.5)                    as median_tfr,
       corr(ln(gdp_pcap_ppp), tfr)                as corr_log_gdp_tfr
from marts.growth_fertility_panel
where year >= ? and tfr is not null and gdp_pcap_ppp is not null
group by decade
order by decade;
