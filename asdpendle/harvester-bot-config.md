# harvester bot 配置表（推测 / 7d 反推）

- calls：`data/f88e_harvester_calls_7d.csv`
- receipts sample：`data/f88e_harvester_receipts_sample.csv`（用于 gas_used 与 m_token_per_eth）
- prices：`data/coingecko_prices_7d.json`（USD 口径 ROI）
- 时间窗口：`2025-12-20 18:05:47` → `2025-12-27 17:43:11` (UTC+8)

## 说明（关键口径）

- `k_token_per_wei_p50`：p50(minOut/gas_price)，单位 `token/wei`（最贴近链上入参特征）。
- `m_token_per_eth_p50`：p50(minOut/tx_fee)，单位 `token/ETH`（tx_fee=gas_used*gas_price）。
- `roi_usd_p50`：p50(yield_usd/tx_cost_usd)，其中 yield_usd≈minOut*token_usd，tx_cost_usd≈tx_fee*ETH_usd。
- 注意：这里用 minOut 近似 expected_out（bot 可能会留少量 buffer），因此这些阈值偏保守。

## ROI 档位（p50）

- T4 (>=1000): asdPENDLE(1.9e+03), asdCRV(1.85e+03)
- T3 (150-1000): arUSD(base)(185), aFXN(181)
- T2 (70-150): abcCVX(92.8), aCRV(90.3), aCVX(84.7)
- T1 (<70): AladdinCRVConvexVault(64)(49.6), AladdinCRVConvexVault(48)(45.6), AladdinCRVConvexVault(5)(45.6), AladdinCRVConvexVault(50)(45.4), AladdinCRVConvexVault(3)(44.9), AladdinCRVConvexVault(39)(44.6), AladdinCRVConvexVault(37)(44.3), ConcentratorGeneralVault(14)(36.7), ConcentratorGeneralVault(3)(36.3), ConcentratorGeneralVault(7)(36.2), ConcentratorGeneralVault(9)(35.5), ConcentratorGeneralVault(8)(35.4), ConcentratorGeneralVault(11)(34)

## 配置表（按 7d 调用次数排序）

| job | type | selector | target | subkey | out_token | calls_7d | gap_s(p50) | gas_used(p50) | m_token/ETH(p50) | k_token/wei(p50) | ROI_usd(p50) | tier |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| aFXN | compounder | `0x04117561` | `0x00bac667a4ccf9089ab1db978238c555c4349545` |  | cvxFXN | 206 | 2580 | 1151936 | 2.07e+04 | 2.333e-08 | 180.9 | T3 (150-1000) |
| abcCVX | compounder | `0x04117561` | `0xdec800c2b17c9673570fdf54450dc1bd79c8e359` |  | CVX | 160 | 3384 | 1723428 | 1.55e+05 | 2.679e-07 | 92.83 | T2 (70-150) |
| aCRV | compounder | `0x04117561` | `0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884` |  | cvxCRV | 156 | 3456 | 1187096 | 1.717e+06 | 2.071e-06 | 90.3 | T2 (70-150) |
| aCVX | compounder | `0x04117561` | `0xb0903ab70a7467ee5756074b31ac88aebb8fb777` |  | CVX | 106 | 5196 | 842862 | 1.515e+05 | 1.208e-07 | 84.71 | T2 (70-150) |
| asdCRV | compounder | `0x04117561` | `0x43e54c2e7b3e294de3a155785f52ab49d87b9922` |  | sdCRV | 80 | 6768 | 1229470 | 2.296e+07 | 2.911e-05 | 1853 | T4 (>=1000) |
| asdPENDLE | compounder | `0x04117561` | `0x606462126e4bd5c4d153fe09967e4c46c9c7fecf` |  | sdPENDLE | 64 | 8460 | 879912 | 3.008e+06 | 2.647e-06 | 1902 | T4 (>=1000) |
| ConcentratorGeneralVault(3) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 3 | cvxCRV | 37 | 15468 | 1229298 | 6.652e+05 | 8.301e-07 | 36.34 | T1 (<70) |
| arUSD(base) | fxusd | `0x78f26f5b` | `0x549716f858aeff9cb845d4c78c67a7599b0df240` |  | weETH | 33 | 17628 | 2113891 | 170.7 | 3.614e-10 | 185.3 | T3 (150-1000) |
| AladdinCRVConvexVault(50) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 50 | cvxCRV | 31 | 18282 | 1294800 | 8.473e+05 | 1.113e-06 | 45.39 | T1 (<70) |
| AladdinCRVConvexVault(5) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 5 | cvxCRV | 20 | 30300 | 1265350 | 8.726e+05 | 1.095e-06 | 45.6 | T1 (<70) |
| ConcentratorGeneralVault(9) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 9 | cvxCRV | 12 | 50760 | 1281917 | 6.523e+05 | 8.278e-07 | 35.47 | T1 (<70) |
| AladdinCRVConvexVault(48) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 48 | cvxCRV | 7 | 84636 | 1286574 | 8.239e+05 | 1.077e-06 | 45.64 | T1 (<70) |
| ConcentratorGeneralVault(7) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 7 | cvxCRV | 7 | 86310 | 1209288 | 6.557e+05 | 8.201e-07 | 36.17 | T1 (<70) |
| ConcentratorGeneralVault(8) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 8 | cvxCRV | 6 | 109968 | 1273785 | 6.526e+05 | 8.317e-07 | 35.41 | T1 (<70) |
| AladdinCRVConvexVault(37) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 37 | cvxCRV | 4 | 147024 | 1315404 | 8.109e+05 | 1.081e-06 | 44.34 | T1 (<70) |
| AladdinCRVConvexVault(39) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 39 | cvxCRV | 4 | 142200 | 1283821 | 8.133e+05 | 1.08e-06 | 44.58 | T1 (<70) |
| ConcentratorGeneralVault(14) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 14 | cvxCRV | 1 | 0 | 1212860 | 6.775e+05 | 8.217e-07 | 36.69 | T1 (<70) |
| AladdinCRVConvexVault(64) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 64 | cvxCRV | 1 | 0 | 1208036 | 9.137e+05 | 1.104e-06 | 49.56 | T1 (<70) |
| AladdinCRVConvexVault(3) | vault | `0xc7f884c6` | `0x3cf54f3a1969be9916dad548f3c084331c4450b5` | 3 | cvxCRV | 1 | 0 | 1367773 | 7.876e+05 | 1.077e-06 | 44.95 | T1 (<70) |
| ConcentratorGeneralVault(11) | vault | `0xc7f884c6` | `0x59866ec5650e9ba00c51f6d681762b48b0ada3de` | 11 | cvxCRV | 1 | 0 | 1186747 | 6.417e+05 | 7.615e-07 | 33.98 | T1 (<70) |
