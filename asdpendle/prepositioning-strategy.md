# asdPENDLE YT「提前持仓」方案（不依赖抢排序）

> 目标：在不做 mempool 抢排序/夹子、不依赖 bundle 的前提下，通过**提前持仓 YT-asdPENDLE**，尽可能吃到 `asdPENDLE.depositReward()` 导致的 `SY.exchangeRate()`（`pyIndex`）跳涨收益。  
> 研究对象与背景见：`asdpendle/report.md`、`reports/pendle-market-0xbe570be4238bd9019aa8d575204f1daa27ee0a15-pricing.md`。

---

## 0. TL;DR（结论先行）

- **核心机会**：`SdPendleBribeBurner.burn()` 会把 burner 内 `sdPENDLE` 按 `10% + 10% + 80%` 拆分，其中约 **80% 直接 `depositReward()` 注入 asdPENDLE**，不增发 share，只增 `totalAssets` ⇒ **asdPENDLE share price / `SY.exchangeRate()` 跳涨**（见 `asdpendle/report.md` 的机制解释）。
- **关键观察（可用于提前量）**：这类跳涨往往不是“突然天降”，其上游通常先发生 **Botmarket → MultiMerkleStash 的大额入金 + root/update**；在我们抽取的链上样本里，`update → claim → burn` 的时间结构非常稳定：  
  - `update → claim`：最早约 **16.1h**，中位约 **18.5h**，最晚约 **44.4h**  
  - `claim → burn`：通常 **12~60s**（几乎只剩 1~5 个区块）  
  这意味着：**想不抢排序还吃到跳涨，只能把“监控点”前移到 update**，提前若干小时建仓。
- **不抢排序版策略**：把 `update` 作为“周期开始”信号 → 在 `+12h~+16h` 之前完成主要建仓（更稳健可分批）→ 设置 **48h 超时风控**（若没等到 `burn/depositReward` 就减仓/平仓）→ 等到 `depositReward` 落地后再考虑卖出/兑现（不需要同块）。

---

## 1. 机制与对象梳理（你要吃的“跳涨”到底是什么）

### 1.1 合约与地址（mainnet）

- `sdPENDLE`（reward token / asset）：`0x5ea630e00d6ee438d3dea1556a110359acdc10a9`
- `asdPENDLE`（compounder / yieldToken）：`0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`（proxy）
- `SY-asdPENDLE`：`0xc87d2d5a2117a495e0f04ef9304da603a86b7ad5`（proxy）
- Pendle MarketV3（SY/PT AMM）：`0xbE570Be4238BD9019aA8D575204f1DAA27Ee0a15`
- `YT-asdPENDLE-26MAR2026`：`0xbf72d17a4be0eeffe1cbab96b5d64392fb1e6bea`

上游奖励分发与燃烧链路相关：

- `MultiMerkleStash`：`0x03e34b085c52985f6a5d27243f20c84bddc01db4`
- `Botmarket`（往 stash 打钱 + 更新 root 的资金归集/出金合约）：`0xadfbfd06633eb92fc9b58b3152fe92b0a24eb1ff`
- `SdPendleBribeBurner`：`0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2`
- 常见执行者（观察样本中多次出现）：`0x11e91bb6d1334585aa37d8f4fde3932c7960b938`
- 中转 proxy（claim 时常见的过桥地址之一）：`0x1c0d72a330f2768daf718def8a19bab019eead09`

### 1.2 为什么“持有 YT”能吃到这波

Pendle 的 YT 计息 index 取自 `SY.exchangeRate()`（即 `pyIndex`），并且在 YT 内部通过 `(currentIndex - prevIndex)` 结算利息（见 `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol` 与 `InterestManagerYT.sol` 的逻辑）。

因此：

- **你必须在跳涨发生前持有 YT**，才能在 index jump 时累积 interest；
- 如果你等到 `depositReward` 后才买 YT，`prevIndex` 会在你第一次参与时被设置为“当前 index”，你不会拿到这次跳涨的那一段。

---

## 2. 跳涨链路回放：update → claim → burn → depositReward

这一段是把 `asdpendle/report.md` 的“两步连击”进一步扩成“四段”并对应到可监控信号。

### 2.1 L0（领先信号）：Botmarket 给 Stash 入金（update/root 之前置动作）

链上可见表现（最容易监控的就是 `sdPENDLE` 的 ERC20 Transfer）：

- `sdPENDLE.Transfer(from=Botmarket,to=MultiMerkleStash,amount)`

这通常意味着“新一轮 Merkle 分发资金到位”（报告里称 update=0x9e/0xa0/…）。

> 监控意义：这是“不抢排序策略”的**主要触发点**，因为它领先后续 `claim/burn` 的时间足够长。

### 2.2 L1（确认信号，但对不抢排序帮助不大）：asdPENDLE.harvestBribe（claim）

典型执行方式是执行者调用 `asdPENDLE.harvestBribe(...)`，它内部会通过 `StakeDAOBribeClaimer.claim(...)` 从 `MultiMerkleStash` 把 `sdPENDLE` 领到 `bribeBurner`（见 asdPENDLE implementation `SdPendleCompounder.sol`）。

