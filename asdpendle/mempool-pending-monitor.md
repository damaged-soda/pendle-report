# 用 mempool 捕捉 `harvestBribe → burn → depositReward` 的 pending 预警方案（Alchemy WSS）

> 背景报告：`asdpendle/report.md`  
> 相关策略（不抢排序版、以 L0 为主的小时级提前量）：`asdpendle/prepositioning-strategy.md`

---

## 0. TL;DR

- 你关心的 tx（例如 `0x227847...59f95`）本质是一次 **`asdPENDLE.harvestBribe(...)`（claim）**，它通常会在 **几十秒内** 被同一执行者接着发起的 **`SdPendleBribeBurner.burn(...)`（burn）** 跟上。
- `burn()` 会把 burner 里的 `sdPENDLE` 按固定比例拆分，其中约 **80% 调用 `asdPENDLE.depositReward()`**（不增发 share，只增加 `totalAssets`），从而触发 `SY.exchangeRate()`/`pyIndex` 的 **跳涨**（详见 `asdpendle/report.md`）。
- **为什么要抓 mempool/pending**：链上 log/receipt 只能“事后确认”；而 `claim → burn` 的窗口往往只有 **12~60 秒**（甚至更短）。mempool 是少数能提供“事前预警”的手段之一。
- **方案核心**：用 Alchemy WSS 的 `alchemy_pendingTransactions` 订阅 `toAddress = [asdPENDLE, burner]`，本地用 `input` 前 4 bytes（selector）做二次过滤/解码；再用 `(from, nonce)` 做 `claim ↔ burn` 关联；最后用链上 `logs` 订阅做兜底确认与统计。
- **重要现实**：mempool 并不完整（私有交易/Flashbots/bundle 看不到，节点视角也不一致），所以**不能只靠 mempool**；必须把 `logs` 兜底当成“最终真相源”。

---

## 1. 前因：为什么这类交易值得“提前知道”

`asdpendle/report.md` 已解释了跳涨链路，这里只抽取与 mempool 方案直接相关的因果：

1) **claim（harvestBribe）**  
执行者调用 `asdPENDLE.harvestBribe(...)`，从 `MultiMerkleStash` 领取累计的 `sdPENDLE`，资金最终进入 `SdPendleBribeBurner`。

2) **burn（burner.burn）**  
执行者紧接着调用 `SdPendleBribeBurner.burn(...)`，把 burner 内 `sdPENDLE` 拆分：  
`10% → treasury`、`10% → booster（swap 成 SDT）`、**`~80% → asdPENDLE.depositReward()`**

3) **结果：`depositReward` 抬升 share price / `SY.exchangeRate()`**  
由于 `depositReward` 不 mint share，而是增加 vault 的 `totalAssets`，因此 `asdPENDLE` 的 share price（以及 `SY.exchangeRate()`/`pyIndex`）会出现明显“台阶”跳涨。

这条链路的关键工程结论是：

- `claim → burn` 时间非常短：如果你想在跳涨发生前完成某些动作（下单、调仓、打标签、做风控），**只能依赖 mempool 的秒级预警**或更早的小时级信号（L0：`update_inflow`）。

---

## 2. 后果：mempool 能给你什么、不能给你什么

### 2.1 能给你的：秒级“可能马上发生”的预警

- 一旦看到 `harvestBribe` pending，通常意味着：
  - `sdPENDLE` 很快会进入 burner（如果 claim 成功）
  - 同一执行者大概率马上发 `burn`（下一笔 nonce）
  - `depositReward` 很可能在 1~数个区块内落地

这类预警适合：

- **告警/监控**：提示“跳涨即将发生”，用于人工盯盘或记录数据；
- **自动化预案**：触发一个更重的 on-chain/off-chain 流程（例如重新估值、撤单、调整仓位）。

### 2.2 不能给你的：100% 覆盖与确定性

必须接受以下限制：

- **私有交易不可见**：执行者可能用 Flashbots / MEV-Share / 自建 relay / bundle 直接给出块构建者，你的 mempool 订阅可能完全看不到。
- **节点视角不一致**：Alchemy 的 “pending feed” 很强，但也不是“全球 mempool 真相”。同一时刻不同节点看到的 pending 集合会不同。
- **pending ≠ 必然上链**：tx 可能被 replace（同 nonce 提高 gas）、被 drop、被卡很久、或最终 revert。

因此工程上必须做到：

- mempool 负责 **早知道**（best-effort）
- logs/receipt 负责 **最终确认**（source of truth）

---

