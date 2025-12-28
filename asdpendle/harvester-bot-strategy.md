# harvester bot 策略推断（基于 7 天链上调用）

- 数据源：`data/f88e_harvester_calls_7d.csv`（937 笔 bot→harvester 调用）
- 时间窗口：`2025-12-20 18:05:47` → `2025-12-27 17:43:11` (UTC+8)
- run 聚类：gap>120s 断开，runs=658

## 1) 固定 job 列表（不是随机扫全网）

bot 在 7 天里只调用了 3 个 selector，对应 9 个 target：

- `0x04117561` `0x00bac667a4ccf9089ab1db978238c555c4349545`: 206 (aFXN)
- `0x04117561` `0xdec800c2b17c9673570fdf54450dc1bd79c8e359`: 160 (abcCVX)
- `0x04117561` `0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884`: 156 (aCRV)
- `0x04117561` `0xb0903ab70a7467ee5756074b31ac88aebb8fb777`: 106 (aCVX)
- `0x04117561` `0x43e54c2e7b3e294de3a155785f52ab49d87b9922`: 80 (asdCRV)
- `0xc7f884c6` `0x3cf54f3a1969be9916dad548f3c084331c4450b5`: 68 (AladdinCRVConvexVault (proxy))
- `0xc7f884c6` `0x59866ec5650e9ba00c51f6d681762b48b0ada3de`: 64 (ConcentratorGeneralVault / VaultForAsdCRV (proxy))
- `0x04117561` `0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`: 64 (asdPENDLE)
- `0x78f26f5b` `0x549716f858aeff9cb845d4c78c67a7599b0df240`: 33 (arUSD)

## 2) run/批处理特征（一次扫到多个就同一波全发）

- run_size：p50=1, p90=2, max=7
- 常见多笔 run 组合（按出现次数 Top 10）：
  - 24×: 0x04117561:aCRV, 0x04117561:abcCVX
  - 11×: 0x04117561:aFXN, 0x04117561:aCVX
  - 10×: 0x04117561:aFXN, 0x04117561:abcCVX
  - 8×: 0x04117561:asdCRV, 0x04117561:abcCVX
  - 7×: 0x04117561:aFXN, 0x04117561:aCRV
  - 7×: 0x04117561:aCRV, 0xc7f884c6:0x3cf5…50b5
  - 6×: 0x04117561:aCRV, 0x04117561:aCVX
  - 6×: 0x04117561:asdCRV, 0x04117561:asdPENDLE
  - 5×: 0x04117561:aFXN, 0x04117561:asdCRV
  - 5×: 0x04117561:aCRV, 0xc7f884c6:0x5986…a3de

- 最大批次（同一波发了所有常用 job）：
  - ts=1766391095 block=24066874 `0x04117561` asdCRV
  - ts=1766391095 block=24066874 `0x04117561` aCRV
  - ts=1766391095 block=24066874 `0x78f26f5b` arUSD
  - ts=1766391095 block=24066874 `0x04117561` aCVX
  - ts=1766391095 block=24066874 `0xc7f884c6` 0x3cf5…50b5
  - ts=1766391095 block=24066874 `0x04117561` abcCVX
  - ts=1766391095 block=24066874 `0x04117561` aFXN

## 3) 触发阈值：更像“expected_out 与交易成本线性绑定”

直接从 tx 参数看，minOut 与 `gas_price` 强相关，且 `minOut/gas_price` 波动很小。
但更底层的成本是 `tx_fee = gas_used * effectiveGasPrice`；当某个 job 的 `gas_used` 很稳定时，统计上就会呈现出 `minOut ~ gas_price*k` 这种“线性绑定”。

### 3.1 各 target 的拟合系数（用 p50(minAssets/gas_price) 近似 k_target）

