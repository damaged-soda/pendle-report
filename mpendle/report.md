# mPENDLE（SY-mPendle）生息逻辑 / 总资产变大事件 / 未领取收益增长机制（Arbitrum）

> 时区：北京时间（UTC+8）  
> 研究对象：
> - `SY-mPendle`：`0x5c4110ed760470f79e469a901bd6fb45a65be0f4`（non-proxy, Arbitrum One）
> - `Pendle`：`0x0c880f6761f1af8d9aa9c466984b80dab9a8c9e8`
> - `mPendle`：`0xb688ba096b7bb75d7841e47163cd12d18b36a5bf`
> - `PNP`：`0x2ac2b254bc18cd4999f64773a966e4f4869c34ee`
> - `mPendleReceiptToken (mPendle_PRT)`：`0x2b5fa2c7cb4b0f51ea7250f66ca3ed369253addf`
> - `MasterPenpie`（proxy）：`0x0776c06907ce6ff3d9dbf84ba9b3422d7225942d`
> - `mPendle Penpie Rewarder`（StreamRewarder, proxy）：`0x2c1299ddf74b219493c762caf0d0bde5a366dfc6`
> - `SmartPendleConvertor`（proxy）：`0xa9dd725ba2eaacdb7a30d17597b7d8c3fd2f80ed`

---

## TL;DR

- `SY-mPendle.exchangeRate()` 的本质是「SY 持有的总资产 / SY 的总份额」。
- 这份“总资产”由两部分构成：
  1) `MasterPenpie` 里 `SY` 的 `mPendle` 质押仓位（通过 `mPendle_PRT` 表示）；  
  2) `SY` 尚未领取的 `PENDLE`（从 `rewarder` 线性流出），并用 `SmartPendleConvertor` 估算成 `mPendle` 价值后计入。
- “未领取收益变大”不是每秒真的有人给你打钱；它来自 `rewarder` 的**时间流式记账**：先有人一次性 `RewardQueued`（打钱进 rewarder），然后在接下来约 7 天按时间线性释放，`pending/earned` 随时间上升，直到被 `multiclaim` 领取。
- 你看到 `11/24~11/25` “发了很多收益”，对应链上是 `2025-11-24 19:29:56` 的一笔 `RewardQueued 37289 PENDLE`（tx `0xf40ab54c7a76c58068f3578c6f07f9a5139f76fff380f2545ab0b36add21c4e6`），之后收益开始流式释放。
- `exchangeRate` 不会因为 `RewardQueued` 立刻“大跳涨”；能让“总资产”瞬间变大的，通常是 **实际把 `PENDLE` 领取并复投成 `mPendle`（或有人直接把仓位/receipt token 打给 SY）** 的那笔交易。

---

## 1. exchangeRate / 总资产的定义（合约层面）

`MPendleSY.sol` 的核心定义很直接：

- `exchangeRate() = getTotalAssetOwned() * 1e18 / totalSupply()`
- `getTotalAssetOwned()`：
  - 读取 `MasterPenpie.stakingInfo(mPendle, SY)` 得到 `SY` 的 `stakedAmount`（可理解为 SY 已质押的 `mPendle` 仓位规模）
  - 再读取 `MasterPenpie.pendingTokens(mPendle, SY, Pendle)` 得到 `unclaimed PENDLE`
  - 若有 `unclaimed PENDLE`，则用 `previewPendleTomPendleConvert(unclaimed)` 折算成 `mPendle` 价值，**加到 totalAssetOwned**

因此：哪怕 SY 还没真正把 PENDLE 领出来，只要 `pendingTokens` 变大，`getTotalAssetOwned()` 也会“看起来在涨”。

---

## 2. 总资产变大的“事件”是什么（链上发生了什么）

要让 `getTotalAssetOwned()` 变大，本质上是下面两类事件之一：

### 2.1 复投导致仓位增加（最常见）

SY 会在 `deposit/redeem/claimRewards/harvestAndCompound()` 内部调用 `_harvestAndCompound()`：

1) `MasterPenpie.pendingTokens(...)` 看当前是否有 `PNP` 或 `PENDLE` 可领  
2) `MasterPenpie.multiclaim([mPendle])` 把 `PNP + PENDLE` 真正转到 SY 合约  
3) 将拿到的 `PENDLE` 调用 `SmartPendleConvertor.smartConvert(amount, STAKEMODE=1)`：
   - 把 `PENDLE → mPendle`（含 buyback/swap 路径），并**stake 回 MasterPenpie**

