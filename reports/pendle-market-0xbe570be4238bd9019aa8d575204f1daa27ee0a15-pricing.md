# Pendle MarketV3 定价研究报告（asdPENDLE / sdPENDLE，2026-03-26 到期）

> 研究对象：`0xbE570Be4238BD9019aA8D575204f1DAA27Ee0a15`（Ethereum mainnet）  
> 目标：理解定价公式，解释 UI 中 “1 asdPENDLE 能买到 ~21 YT” 的原因，并能复现计算（含卖出 YT 换回 asdPENDLE 的数值）。

---

## TL;DR（结论摘要）

- 该合约是 **Pendle `PendleMarketV3`（PT/SY AMM）**，不是 proxy；配套 `SY/PT/YT` 分别为：
  - `SY-asdPENDLE`：`0xc87d2d5a2117a495e0f04ef9304da603a86b7ad5`（proxy，implementation `0x73e39db05dc39bc1f94a0340dfd89563ed6c7b37`）
  - `PT-asdPENDLE-26MAR2026`：`0xab422a9b3767f4f1a2443882f5c0d1a01f30cde2`
  - `YT-asdPENDLE-26MAR2026`：`0xbf72d17a4be0eeffe1cbab96b5d64392fb1e6bea`
- `SY.exchangeRate()`（也即 `pyIndex`）给出 **SY ↔ asset（sdPENDLE）** 的换算：当前 `pyIndex ≈ 1.15909 sdPENDLE / SY`。
- Market 的核心定价是 **logit 曲线**：`exchangeRate(PT/asset) = ln(p/(1-p))/rateScalar + rateAnchor`，其中 `p = (totalPt - netPtToAccount)/(totalPt + totalAsset)`，并且 `rateScalar` 与到期时间 `T` 成反比。
- UI 的 “Buy YT” 并不是 `1 SY -> 1.159 YT` 的“铸造比例”，而是一个**合成/杠杆**动作：重复执行「用 SY mint PT+YT，然后卖 PT 换回 SY 再继续 mint」直到 SY 用尽；因此会出现 **`1 SY ≈ 21.x YT`** 这种“数量远大于 1”的结果。
- 你看到的 “-1.29%” 这种磨损，本质是：**YT 是很薄的“收益切片”（≈5%），手续费主要打在 PT 这条大额腿（≈95%），所以会被放大到 YT 口径上（约 17~18 倍）**。
- 复现示例（block `24054540`，timestamp `1766242487`）：
  - `21.38 YT` 卖出后可换回约 **`0.97375 asdPENDLE`**（小额 trade，price impact 基本可忽略）。

---

## 1. 合约与资产关系梳理

### 1.1 Market 合约（研究对象）

- 地址：`0xbE570Be4238BD9019aA8D575204f1DAA27Ee0a15`
- 类型：`PendleMarketV3`（已验证、非 proxy）
- 创建信息：
  - creator：`0x88883560ad02a31d299865b1fce0aaf350aaa553`
  - creation tx：`0xd316456dc3e9de698d23e7a46a95ab39152142a2880d55093af34a1eae5712da`
  - block：`23467977`（2025-09-29 10:13:11 UTC）
- 到期时间：`expiry = 1774483200`（2026-03-26 00:00:00 UTC）

### 1.2 交易对内的 Token（`readTokens()`）

- `SY`：`0xc87d2d5a2117a495e0f04ef9304da603a86b7ad5`，symbol `SY-asdPENDLE`
- `PT`：`0xab422a9b3767f4f1a2443882f5c0d1a01f30cde2`，symbol `PT-asdPENDLE-26MAR2026`
- `YT`：`0xbf72d17a4be0eeffe1cbab96b5d64392fb1e6bea`，symbol `YT-asdPENDLE-26MAR2026`
- decimals：三者均为 18

### 1.3 SY 的底层资产与可存取 Token

SY `assetInfo()`：
- `assetAddress = 0x5ea630e00d6ee438d3dea1556a110359acdc10a9`，symbol `sdPENDLE`
- `assetDecimals = 18`