链上可见的强特征：

- tx `to = asdPENDLE(0x6064...)`，input selector = `0x417e3310`（`harvestBribe((address,uint256,uint256,bytes32[]))`）
- 或者直接看 token 流：`sdPENDLE` 会在同 tx 内从 `MultiMerkleStash` 转出，并最终进入 `SdPendleBribeBurner(0x8bde...)`（常见中转 `0x1c0d72...`）。

> 监控意义：这一步对“抢排序吃跳涨”很关键，但你如果不做抢排序，它基本只剩几十秒的预警价值。

### 2.3 L2（几乎紧随其后）：burner.burn（触发拆分 + depositReward）

`SdPendleBribeBurner.burn(ConvertParams)` 会将 burner 的 `sdPENDLE` 按固定比例拆分，其中约 80% 被用于 `asdPENDLE.depositReward()`。

链上特征：

- tx `to = burner(0x8bde...)`，input selector = `0x27084a41`（`burn((address,bytes,uint256))`）

### 2.4 L3（跳涨落地信号）：asdPENDLE.DepositReward / sdPENDLE→asdPENDLE 转账

你可以用两种方式确认“跳涨已发生”：

1) 监听 `asdPENDLE` 事件 `DepositReward(uint256)`（topic `0x19d619b1...`）  
2) 或监听 `sdPENDLE.Transfer(from=burner,to=asdPENDLE,amount)`

> 这一步发生后，Pendle Market 在后续 swap 会读取新的 `pyIndex` 进行定价；你如果没抢排序，已经无法“买在跳涨前”，只能做“跳涨后兑现/再平衡”。

---

## 3. 我们在链上样本里看到的“提前量”到底有多大

下面这些统计用于回答你关心的“有没有足够的反应时间”，并指导不抢排序的入场/超时风控。

### 3.1 样本口径

我从链上抽取了一个可复现的样本集合（不依赖 mempool）：

- L0：`sdPENDLE.Transfer(Botmarket → MultiMerkleStash)`（把它视为一次 update 周期的入金）
- L1：`sdPENDLE.Transfer(0x1c0d72... → burner)`（把它视为一次 claim 到 burner 的到达）
- L2/L3：`asdPENDLE.DepositReward` 且 tx `to=burner`（把它视为 burn 导致的“跳涨注入”）

在这个样本中，能形成“claim 后 5 分钟内跟随 burn”的 **紧连击事件**共有 9 次（覆盖 2025-07~2025-12，包含你报告里 12/03、12/10、12/18、12/24 四次）。

### 3.2 关键时间分布（结论：update 提供小时级提前量，claim 只提供秒级）

对这 9 次紧连击事件统计：

- `update → claim`
  - min：约 **16.1h**
  - p50：约 **18.5h**
  - max：约 **44.4h**
- `claim → burn`
  - min：**12s**
  - p50：**12s**
  - max：**60s**

**解释**：  
`claim → burn` 几乎就是“同一个执行者的连击”，给你的反应时间只有几个区块；所以如果你不做抢排序，真正可用的提前量只能来自 `update → claim` 这段小时级窗口。

### 3.3 金额关系（用于把“入金规模”转成“预计跳涨规模”）

在上述 9 次紧连击事件中，我们观察到两个非常稳定的关系：

1) `depositReward ≈ claim_amount * 80%`  
   - 这一点与你报告里“10% treasury + 10% booster + 80% 注入”的逻辑完全一致，并且在样本中几乎精确成立。

2) `claim_amount` 与 `update_inflow`（Botmarket→Stash）高度相关  
   - 在样本中，`corr(update_inflow, claim_amount) ≈ 0.997`（近似线性）。
   - `depositReward / update_inflow` 的经验比例（9 次样本）：
     - 中位约 **0.289**
     - 近期（你关心的 12 月四次）大约在 **0.29~0.30** 区间

> 用法：当你看到一次 `update_inflow`（例如 ~5330 `sdPENDLE`），你可以粗略估计这轮“最终注入 vault 的规模”大约是 `0.29 * update_inflow`（例如 ~1546 `sdPENDLE`），并进一步用 `depositReward / totalAssets` 去近似这次 `exchangeRate` 的百分比跳涨。

---

## 4. 不抢排序版「提前持仓」策略设计

### 4.1 触发条件：以 L0（update_inflow）作为主触发

当检测到：

- `sdPENDLE.Transfer(from=Botmarket,to=MultiMerkleStash,amount)` 且 `amount` 足够大

就认为进入“本周一次性跳涨事件的候选窗口”。

**阈值建议**（经验启发，不是定论）：

- 你可以用 `amount`（update_inflow）作为筛选：
  - 小额 update 往往对应小额 claim/注入，可能被 gas + 滑点轻易吃掉；
  - 大额 update 才值得做提前持仓。
- 更稳的做法：用 `predicted_depositReward ≈ 0.29 * update_inflow` 作为阈值（比如预计注入 < 300 `sdPENDLE` 就跳过）。

### 4.2 入场节奏：用“最早 16h”约束来避免错过