这类交易会在 `MasterPenpie` 上看到 `Deposit(_user=SY, _stakingToken=mPendle, _receiptToken=mPendle_PRT, _amount=...)`，代表 SY 仓位增加（也就是“总资产变大”的落地动作）。

### 2.2 rewarder 打钱（只改变“未领取”，不直接改变仓位）

你关心的“总有地方打钱过来吧”，对应的是 rewarder 收到资金并触发 `RewardQueued(rewardToken, rewardAmount)`：

- `RewardQueued` 的资金 **转进的是 rewarder 合约**，不是 SY
- 之后 rewarder 再在 `duration≈7天` 的窗口里按时间线性释放
- 所以你看到的“pending 增加”，更像是**记账在变大**，直到有人触发 `multiclaim` 才真正把 token 转给 SY（或你的地址）

---

## 3. “未领取收益变大”的原理（为什么不是每秒都有人转账）

mPendle 这池的 bonus 奖励（PENDLE）来自一个 `StreamRewarder`（地址见上）。它的典型机制是：

1) 有人一次性调用 `queueNewRewards(...)` / `donateRewards(...)` 把 `PENDLE` 转进 rewarder（你在链上看到的“打钱”）
2) rewarder 设置 `rewardRate = rewardAmount / duration`  
3) `earned(account)` 通过 `rewardPerToken` 和 `lastUpdateTime` 按 `block.timestamp` **线性累积**

所以：**pending 是随时间增长的变量**，并不需要每秒有 ERC20 Transfer 发生。

---

## 4. 11/24 18:00 ～ 11/25 18:00（北京）发生了什么

### 4.1 关键“打钱”事件：RewardQueued 37289 PENDLE

- 时间：`2025-11-24 19:29:56`（北京）
- tx：`0xf40ab54c7a76c58068f3578c6f07f9a5139f76fff380f2545ab0b36add21c4e6`
- 行为：向 `mPendle rewarder 0x2c1299...` `RewardQueued 37289 PENDLE`

这会把后续一段时间的 `rewardRate` 拉高，因此你看到 `mpendle` “开始发很多收益”。

### 4.2 关键“复投/落地”事件：SY.harvestAndCompound() 把收益变成仓位

下面是一笔落在该时间窗内、可直接观察到“领取→换仓→再质押”的复投交易：

- 时间：`2025-11-25 01:00:40`（北京）
- tx：`0x4c2799fd91501fe8674973616e0568d6e1cc74c624e58f89c0b498b472cfb7c5`
- 结果（同 tx 内）：
  - `PENDLE` 从 rewarder 转给 `SY`：`15.095590689 PENDLE`
  - `PNP` 从 MasterPenpie 转给 `SY`：`0.706425359 PNP`
  - `SY` 把 `15.095590689 PENDLE` 通过 convertor 复投，新增质押：`23.242795834 mPendle`（`MasterPenpie.Deposit`，并 mint `mPendle_PRT` 给 SY）

直观理解：  
`RewardQueued` 让 pending 的“速度”变快；而 `harvestAndCompound`/`deposit` 才是把 pending 变成“总资产（仓位）”的落地动作。

---

## 5. 近 30 天内的“打钱/跳变”时间点（RewardQueued）

> 这些是 rewarder 收到资金的时点：资金进入 rewarder，后续线性释放；不等于 exchangeRate 当场大跳。