SY `yieldToken()`（这里指 SY 的“底层收益/包装 token”）：
- `yieldToken = 0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`，symbol `asdPENDLE`

SY `getTokensIn()` 表明可用于 mint SY 的 token（本次抓到 3 个）：
- `0x808507121b80c02388fad14726482e061b8da827`（PENDLE）
- `0x5ea630e00d6ee438d3dea1556a110359acdc10a9`（sdPENDLE）
- `0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`（asdPENDLE）

实测（用于确认 `asdPENDLE ↔ SY` 是否 1:1）：
- `SY.previewDeposit(asdPENDLE, 1e18) = 1e18`  → `1 asdPENDLE` 可铸造 `1 SY`
- `SY.previewRedeem(asdPENDLE, 1e18) = 1e18`  → `1 SY` 可赎回 `1 asdPENDLE`

因此在你截图场景中，可以近似认为：**`asdPENDLE ≈ SY`（1:1）**。

---

## 2. 关键概念与单位（建模必读）

### 2.1 SY / asset / pyIndex

- Market 数学里常把 SY 统一换算为 `asset`（本池的 asset 是 `sdPENDLE`）。
- `pyIndex`（来自 `SY.exchangeRate()` 或 `YT.pyIndexCurrent()`）定义：
  - `asset = sy * pyIndex`
  - `sy = asset / pyIndex`
- 本次查询中 `pyIndex = 1.1590929262`，含义：`1 SY = 1.15909 sdPENDLE(asset)`

> 注意：Pendle 的 PT/YT 数量单位本质上是 “asset 口径” 的数量（见 `PendleYieldToken._calcPYToMint`：`amountPY = syToAsset(index, amountSy)`），所以 PT/YT 的“数量”不等于它们的“价值”。

### 2.2 PT / YT 的金融解释

- `PT`：到期能兑回 1 份 asset 本金的“本金票据”（折价交易）
- `YT`：到期前产生的收益权（只值“收益切片”，通常远小于 1）
- 直观关系（asset 口径）：
  - `PT_price_asset + YT_price_asset ≈ 1`
  - 在到期还很久、或收益率不高时：`PT_price_asset` 接近 1、`YT_price_asset` 很小

---

## 3. Market 核心定价公式（来自 `MarketMathCore.sol`）

> 代码位置（Etherscan 验证源码）：`contracts/pendle/contracts/core/Market/MarketMathCore.sol`

### 3.1 主要状态量

- `totalPt`：池子里 PT 储备（int，18 decimals）
- `totalSy`：池子里 SY 储备（int，18 decimals）
- `totalAsset = syToAsset(totalSy) = totalSy * pyIndex`
- `T = timeToExpiry = expiry - block.timestamp`

### 3.2 时间缩放（曲线随到期变“更陡/更平”）

`rateScalar = scalarRoot * 1year / T`

含义：离到期越近，`T` 越小，`rateScalar` 越大，价格曲线更“敏感”。

### 3.3 交易定价的核心：logit 曲线

先定义（这里用未缩放的 0~1 实数表示，合约内部是 1e18 fixed-point）：

- `p = (totalPt - netPtToAccount) / (totalPt + totalAsset)`
- `logit(p) = ln(p/(1-p))`

然后：

`exchangeRate(PT_per_asset) = logit(p)/rateScalar + rateAnchor`

其中 `rateAnchor` 由“上一笔交易保存的 implied rate”反推得到（确保曲线连续）：

- `exchangeRateFromImplied(lnImpliedRate) = exp( lnImpliedRate * T / 1year )`
- 令 `p0 = totalPt/(totalPt + totalAsset)`（即 `netPtToAccount=0` 的点）
- `rateAnchor = exchangeRateFromImplied(lastLnImpliedRate) - logit(p0)/rateScalar`

> 合约保证 `exchangeRate >= 1`（否则 revert），因此 `PT_price_asset = 1/exchangeRate <= 1`。

### 3.4 费率的处理（非常关键）

Market 会把 `lnFeeRateRoot` 转换为期限相关的乘数：

`feeFactor F = exp( lnFeeRateRoot * T / 1year )`

然后根据方向应用：