## 3. 你要抓的“同一类 tx”到底是什么特征

### 3.1 关键地址（mainnet）

（详细背景见 `asdpendle/prepositioning-strategy.md`）

- `asdPENDLE`（compounder / yieldToken）：`0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`
- `SdPendleBribeBurner`：`0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2`
- `sdPENDLE`（ERC20）：`0x5ea630e00d6ee438d3dea1556a110359acdc10a9`
- `MultiMerkleStash`：`0x03e34b085c52985f6a5d27243f20c84bddc01db4`
- `Botmarket`：`0xadfbfd06633eb92fc9b58b3152fe92b0a24eb1ff`

### 3.2 关键 selector / topic

（这些值在 `asdpendle/prepositioning-strategy.md` 里也有，便于你直接复用）

- `asdPENDLE.harvestBribe((address,uint256,uint256,bytes32[]))` selector：`0x417e3310`
- `SdPendleBribeBurner.burn((address,bytes,uint256))` selector：`0x27084a41`
- `asdPENDLE.DepositReward(uint256)` topic：`0x19d619b124479c2d70fdcdb33644246ae36f947e11b9612f998df529be9e54b6`
- `sdPENDLE.Transfer(address,address,uint256)` topic：`0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`

### 3.3 例子：你提到的 `0x2278...` 属于哪一段

在 `asdpendle/report.md` 的时间线里：

- `0x227847...59f95` 是 **claim**（`harvestBribe`），把 `sdPENDLE` 领到 burner。
- 随后紧跟的 `0x7ed523...32b2` 是 **burn**（触发 `depositReward`），形成跳涨。

工程上这意味着：你要捕捉的 pending 交易特征更像是：

- **`to=asdPENDLE` 且 selector=`0x417e3310`**（L1 预警）
- 或 **`to=burner` 且 selector=`0x27084a41`**（L2 更近的预警）

---

## 4. 方案总览（推荐：mempool + logs 双通道）

### 4.1 数据通道 A：Alchemy pending（事前预警）

