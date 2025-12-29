# Pendle YT（Yield Token）结算机制：`exchangeRate` 如何被读取、记录、结算（代码级）

> 读者定位：已经知道 Pendle 的 SY/PT/YT 概念，但想从合约实现确认 “YT 到底怎么结算” 的人  
> 目标：把 **`exchangeRate()` 在哪里被读取、上涨如何被使用、用户快照如何记录与结算、卖出是否丢收益、到期后如何处理** 一次讲清楚  
> 代码版本：`pendle-core-v2-public`（YT `VERSION = 6`，见 `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:38`）

---

## 0. 先把单位钉死：SY / asset / PY（PT,YT）

### 0.1 `exchangeRate` 的定义（SY ↔ asset）

SY 合约接口定义了：

- `exchangeRate * syBalance / 1e18 = assetBalance`
- 反向：`assetAmount / exchangeRate * 1e18 = syAmount`

见 `pendle-core-v2-public/contracts/interfaces/IStandardizedYield.sol:93` 到 `pendle-core-v2-public/contracts/interfaces/IStandardizedYield.sol:100`。

对应换算函数在：

- `syToAsset(exchangeRate, syAmount)`：`pendle-core-v2-public/contracts/core/StandardizedYield/SYUtils.sol:7`
- `assetToSy(exchangeRate, assetAmount)`：`pendle-core-v2-public/contracts/core/StandardizedYield/SYUtils.sol:15`

### 0.2 PT/YT 的“数量单位”是 asset 口径（不是 SY 口径）

YT 合约铸造 PT/YT 时，会把你转进来的 `SY`（份额）按当下指数换算成 `asset` 数量，再按 asset 数量 mint 出等量的 PT 与 YT：

- `_calcPYToMint(amountSy, index) = syToAsset(index, amountSy)`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:348`

因此后文提到的：

- `principal`（用户 YT 余额）是 **asset 口径数量**
- `interest`（用户可领利息）是 **SY 口径数量（SY 份额）**

---

## 1. YT 里与“结算”直接相关的状态（你要盯着哪些变量）

### 1.1 全局利息指数：PY index（本质上来自 `SY.exchangeRate()`）

YT 合约存了一个 “PY index” 的缓存与更新时间：

- `doCacheIndexSameBlock`：同一 block 是否缓存指数（最多更新一次）：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:45`
- `pyIndexLastUpdatedBlock` / `_pyIndexStored`：缓存的指数与更新时间：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:49`

外部可调用：

- `pyIndexCurrent()`：会更新并返回当前指数：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:243`
- `pyIndexStored()`：只读缓存值：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:248`

### 1.2 用户利息快照：`userInterest[user] = {index, accrued}`

利息相关状态在 `InterestManagerYT`：

- `userInterest[user].index`：上次结算时的快照指数
- `userInterest[user].accrued`：已累计但尚未转出的利息（SY 份额）

见 `pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:26` 到 `pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:31`。

### 1.3 用户奖励快照：`userReward[token][user] = {index, accrued}`

奖励相关状态在 `RewardManagerAbstract`：

- `userReward[token][user].index`：上次结算时该 reward token 的快照 index
- `userReward[token][user].accrued`：已累计但尚未转出的 reward token 数量

见 `pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:28` 到 `pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:29`。

---

## 2. `exchangeRate()` 到底在哪里被读取？——只在 `_pyIndexCurrent()`

### 2.1 `_pyIndexCurrent()`：读 `SY.exchangeRate()`，并把它变成“单调不减”的 PY index

核心代码：

- 读取：`IStandardizedYield(SY).exchangeRate()`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:406`
- 单调不减：`max(exchangeRate, _pyIndexStored)`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:406`
- 同 block 缓存：如果 `doCacheIndexSameBlock` 且本 block 已更新过，直接返回缓存：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:404`

结论：