| target | 7d次数 | minAssets(p50) | gas_price(p50) | k≈p50(minAssets/gas_price) | CV(k) | gap_s(p50) |
|---|---:|---:|---:|---:|---:|---:|
| aFXN | 206 | 0.6537 | 27468186 | 2.333e-08 | 0.074 | 2580 |
| abcCVX | 160 | 7.292 | 27238623 | 2.679e-07 | 0.033 | 3384 |
| aCRV | 156 | 55.92 | 27362572 | 2.071e-06 | 0.042 | 3456 |
| aCVX | 106 | 3.367 | 27191544 | 1.208e-07 | 0.043 | 5196 |
| asdCRV | 80 | 797.3 | 27168824 | 2.911e-05 | 0.036 | 6768 |
| asdPENDLE | 64 | 70.33 | 26473346 | 2.647e-06 | 0.044 | 8460 |

### 3.2 交易成本视角：minOut 与 tx_fee 线性绑定（更贴近 bot 决策）

- receipt sample：137 笔；effectiveGasPrice-tx_gas_price：p50=0, p90=0, max=0；mismatch=0
- 定义 `tx_fee = gas_used * effectiveGasPrice`（单位 wei）。在 sample 内 effectiveGasPrice==tx_gas_price，因此可把 `gas_price` 当作成本 proxy。
- 更关键的是：同一 job 的 `gas_used` 非常稳定，所以 `minOut ~ gas_price` 的现象更像来自 `minOut ~ tx_fee`。

- 注：`out/tx_fee` 的量纲是 `token_wei/wei`，等价于 `token/ETH`（这里默认这些 out 都是 18 decimals）。

| job | 7d次数 | sample | gas_used(p50) | CV(gas_used) | out/tx_fee(p50) | CV(out/tx_fee) |
|---|---:|---:|---:|---:|---:|---:|
| aFXN | 206 | 10 | 1151936 | 0.056 | 2.07e+04 | 0.024 |
| abcCVX | 160 | 10 | 1723428 | 0.022 | 1.55e+05 | 0.029 |
| aCRV | 156 | 10 | 1187096 | 0.036 | 1.717e+06 | 0.028 |
| aCVX | 106 | 9 | 842862 | 0.061 | 1.515e+05 | 0.028 |
| asdCRV | 80 | 10 | 1229470 | 0.003 | 2.296e+07 | 0.029 |
| asdPENDLE | 64 | 9 | 879912 | 0.012 | 3.008e+06 | 0.058 |
| ConcentratorGeneralVault(3) | 37 | 10 | 1229298 | 0.034 | 6.652e+05 | 0.023 |
| arUSD(base) | 33 | 10 | 2113891 | 0.028 | 170.7 | 0.017 |
| AladdinCRVConvexVault(50) | 31 | 10 | 1294800 | 0.078 | 8.473e+05 | 0.075 |
| AladdinCRVConvexVault(5) | 20 | 10 | 1265350 | 0.058 | 8.726e+05 | 0.076 |
| ConcentratorGeneralVault(9) | 12 | 7 | 1281917 | 0.033 | 6.523e+05 | 0.022 |
| AladdinCRVConvexVault(48) | 7 | 7 | 1286574 | 0.073 | 8.239e+05 | 0.093 |
| ConcentratorGeneralVault(7) | 7 | 7 | 1209288 | 0.033 | 6.557e+05 | 0.037 |
| ConcentratorGeneralVault(8) | 6 | 6 | 1273785 | 0.034 | 6.526e+05 | 0.035 |
| AladdinCRVConvexVault(37) | 4 | 4 | 1315404 | 0.083 | 8.109e+05 | 0.090 |
| AladdinCRVConvexVault(39) | 4 | 4 | 1283821 | 0.040 | 8.133e+05 | 0.042 |
| ConcentratorGeneralVault(14) | 1 | 1 | 1212860 | 0.000 | 6.775e+05 | 0.000 |
| AladdinCRVConvexVault(64) | 1 | 1 | 1208036 | 0.000 | 9.137e+05 | 0.000 |
| AladdinCRVConvexVault(3) | 1 | 1 | 1367773 | 0.000 | 7.876e+05 | 0.000 |
| ConcentratorGeneralVault(11) | 1 | 1 | 1186747 | 0.000 | 6.417e+05 | 0.000 |