- `2025-11-30 12:00:42`：`1833.314342 PENDLE`（tx `0xd7c36f7ec9b695f80627f4f12a8667dc3443c6ddb6b055d72526bd653f949996`）
- `2025-11-30 15:51:10`：`37137 PENDLE`（tx `0xc45112f2153d31b0f483785b639d7bc2d73b4c786192b7fc90b7444ac299208b`）
- `2025-12-07 12:00:42`：`1601.835706 PENDLE`（tx `0xf04cce9afd4cbd3310e952f54b4c21b8cd90e147844214a848d5c2f476695b0e`）
- `2025-12-07 13:13:50`：`37137 PENDLE`（tx `0x48b6d4bbe4c7ed03c143329628efeffd9b922926eb2154b02f40641555db95eb`）
- `2025-12-14 12:00:42`：`1815.100979 PENDLE`（tx `0xcf52c90b694e000a011eec41680f23613695a796b73bc4b5dabe7f1f91810b19`）
- `2025-12-14 16:17:10`：`37137 PENDLE`（tx `0x9a6b03db618cfd56c1fa14486db517c1e88f055c0922606791fb34cd1a6dbff9`）
- `2025-12-21 12:00:42`：`1536.626065 PENDLE`（tx `0x56651687c1555488de1036c8a97cf4def2388a7f337c3528074473196039d096`）
- `2025-12-21 21:03:18`：`14794 PENDLE`（tx `0x187e2eb64fa2ff8ee5dfa91805f56a0b071f0dd8b0ffb74b341da9085338bea9`）
- `2025-12-28 12:00:42`：`1434.227100 PENDLE`（tx `0xf6ec04ad2df5f6eeb10a8199925d1cf1c853246f094836deba3967132f761840`）
- `2025-12-28 21:24:43`：`14794 PENDLE`（tx `0x6a218838c7f90ffc7e6d7a8ece2fefa05d5eeca41fe3fa2e7db2b9eb449b7e83`）

---

## 6. 近 30 天内的“总资产落地增加”（复投）示例时间点（harvestAndCompound）

> 这些交易会把已累积的 `pending PENDLE` 真的领出来，并复投成 `mPendle` 仓位；如果 `totalSupply(SY)` 不变，它才会在该时点推动 `exchangeRate` 上移。

- `2025-11-29 01:00:40`（北京）：tx `0x8ebf8c661a51d06aa6613b2bd3200e858c45e3ab642c4368af287f3647f6d7a2`  
  - 领取并复投：`36.500799354 PENDLE → 57.347403603 mPendle`；同时领取 `1.708121501 PNP`
- `2025-11-30 01:00:40`（北京）：tx `0x211aa9902c0b78d75cd5e7e774ec4a37c71058df3a6feff69e9ecd8ccc584432`  
  - 领取并复投：`40.615134157 PENDLE → 65.540026064 mPendle`；同时领取 `1.900654096 PNP`
- `2025-12-27 01:00:40`（北京）：tx `0xa3fe450708222c5592ee26b310db7bc416c7a18163c6783222f27e469b2591d0`  
  - 领取并复投：`0.360740333 PENDLE → 0.626588924 mPendle`；同时领取 `0.038072791 PNP`
- `2025-12-28 01:00:40`（北京）：tx `0x79c8fb7189338c5a76d1d1e452ae14d2e80a355e4963e1d6e05c9aabb0acc7d0`  
  - 领取并复投：`13.173985512 PENDLE → 23.052373343 mPendle`；同时领取 `1.390404806 PNP`

---

## 7. 关于“会不会突然跳涨很大幅度”的结论（如何排除你说的 asset 注资型跳变）

### 7.1 结论（针对你说的“打一大笔钱让资产瞬间变大”）

- **rewarder 确实会“一次性打钱”**（`RewardQueued`），但这是打进 rewarder，并在后续按时间流式释放；它更像改变“收益斜率”，不是直接把 SY 的仓位瞬间抬高。
- 真正能让 `SY` 的“总资产（仓位）”瞬间变大的，是“复投/注资落地”类交易（`MasterPenpie.Deposit` 给到 `_user=SY`），它可能来自：
  - 正常路径：`harvestAndCompound` / `deposit` 触发的 `_harvestAndCompound`（把 accrued 的 PENDLE 一次性复投）
  - 极端路径：第三方直接把 `mPendle_PRT`/仓位转给 `SY`（不 mint SY 份额），这会造成你说的那种“asset/supply 结构性跳变”

### 7.2 如何继续“排除”外部注资（建议的审计办法）

- 盯 `MasterPenpie.Deposit(_user=SY, _stakingToken=mPendle, ...)` 的交易：
  - 若同一笔 tx 内 **没有** `SY` 自身 ERC20 `Transfer(0x0 → user)`（mint 份额），但 `Deposit` 给了 SY 很大 `_amount`，就更像“外部注资/捐赠式抬升”。
  - 若 `Deposit` 同时伴随 `SY` 的 `Deposit` 事件/份额 mint，通常只是用户正常申购。