- **YT 的利息指数 = SY 的 `exchangeRate()`（但被缓存/强制单调不减）**
- “指数更新”不是持续发生的；只有在合约执行到 `_pyIndexCurrent()` 时才会读取并（可能）更新缓存。

### 2.2 什么时候会走到 `_pyIndexCurrent()`？

至少以下路径会触发（直接或间接）：

- `pyIndexCurrent()` 外部调用：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:243`
- `mintPY`/`redeemPY` 内部会拿一次 `index = _pyIndexCurrent()`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:307`，`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:331`
- **任何 YT 的 `transfer/mint/burn`**：都会先走 `_beforeTokenTransfer`，其中会结算利息（会读指数）：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:505`

---

## 3. YT 的“利息”（interest，以 SY 支付）是怎么结算的？

### 3.1 结算触发点：所有余额变动都先结算（lazy，但不丢）

YT 是一个改造过的 ERC20（`PendleERC20`），其 `_transfer/_mint/_burn` 在改余额前会调用 `_beforeTokenTransfer`：`pendle-core-v2-public/contracts/core/erc20/PendleERC20.sol:195`，`pendle-core-v2-public/contracts/core/erc20/PendleERC20.sol:222`，`pendle-core-v2-public/contracts/core/erc20/PendleERC20.sol:245`。

YT 自己重写了 `_beforeTokenTransfer`，并在其中：

1) 结算 rewards：`_updateAndDistributeRewardsForTwo(from, to)`  
2) 结算 interest：`_distributeInterestForTwo(from, to)`

见 `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:505` 到 `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:508`。

这个顺序的含义（先记下来，后面会用）：

- 任何一次 “卖出/转出 YT” 都会在**扣你余额之前**先把你这段期间应得的利息累计到 `userInterest[msg.sender].accrued`。
- 这就是 “结算是 lazy 的，但历史收益不会因为你卖出而丢失” 的代码根源（除非你遇到同 block 缓存导致的 1-block 边界效应，见 §6.2）。

### 3.2 利息结算公式：只看 “当前指数 - 你的快照指数”

利息结算核心在 `InterestManagerYT._distributeInterestPrivate`：

- `prevIndex = userInterest[user].index`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:66`
- `principal = _YTbalance(user)`（即 `balanceOf(user)`）：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:74` + `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:415`
- 结算：  
  `interestFromYT = principal * (currentIndex - prevIndex) / (prevIndex * currentIndex)`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:76`
- 写入：`userInterest[user].accrued += interestFromYT` 并更新 `userInterest[user].index = currentIndex`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:78`

**非常关键的一行：第一次见到你时只会写快照，不会给历史利息**

- `if (prevIndex == 0) { userInterest[user].index = currentIndex; return; }`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:69`

这就意味着：

- 你刚买入 YT（或第一次持有）时，快照被设置为“买入时刻的指数”，不会凭空拿到过去上涨带来的利息。

### 3.3 公式直觉：它等价于“同一份 YT 本金在两个指数下需要的 SY 份额差”

把 `assetToSy(index, principal)` 理解为 “用多少 SY 份额才能对应这份 YT 本金（asset 口径）”。

当指数从 `prevIndex` 上升到 `currentIndex`，同样 `principal` 需要的 SY 份额变少；变少的那部分就是用户可领取的利息（SY 份额）。

因此（忽略 rounding）：

- `interestFromYT ≈ assetToSy(prevIndex, principal) - assetToSy(currentIndex, principal)`

其中 `assetToSy` 见 `pendle-core-v2-public/contracts/core/StandardizedYield/SYUtils.sol:15`。

### 3.4 你什么时候真正拿到 SY？——`redeemDueInterestAndRewards`

利息真正转出发生在：

1) `_distributeInterest(user)`（先把指数差结算进 `accrued`）  
2) `_doTransferOutInterest(user, SY, factory)`（把 `accrued` 清零并转出，扣手续费）

见：

- `PendleYieldToken.redeemDueInterestAndRewards`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:168`
- `_doTransferOutInterest`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:43`