用 `alchemy_pendingTransactions` 订阅你关心的“收件人地址”，拿到完整 tx（`hashesOnly=false`），然后在你本地做二次过滤：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "eth_subscribe",
  "params": [
    "alchemy_pendingTransactions",
    {
      "toAddress": [
        "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf",
        "0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2"
      ],
      "hashesOnly": false
    }
  ]
}
```

你本地只保留：

- `tx.to == asdPENDLE && tx.input.startsWith("0x417e3310")`（harvestBribe）
- `tx.to == burner && tx.input.startsWith("0x27084a41")`（burn）

> 为什么不直接用 token `toAddress=sdPENDLE` 来抓 `Transfer`？因为 token `Transfer` 是日志事件，不在交易顶层；mempool 里你只能看到 tx 的 `to/from/input/value/gas...`，看不到“未来会 emit 哪些 log”。

### 4.2 数据通道 B：链上 logs（最终真相 + 兜底）

无论 mempool 是否可见，你都能在交易落块后通过 `logs` 拿到确定信息：

- 订阅 `asdPENDLE.DepositReward`：确认跳涨是否发生、发生的金额；
- 订阅 `sdPENDLE.Transfer`：
  - `Botmarket → MultiMerkleStash`（L0，小时级提前量）
  - `to=burner`（claim 资金是否到位）
  - `from=burner,to=asdPENDLE`（token 侧确认 depositReward 的流向）

这使得你的系统在“看不到 pending/看漏 pending”的情况下仍能正确工作（只是少了预警）。

---

## 5. 处理流程（建议做成状态机）

把你的目标抽象成一个可观测的状态机，能让工程实现更稳定，也更容易做统计/回测。

### 5.1 关键关联：用 `(from, nonce)` 把 claim 和 burn 串起来

你关心的模式通常是同一执行者连击：

- `harvestBribe`: `(from=A, nonce=n)`
- `burn`: `(from=A, nonce=n+1)`

因此关联规则建议按优先级：

1) **强关联**：同 `from` 且 `burn.nonce == claim.nonce + 1`  
2) **弱关联**：同 `from` 且时间间隔很短（例如 0~120s），但 nonce 不一定连号（有时中间夹了别的 tx）

### 5.2 pending 事件的生命周期（必须处理 replace/drop）

对每个 `(from, nonce)` 维护一个“当前活跃 hash”：

- 如果同一 `(from, nonce)` 出现新的 `hash`，视为 replace（RBF），用新 tx 覆盖旧 tx；
- 设置 TTL（例如 10~30 分钟）：超时仍未 mined 的 pending 进入 `stale` 状态；
- 通过 `newHeads` 驱动对活跃 hash 做 `eth_getTransactionReceipt` 轮询，标记为 `mined` / `dropped`。

### 5.3 预估跳涨规模（可选但很有用）

如果你在 `harvestBribe` calldata 里能解码出 `claim_amount`（`sdPENDLE` 数量），可以做一个最直接的估算：

- `predDepositReward ≈ claim_amount * (1 - expenseRatio - boosterRatio)`
- 在你的报告样本里通常接近 `claim_amount * 0.8`

更稳健一点的做法是“参数不写死”：

- 启动时（或定期）用 RPC `eth_call` 读取 `asdPENDLE.getExpenseRatio()` / `asdPENDLE.getBoosterRatio()`（如果合约提供），动态得到当前拆分比例；
- 发现比例变化就立刻告警（这本身就是重要风险信号）。

> 注意：你无法可靠地在 mempool 里“模拟未来日志”，也很难精确知道 burner 当时余额、swap 路径、minOut 等边界条件；所以预估是启发式的，最终以 `DepositReward` 日志为准。

---

## 6. 工程架构建议（模块拆分）

建议拆成 5 个组件，减少耦合、方便扩展到更多目标：

1) **`PendingTxWatcher`**：连接 Alchemy WSS，接收 pending tx，做 `toAddress + selector` 过滤，产出 `ClaimPending` / `BurnPending` 事件流。
2) **`LogWatcher`**：订阅 `DepositReward` 与 `sdPENDLE.Transfer`（以及可选的 `newHeads`），产出 `DepositRewardMined` / `TransferMined` 等事件流。
3) **`Correlator`**：维护 `(from, nonce)` 状态，把 `claim` 与 `burn` 关联；输出“连击检测”事件（例如 `ComboLikelySoon`）。
4) **`Estimator`**：把 `claim_amount` 变成 `predDepositReward`、再变成你关心的指标（例如预计 `exchangeRate` 跳涨百分比）。
5) **`Notifier/Strategy`**：告警、写数据库、或触发你的交易/风控动作。

数据存储建议最少做到：

- 把所有 `DepositRewardMined` 事件落盘（这是你最终要回测/统计的核心数据集）
- 把 “mempool 是否提前看到 claim/burn” 也落盘（用于量化你 mempool 方案的覆盖率）

---

## 7. 风险与对策（务必写进设计里）

- **看不到 pending（私有交易）** → 用 `logs` 兜底 + 统计“可见率”；必要时多接几家 provider/自建节点提高覆盖。
- **pending replace/drop** → 用 `(from, nonce)` 追踪 replace，用 TTL + receipt 轮询判定落地与否。
- **reorg** → 对关键动作（尤其重仓动作）等待 N 确认（例如 2~5）；或至少能在 reorg 时回滚状态。
- **行为改变/参数改变**（expenseRatio/boosterRatio、burner 地址、claimer 逻辑变化）→ 把这些当作监控项，变化即告警。
- **策略层风险**（滑点、流动性、被夹、gas 成本）→ 这属于交易策略范畴；mempool 预警只能解决“早知道”，不能保证“能安全赚钱”。

---

## 8. 和 L0（update_inflow）监控的关系：各自解决不同问题

如果你的目标是不抢排序、尽量稳健地吃跳涨（见 `asdpendle/prepositioning-strategy.md`）：

- 主触发应是 **L0：`Botmarket → MultiMerkleStash` 的大额入金**（小时级提前量）
- mempool 预警更多是：
  - **确认**“这轮终于要发生了”（从小时级变成秒级）
  - **修正**时序统计（例如未来出现更早的 claim）
  - **做数据**（把 pending 与最终落地匹配起来，量化可见率与延迟）

如果你的目标是更激进的“临近跳涨再动作”，那 mempool 才是关键输入，但也会更依赖 gas/打包策略与执行细节。

---

## 9. 附录：推荐订阅清单（最小可用）

**pending（Alchemy）**

- `alchemy_pendingTransactions`：`toAddress=[asdPENDLE, burner]`，`hashesOnly=false`

**mined（任意以太坊节点都可）**

- `eth_subscribe: logs`（`asdPENDLE.DepositReward`）
- `eth_subscribe: logs`（`sdPENDLE.Transfer`，可按 from/to topic 做过滤）
- `eth_subscribe: newHeads`（驱动确认数、对活跃 pending 做 receipt 检查）