### 3.3 USD 口径：是否存在跨 job 的统一 ROI 阈值？

- 定义 `ROI = yield_usd / tx_cost_usd`，其中 `yield_usd ≈ minOut * price_usd`，`tx_cost_usd ≈ (gas_price * gas_used_est) * ETH_usd`。
- 如果 bot 是“统一的 USD ROI 阈值”，则不同 job 的 `ROI(p50)` 应该接近；反之说明是 job-specific 的系数。

| job | 7d次数 | ROI(p50) | CV(ROI) | yield_usd(p50) | tx_cost_usd(p50) |
|---|---:|---:|---:|---:|---:|
| aFXN | 206 | 181 | 0.065 | 17.2 | 0.0942 |
| abcCVX | 160 | 92.8 | 0.031 | 13 | 0.14 |
| aCRV | 156 | 90.3 | 0.041 | 8.95 | 0.0965 |
| aCVX | 106 | 84.7 | 0.066 | 6.04 | 0.0678 |
| asdCRV | 80 | 1.85e+03 | 0.013 | 183 | 0.0987 |
| asdPENDLE | 64 | 1.9e+03 | 0.050 | 133 | 0.0691 |
| ConcentratorGeneralVault(3) | 37 | 36.3 | 0.058 | 3.46 | 0.095 |
| arUSD(base) | 33 | 185 | 0.029 | 30.6 | 0.163 |
| AladdinCRVConvexVault(50) | 31 | 45.4 | 0.040 | 4.61 | 0.0996 |
| AladdinCRVConvexVault(5) | 20 | 45.6 | 0.035 | 4.43 | 0.0952 |
| ConcentratorGeneralVault(9) | 12 | 35.5 | 0.053 | 3.32 | 0.0971 |
| AladdinCRVConvexVault(48) | 7 | 45.6 | 0.043 | 4.95 | 0.107 |
| ConcentratorGeneralVault(7) | 7 | 36.2 | 0.044 | 3.2 | 0.0893 |
| ConcentratorGeneralVault(8) | 6 | 35.4 | 0.063 | 3.34 | 0.0939 |
| AladdinCRVConvexVault(37) | 4 | 44.3 | 0.044 | 4.33 | 0.0963 |
| AladdinCRVConvexVault(39) | 4 | 44.6 | 0.035 | 4.21 | 0.0941 |
| ConcentratorGeneralVault(14) | 1 | 36.7 | 0.000 | 3.32 | 0.0905 |
| AladdinCRVConvexVault(64) | 1 | 49.6 | 0.000 | 4.11 | 0.0829 |
| AladdinCRVConvexVault(3) | 1 | 44.9 | 0.000 | 3.97 | 0.0884 |
| ConcentratorGeneralVault(11) | 1 | 34 | 0.000 | 2.94 | 0.0866 |

- 结论：`ROI(p50)` 跨 job 差异很大（min≈34 `ConcentratorGeneralVault(11)`, max≈1.9e+03 `asdPENDLE`, max/min≈56），更像每个 job 维护独立阈值系数，而非全局统一 ROI。

### 3.4 vault/fxUSD：也呈现“expected_out 与 gas_price 线性绑定”

对 vault 调用（`0xc7f884c6`），`minOut` 同样与 `gas_price` 强相关，且 `minOut/gas_price` 波动很小；这说明 bot 对 vault 也在用同一类阈值规则。