---

## 4. YT 的“奖励”（reward tokens）怎么结算？它和 `exchangeRate` 的关系是什么？

### 4.1 reward index 来自 SY：`rewardIndexesCurrent()`

YT 通过 SY 拉取 reward index（通常会在 SY 内部做一次 “更新/累计”）：

- `indexes = IStandardizedYield(SY).rewardIndexesCurrent()`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:500`

YT 也暴露了一个同名函数透传给外部用来触发更新：

- `PendleYieldToken.rewardIndexesCurrent()`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:231`

### 4.2 reward 分配公式：`userShares * (index - userIndex)`

`RewardManagerAbstract` 的分配公式：

- `userShares = _rewardSharesUser(user)`：`pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:48`
- `rewardDelta = userShares.mulDown(deltaIndex)`：`pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:61`
- 写入 `userReward[token][user] = {index, accrued}`：`pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:65`

这是一套非常标准的 “全局 index + 用户 index 快照” 模型。

### 4.3 `_rewardSharesUser` 为什么要用 `userInterest.index` 和 `userInterest.accrued`？

YT 的实现：

- `rewardSharesUser = assetToSy(userInterest[user].index, balanceOf(user)) + userInterest[user].accrued`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:486`

直觉上它返回的是：

- **“用户这份 YT 对应的、用于生成 reward 的 SY 份额总量”**

更关键的是：这个量在理论上应当随时间保持不变（只要你不把利息取走、不做 PY redeem），Pendle 也在代码注释里明确写了这一点，并要求**必须先更新 rewards 再转出 interest**：

- 注释与顺序：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:162` 到 `pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:190`

因此 reward 的结算逻辑是：

- 你可以把 reward 当成 “按你锁定的 SY 份额份额分配的外部奖励”
- `exchangeRate` 上升会改变 “本金需要的 SY 份额”，但这部分变化会被 “利息 accrued 的增加” 抵消，使得 `assetToSy(snapshotIndex, balance) + accrued` 保持不变（这就是该设计的核心）。

### 4.4 reward token 什么时候真的转到你钱包？——可能会出现“成批到账”的观感

转出 reward 的函数会在需要时才去 `SY.claimRewards()` 把外部奖励拉进来：

- `if (_selfBalance(token) < rewardPreFee) { _redeemExternalReward(); }`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:467`
- `_redeemExternalReward()` 实际调用 `IStandardizedYield(SY).claimRewards(address(this))`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:481`

所以如果底层 SY 的奖励累积是 lazy 的，你会看到：

- reward index 更新（`rewardIndexesCurrent`）可能是离散的
- `claimRewards` 也可能是在某次用户 claim 时才触发

这不是 “漏发”，而是 **更新与实际转账都偏 lazy**。

---

## 5. 一个最常见的问题：`exchangeRate()` 刚涨我就卖 YT，会丢利息/奖励吗？

### 5.1 利息（SY）不会凭空丢：卖出前会先把你那段收益写进 `accrued`

假设你从 Alice → Bob 转出（卖出）Y T：

1) `PendleERC20._transfer()` 在改余额前调用 `_beforeTokenTransfer(from,to,amount)`：`pendle-core-v2-public/contracts/core/erc20/PendleERC20.sol:195`
2) YT 的 `_beforeTokenTransfer` 会对 Alice/Bob 都进行结算：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:505`
3) 利息结算用的是 “Alice 当前余额（扣减前）+ 当前指数 - 快照指数” 并写进 `userInterest[Alice].accrued`：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:74`

因此：

