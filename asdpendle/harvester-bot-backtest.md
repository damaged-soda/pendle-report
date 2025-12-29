# asdPENDLE harvester bot：配置回测（7 天）

数据源：
- calls：`data/f88e_harvester_calls_7d.csv`
- harvest logs：`data/asdpendle_harvest_logs.csv`
- config：`data/f88e_harvester_bot_config_estimates.csv`
- prices：`data/coingecko_prices_7d.json`（sdPENDLE 已用链上 TWAP 填充）

窗口：
- start：`2025-12-20 18:05:47` (UTC+8)
- end：`2025-12-27 17:43:11` (UTC+8)

## 1) 使用的配置参数（asdPENDLE job）

- selector：`0x04117561`
- target：`0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`
- gas_used_p50：`879912`
- m_token_per_eth_p50：`3.00831e+06`
- k_token_per_wei_p50：`2.64724e-06`

## 2) 回放：minAssets ≈ k * gas_price（用配置 k 预测 tx 输入）

- asdPENDLE calls：64
- 可解析 minAssets 且可预测：64
- |pred-minAssets|（token）：p50≈2.473，p90≈5.551，max≈7.939
- |pred-minAssets|/minAssets（bps）：p50≈339，p90≈639，max≈1.19e+03

## 3) 触发回测（近似）：滚动估计 assets/sec + 扫描点=bot 每笔 tx 时间

定义：
- `expected(t)`：用历史 harvest 间隔估计的可 harvest `assets`（线性随时间增长）
- `threshold(t)`：用配置 `k` 与当下 `gas_price` 推出的 `minAssets`
- 认为当某个扫描点首次满足 `expected(t) >= threshold(t)` 时，bot 应该会触发 harvest。

- warmup_intervals：5（用窗口前的历史间隔初始化）
- rate_window：5（滚动中位数）
- intervals（按相邻 asdPENDLE harvest 划分）：62
- missed_intervals：28
- delay = actual_harvest_ts - first_trigger_ts（秒）：p50≈0，p90≈960，max≈7464

## 4) USD 口径（更贴近 bot 收益）：harvester_bounty vs 估算 gas cost

- bounty_rate=bounty/assets：p50≈0.001，p90≈0.001
- est tx_cost_usd：p50≈0.0691，p90≈0.08747
- harvest assets_usd：p50≈132.5，p90≈172.5
- harvester bounty_usd：p50≈0.1325，p90≈0.1725
- ROI_assets_usd=assets/cost：p50≈1905，p90≈2029
- ROI_bounty_usd=bounty/cost：p50≈1.905，p90≈2.029

## 5) 结论（这份配置“回测支持”的边界）

- ✅ 支持“回放型回测”：用 `k/m/gas_used` 预测 tx 的 `minAssets`，误差很小，说明配置可复现机器人出价逻辑。
- ⚠️ 触发时刻回测依赖 `expected(t)` 的估计：本脚本用“历史 assets/sec 线性增长”近似，能给出一个可对齐的触发延迟分布，但不是严格链上真值。
- 若要做严格回测（不靠线性假设），需要能在历史区块 `eth_call` 得到 `simulate_harvest()` 的 `expected assets`（或可替代的 view/preview）。