基于样本的最早 `update→claim ≈ 16.1h`：

- **主仓位建议在 update 后 +12h~+16h 之间分批完成**  
  - 这样你在绝大多数情况下能赶在 `claim/burn` 前完成持仓；
  - 同时避免从 update 刚发生就满仓持有（减少时间价值/价格波动暴露）。

如果你更保守（担心未来出现更早的 claim），可以把窗口整体前移（例如 +8h~+14h）。

### 4.3 持仓期间的监控：只需要“确认有没有进入 L1/L2/L3”

持仓期间主要监控：

- 是否出现 `harvestBribe`（L1）或 `sdPENDLE` 打入 burner（L1 的 token 侧特征）
- 是否出现 `burner.burn`（L2）
- 是否出现 `asdPENDLE.DepositReward`（L3）

其中 L3 是“跳涨已经实现”的落地信号。

### 4.4 超时风控：48 小时是一个直观的起点

样本里 `update→claim` 最晚约 44.4h，因此一个自然的风控是：

- **从 update 开始计时，超过 48h 还没看到 `depositReward`，则减仓/平仓**  
  - 理由：你做的不是长期持有 YT 的收益策略，而是为了一次“跳涨注入”；一旦错过窗口，持仓的机会成本与不确定性快速上升。

你也可以用更激进的 36h 或更保守的 60h；但如果你不想把策略变成长期持有，就需要一个明确的超时点。

### 4.5 兑现路径（不写死，取决于你的执行偏好）

跳涨落地后，你大概率会有两个选择：

- **卖出 YT**（把跳涨带来的增量体现在价格里兑现）  
- **不急卖，直接把 interest 累积/赎回**（视你对后续收益、滑点、流动性判断）

注意：如果你试图“同块买入→同块卖出/赎回”来做原子化锁利，会重新走向抢排序/MEV 范畴；本报告的方案刻意回避这一点。

---

## 5. 执行与监控清单（只用链上事件即可）

你不需要 mempool，也不需要理解全部 calldata；只要订阅事件流：

### 5.1 必要订阅（建议）

1) `sdPENDLE` 的 `Transfer`（topic `0xddf252ad...`）
   - 过滤 A：`from=Botmarket` 且 `to=MultiMerkleStash`（update_inflow）
   - 过滤 B：`to=burner`（claim 到 burner 的落点）
   - 过滤 C：`to=asdPENDLE` 且 `from=burner`（depositReward 的 token 侧确认）

2) `asdPENDLE` 的 `DepositReward(uint256)`（topic `0x19d619b1...`）
   - 这是 L3 “跳涨已落地”的最直接信号。

### 5.2 可选增强

- 订阅 `asdPENDLE.HarvestBribe(...)`（如果你要区分“bribe 注入” vs 其它来源的 depositReward）
- 订阅 `asdPENDLE.Harvest(...)`（与平滑小台阶相关，不是本策略主目标）

### 5.3 Reorg 处理

虽然以太坊主网深 reorg 罕见，但你用事件触发交易时，至少要做：

- 对关键触发事件（update_inflow、DepositReward）等待 N 确认（比如 2~5）再做重仓动作；
- 或者即使先做了，也要能在 reorg 时撤单/纠正状态（工程层面）。

---

## 6. 风险与失效模式（必须写清楚）

这类“可预测事件驱动”策略最常见的失效来自“行为改变”，而不是数学错了：

- **update 并不保证必然发生 claim/burn**：我们在样本里也看到“有 claim 但没有紧随 burn”的情况；更极端的情况是“本周根本没人来 claim”。所以必须有超时风控。
- **参数/权限可变**：`expenseRatio / boosterRatio`、bribeBurner 地址、claimer 逻辑等都可能被治理修改，从而破坏 `80%` 注入比例或时序。
- **执行者行为变化**：当前观察中 `0x11e91...` 很像自动化执行者；一旦它停机或改为 bundle 私有提交，你看到 `claim` 的时点/可见性都可能变化。
- **市场与滑点风险**：买/卖 YT 的价格影响可能显著（尤其你下单量大时）；并且“你提前持仓的这 16~48h”里，YT 本身会随利率/流动性波动。
- **gas 与机会成本**：小额 update 对应的小跳涨可能被 gas 吃掉；因此必须有“金额阈值”。

---

## 7. 附录：关键 selector / topic 速查

- `sdPENDLE.Transfer(address,address,uint256)` topic：`0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`
- `asdPENDLE.DepositReward(uint256)` topic：`0x19d619b124479c2d70fdcdb33644246ae36f947e11b9612f998df529be9e54b6`
- `asdPENDLE.harvestBribe((address,uint256,uint256,bytes32[]))` selector：`0x417e3310`
- `SdPendleBribeBurner.burn((address,bytes,uint256))` selector：`0x27084a41`

示例（与你报告一致）：

- 12/24 claim：`0x3ffae07496c1921b952d51dbdb9905946bdc69e79d9fc3b509634ac73b9ea866`  
- 12/24 burn + DepositReward：`0xedf67d107fd63918d605726c48817becbbc605692085333edaac6ad853d56d24`