- 你卖出后 `balanceOf(Alice)` 变成 0，不影响你已经写进 `accrued` 的利息；你可以之后再单独调用 `redeemDueInterestAndRewards(Alice, true, false)` 把 SY 转出：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:168`。

### 5.2 奖励（reward tokens）同理：卖出前会先累计到 `userReward[token][Alice].accrued`

原因同上：卖出过程会先 `_updateAndDistributeRewardsForTwo(from,to)`，把 index 差结算到 `userReward[token][Alice].accrued`（见 `pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:35`）。

---

## 6. “延迟/提前”到底来自哪里？——两个真实的边界效应

### 6.1 结算是 lazy 的：状态更新只在交互时发生

你不转账、不 redeem，`userInterest.accrued` 就不会自动变大；但这不代表少了，只是 “下一次交互” 时一次性结算。

对应原因：利息结算函数只会在：

- `_beforeTokenTransfer`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:505`
- 或 `redeemDueInterestAndRewards` 内部：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:188`

才被触发。

### 6.2 同一 block 缓存指数（可选）：最多造成 1 block 的“谁吃到涨幅”的边界

当 `doCacheIndexSameBlock=true` 时：

- 若本 block 内 `_pyIndexCurrent()` 已经更新过一次，则同 block 后续调用直接返回 `_pyIndexStored`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:404`

这意味着：

- 如果 SY 的 `exchangeRate()` 在同一个 block 内因为某个调用发生了变化（例如某些 SY 的 lazy accrue），而你又恰好在 “本 block 已缓存旧指数之后” 卖出，那么你这次卖出用的仍可能是旧指数；这段变化会延后到下个 block 首次更新指数时才被结算，可能由下一个持有人吃到。

（是否真的会在同一 block 内变化，取决于具体 SY 的实现；YT 侧只提供“是否缓存”这个开关。）

---

## 7. 到期后（post-expiry）怎么处理？——冻结用户权益，后续收益归 treasury

### 7.1 第一次触发到期逻辑时，记录“到期那刻”的基准指数与 reward index

一旦 `isExpired()` 为真，YT 会在交互中尝试设置 `postExpiry`：

- `postExpiry.firstPYIndex = _pyIndexCurrent()`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:385`
- `postExpiry.firstRewardIndex[token] = SY.rewardIndexesCurrent()[i]`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:387`

触发点包括：

- `updateData` modifier：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:54`
- `_beforeTokenTransfer`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:506`

### 7.2 到期后用户的 interest/reward 如何冻结？

- interest：`_getInterestIndex()` 在到期后返回 `postExpiry.firstPYIndex`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:398`
- rewards：`_updateRewardIndex()` 在到期后返回 `postExpiry.firstRewardIndex`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:494`

含义：

- 用户只能拿到 **到期之前累计的** interest/rewards（冻结在 “first” 这些 index 上）
- 到期之后底层继续产生的收益会被归到 treasury（见下一节）

### 7.3 到期后继续增长的 `exchangeRate`（或新 reward）如何归 treasury？

interest（SY）方面，redeem PY 时会把 “到期后多出来的那部分”累计到 `postExpiry.totalSyInterestForTreasury`：

- `syToUser = assetToSy(indexCurrent, amountPY)`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:358`
- `totalSyRedeemable = assetToSy(firstPYIndex, amountPY)`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:360`
- `syInterestPostExpiry = totalSyRedeemable - syToUser`：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:361`
- 加到 treasury 计数器：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:344`

之后由 `redeemInterestAndRewardsPostExpiryForTreasury()` 把累计的 SY interest 与 reward token 统一转给 treasury：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:201`。

---

## 8. 研究/复现时的最小 checklist（你只要盯这些点就能推导交易级归属）

- 指数读取与缓存：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:403`
- 利息结算：`pendle-core-v2-public/contracts/core/YieldContracts/InterestManagerYT.sol:63`
- 余额变动结算入口：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:505`
- reward 份额定义：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:486`
- reward index 更新与累积：`pendle-core-v2-public/contracts/core/RewardManager/RewardManagerAbstract.sol:35`
- claim 时的顺序（先 rewards 再 interest）：`pendle-core-v2-public/contracts/core/YieldContracts/PendleYieldToken.sol:168`