- **买 PT（SY -> PT）**：需要支付更多 asset，近似 `asset_in = preFeeAsset * F`
- **卖 PT（PT -> SY）**：收到更少 asset，近似 `asset_out = preFeeAsset / F`

此外，`reserveFeePercent` 表示手续费里有多少比例转入 treasury（本池为 80%），但对交易者而言，体现为同一个 `F` 的扣减。

### 3.5 Router 费率覆盖（解释“为什么我一开始算偏了”）

`PendleMarketV3.readState(router)` 会从工厂读取 market config：

`(treasury, overriddenFee, reserveFeePercent) = factory.getMarketConfig(market, router)`

如果 `overriddenFee != 0`，则使用 `overriddenFee` 覆盖默认 `lnFeeRateRoot`。

这意味着：**同一个 market，用不同 router 做报价，费率可能不同**。  
前端报价通常会使用 Pendle Router：`0x888888888889758f76e7103c6cbf23abbf58f946`。

---

## 4. 复现实验数据（本报告固定在一个区块上）

为便于复现，下面所有数值都以同一个 `latest` 读取时刻为准：

- block：`24054540`
- timestamp：`1766242487`（2025-12-20 14:54:47 UTC）
- `T ≈ 95.3786 days`

链上读数（`market.readState(router=0x8888...)`）：

- `totalPt ≈ 168324.7732`
- `totalSy ≈ 282260.1990`
- `scalarRoot ≈ 10.7165715974`
- `lastLnImpliedRate ≈ 0.2103754602`
- `lnFeeRateRoot ≈ 0.0028089610`
- `reserveFeePercent = 80`

指数（`SY.exchangeRate()`）：

- `pyIndex ≈ 1.1590929262 asset/SY`

从 implied rate 得到的现货点（`netPtToAccount=0`）：

- `E0 = exp(lastLnImpliedRate * T/1y) ≈ 1.05651260` （单位：PT/asset）
- `PT_price_asset = 1/E0 ≈ 0.94651025`
- `YT_price_asset(no-fee) = 1 - 1/E0 ≈ 0.05348975`
- `F = exp(lnFeeRateRoot * T/1y) ≈ 1.00073428`（约 0.0734%）

---

## 5. UI 中 “1 asdPENDLE -> 21.x YT” 的计算解释

### 5.1 为什么不是 `1 SY -> 1.159 YT`？

`PendleYieldToken.mintPY` 的确是：

- `1 SY` 只能直接 mint 出 `pyIndex ≈ 1.159` 数量的 `PT + YT`

但 UI 的 “Buy YT” 要的是**纯 YT**，它会把 `PT` 卖掉回收本金，再继续 mint，形成“杠杆循环”：

1. 用 `1 SY` mint 出 `1*pyIndex` 的 PT+YT
2. 卖掉 PT 换回一部分 SY（因为 PT 很值钱，接近 1 asset）
3. 用卖 PT 换回的 SY 继续 mint 更多 PT+YT
4. 重复直到 SY 用尽

这就是为什么 1 单位的 SY 可以累计 mint 出很多单位的 YT（本质是几何级数）。

### 5.2 小额近似下的闭式解（用于快速建模）

把上述循环放到 asset 口径：

- 每 1 asset mint 出 1 YT，同时卖出 1 PT
- 卖 1 PT 能回收的 asset 约为：`k = 1/(E0 * F)`

因此总共能 mint 的 YT（asset 口径）为：

`YT_total_asset = 1 + k + k^2 + ... = 1/(1-k)`

换回 SY 口径（因为 `1 SY = pyIndex asset`）：

`YT_per_SY ≈ pyIndex / (1 - 1/(E0*F))`

代入本报告区块参数：

- `k = 1/(E0*F) ≈ 0.9458`
- `YT_per_SY ≈ 21.39`

与截图中 `21.3791` 同量级且非常接近（差异主要来自区块时间不同、取整、以及极小的 price impact）。

---

## 6. 计算：卖出 `21.38 YT` 能换回多少 `asdPENDLE`？