| vault(pid) | 7d次数 | minOut(p50) | gas_price(p50) | k≈p50(minOut/gas_price) | CV(k) | gap_s(p50) |
|---|---:|---:|---:|---:|---:|---:|
| ConcentratorGeneralVault(3) | 37 | 21.6 | 26102027 | 8.301e-07 | 0.042 | 15468 |
| AladdinCRVConvexVault(50) | 31 | 29.13 | 26167433 | 1.113e-06 | 0.040 | 18282 |
| AladdinCRVConvexVault(5) | 20 | 27.72 | 25523192 | 1.095e-06 | 0.046 | 30300 |
| ConcentratorGeneralVault(9) | 12 | 21.31 | 25796416 | 8.278e-07 | 0.031 | 50760 |
| AladdinCRVConvexVault(48) | 7 | 28.89 | 27981955 | 1.077e-06 | 0.039 | 84636 |
| ConcentratorGeneralVault(7) | 7 | 20.24 | 25090523 | 8.201e-07 | 0.039 | 86310 |
| ConcentratorGeneralVault(8) | 6 | 20.77 | 24884274 | 8.317e-07 | 0.031 | 109968 |
| AladdinCRVConvexVault(37) | 4 | 26.7 | 24900597 | 1.081e-06 | 0.045 | 147024 |
| AladdinCRVConvexVault(39) | 4 | 27.13 | 24771382 | 1.08e-06 | 0.044 | 142200 |
| ConcentratorGeneralVault(14) | 1 | 20.72 | 25217267 | 8.217e-07 | 0.000 | 0 |

- FxUSDCompounder（`0x78f26f5b`）观察：
  - target `arUSD`：minBaseOut 与 gas_price 强相关（k≈p50(minBaseOut/gas_price)=3.614e-10，CV=0.029）
  - minFxUSDOut 在 7 天内恒为 `1` wei（fx_unique=1），等价于“几乎不设阈值，只设 base_out 阈值”。
  - gap_s(p50)≈17628

### 3.5 asdPENDLE：minAssets≈Harvest.assets（先模拟再发 tx）

- 匹配到 63 笔同时有 Harvest 事件的 tx；其中 52 笔 `minAssets == assets`。
- |assets-minAssets|：p90≈0.009，max≈0.115。
- (assets-minAssets)/assets：p90≈1.35 bps，max≈16.50 bps（buffer 很小，符合“先模拟再发 tx”）。

## 4) 可复现的策略伪代码（推测）

```text
jobs = [
  # selector=0x04117561
  {type: 'compounder', target: aFXN,      gas_used: GU_aFXN,      m: m_aFXN},
  {type: 'compounder', target: aCRV,      gas_used: GU_aCRV,      m: m_aCRV},
  {type: 'compounder', target: aCVX,      gas_used: GU_aCVX,      m: m_aCVX},
  {type: 'compounder', target: abcCVX,    gas_used: GU_abcCVX,    m: m_abcCVX},
  {type: 'compounder', target: asdCRV,    gas_used: GU_asdCRV,    m: m_asdCRV},
  {type: 'compounder', target: asdPENDLE, gas_used: GU_asdPENDLE, m: m_asdPENDLE},
  # selector=0xc7f884c6
  {type: 'vault',      target: vault1, pid: X, gas_used: GU_vault1, m: m_vault1},
  {type: 'vault',      target: vault2, pid: Y, gas_used: GU_vault2, m: m_vault2},
  # selector=0x78f26f5b
  {type: 'fxusd',      target: arUSD, gas_used: GU_arUSD, m_base: m1, min_fxusd_out: 1},
]

loop:
  gp = current_gas_price()
  for job in jobs:
    expected = eth_call(simulate_harvest(job, min=0))
    fee_est = gp * job.gas_used             # ≈ tx_fee
    threshold = fee_est * (job.m_base if job.type=='fxusd' else job.m)
    if expected >= threshold:
       min = expected * (1 - buffer_bps)
       send_tx(harvest(job, min))
  sleep(...)   # 扫描频率链上不可见
```