> 这里的“Sell YT”是 UI 的合成路径：你只有 YT，没有 PT；要把 YT 变回 SY，需要买入等量 PT，然后把 `PT+YT` 一起 `redeemPY` 成 SY，再扣掉买 PT 的成本。

设卖出的 YT 数量为 `y`（单位：asset 口径的数量；`YT` 本身的数量单位就是这个口径）。

### 6.1 两步拆解

1) **redeem（需要 y PT + y YT）**  
`sy_redeem = y / pyIndex`

2) **用 SY 买 y PT（市场报价）**  
小额近似下（忽略 price impact），买 PT 需要的 SY：
`sy_in ≈ (y / E0) * F / pyIndex`

因此净拿回：

`sy_out = sy_redeem - sy_in ≈ y * (1 - F/E0) / pyIndex`

> 更精确做法是把 `E0` 替换为 trade-size 的 `E(y)`（用 `MarketMathCore` 的 `logit` 曲线计算），本报告也做了这一版，结果几乎一致。

### 6.2 代入数值（block 24054540）

取 `y = 21.38`：

- 计算得到：`sy_out ≈ 0.97374575 SY`
- 又因 `asdPENDLE ↔ SY` 在本 SY 内是 1:1：  
  **`asdPENDLE_out ≈ 0.97374575 asdPENDLE`**

如果用截图更精确的 `y = 21.3791`：
- `asdPENDLE_out ≈ 0.97370476`

---

## 7. “手续费率被杠杆放大”的定量解释

在本报告区块附近：

- `PT_price_asset ≈ 0.9465`
- `YT_price_asset ≈ 0.0535`（非常薄）
- `feePct ≈ F-1 ≈ 0.073%`

买/卖 YT 这种合成操作，手续费主要作用在“PT 腿”，折算到 YT 口径的相对影响近似：

`amplification ≈ PT_price_asset / YT_price_asset ≈ 0.9465 / 0.0535 ≈ 17.7x`

因此 YT 口径看到的磨损大约：

`effective_loss ≈ feePct * amplification ≈ 0.073% * 17.7 ≈ 1.29%`

这正是 UI 上常见的 `-1.29%` 量级来源（并不需要 price impact 很大也能出现）。

进一步，如果做一次“买 YT 再卖回”的往返，你会在两边都付出这类磨损，因此总往返损耗经常接近 `~2 * 1.29% ≈ 2.6%`（与上面的 `1 -> 0.9737` 的回吐非常一致）。

---

## 8. 复现指南（给下一位读者）

### 8.1 必须固定的输入

- market：`0xbE570Be4238BD9019aA8D575204f1DAA27Ee0a15`
- router（影响费率）：优先用 Pendle Router `0x888888888889758f76e7103c6cbf23abbf58f946`
- block/time：尽量固定 blockTag（否则 `T` 变化会影响报价）

### 8.2 需要的链上读取

1) `market.readTokens()` 得到 `SY/PT/YT`
2) `market.expiry()`
3) `SY.exchangeRate()`（或 `YT.pyIndexCurrent()`）得到 `pyIndex`
4) `market.readState(router)` 得到 `totalPt/totalSy/scalarRoot/lastLnImpliedRate/lnFeeRateRoot`
5) `block.timestamp`（可以用 `latest` block time）
6) 若要验证 `asdPENDLE ≈ SY`：`SY.previewDeposit(asdPENDLE, 1e18)`、`SY.previewRedeem(asdPENDLE, 1e18)`

### 8.3 计算骨架（建议直接实现成脚本/模型）

1) `T = expiry - now`
2) `E0 = exp(lastLnImpliedRate * T/1y)`
3) `F = exp(lnFeeRateRoot * T/1y)`
4) `YT_per_SY ≈ pyIndex / (1 - 1/(E0*F))`
5) 卖出 `y` YT：
   - `SY_out ≈ y * (1 - F/E0) / pyIndex`
   - 本 SY 内 `asdPENDLE_out ≈ SY_out`

> 对大额交易：请用 `MarketMathCore` 的 trade-size `E(y)`（logit 曲线）替代 `E0`，并按 `calcTrade` 的分支处理 fee（买 PT vs 卖 PT），否则误差会逐渐变大。

