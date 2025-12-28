# asdPENDLE（SY-asdPENDLE）exchangeRate 跳涨原因分析（含 2025-12-24 Case）

> 时区：北京时间（UTC+8）  
> 研究对象：
> - `SY-asdPENDLE`：`0xc87d2d5a2117a495e0f04ef9304da603a86b7ad5`（proxy）
> - `yieldToken()`/`asdPENDLE`：`0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`
> - `assetInfo().assetAddress`/`sdPENDLE`：`0x5ea630e00d6ee438d3dea1556a110359acdc10a9`

关联报告：`reports/pendle-market-0xbe570be4238bd9019aa8d575204f1daa27ee0a15-pricing.md`

---

## TL;DR

- `SY ≈ asdPENDLE`（1:1），因此 `SY.exchangeRate()` 的跳动，本质就是 `asdPENDLE` 每股对应的 `sdPENDLE`（share price）在跳。
- 平稳上升主要来自「常规 harvest/复投」的连续累积效应；而偶发的“大跳涨”通常来自 **额外的 `depositReward()` 注入**（不增发 share，只增加 `totalAssets`）。
- 你指出的 **2025-12-24 10:00~11:00（北京）附近**的飙升，对应到链上最可疑的是一笔大额 `DepositReward`：`0xedf67d107fd63918d605726c48817becbbc605692085333edaac6ad853d56d24`（11:18:35 北京）向 `asdPENDLE` 注入 `1558.817161623392166803 sdPENDLE`。

---

## 1. 为什么会“看起来每时每刻都在产生利息”

- `SY.previewDeposit(asdPENDLE, 1e18) = 1e18`、`SY.previewRedeem(asdPENDLE, 1e18) = 1e18` ⇒ `SY` 与 `asdPENDLE` 近似 1:1。
- `SY.exchangeRate()`/`pyIndex`（单位：`sdPENDLE per SY`）可以理解为：
  - `exchangeRate ≈ totalAssets(sdPENDLE) / totalSupply(asdPENDLE shares)`
  - 当 `totalAssets` 随时间增加，exchangeRate 就会上升。
- 平滑上涨：更多来自底层资产/策略收益的持续累积（在时间维度上显得“每时每刻都在涨”）。
- 跳涨：当某个时点 `totalAssets` 被一次性拉升（但 share 数量几乎不变），就会出现你看到的 exchangeRate “突然飙一下”。

---

## 2. 能让 exchangeRate 变大的两条链上路径

### 2.1 常规：`Harvest`（小额、较频繁）

- 典型触发者：`harvester()` = `0xfa86aa141e45da5183b42792d99dede3d26ec515`
- 事件：`Harvest(caller, receiver, assets, performanceFee, harvesterBounty)`
- 特征：每次规模通常只有 ~`70~80 sdPENDLE`，对 exchangeRate 的影响是“小台阶”。

### 2.2 额外：`depositReward`（大额、偶发，导致“突然一大笔”）

链路是：**`SdPendleBribeBurner.burn()` → `asdPENDLE.depositReward()`**。

- Bribe burner：`0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2`（已验证源码：`SdPendleBribeBurner`）
- 核心逻辑（按 `sdPENDLE` 余额拆分后再处理）：
  - 平台费：`asdPENDLE.getExpenseRatio()` = 10% → `asdPENDLE.treasury()` = `0x32366846354db5c08e92b4ab0d2a510b2a2380c8`
  - Booster：`asdPENDLE.getBoosterRatio()` = 10% → 转成 `SDT` 打给 `delegator` = `0x6037Bb1BBa598bf88D816cAD90A28cC00fE3ff64`
  - 剩余约 80%：调用 `asdPENDLE.depositReward()` 注入 vault（不 mint share → 直接抬升 exchangeRate）
- 权限点：bribe burner 地址拥有 `asdPENDLE` 的 `REWARD_DEPOSITOR_ROLE`，因此可以 `depositReward`。

---

## 3. Case：2025-12-24 11:18（北京）exchangeRate 跳涨的链上证据

### 3.0 这笔钱“从哪来”：同区块前一笔 `claim` 把资金打进 burner

在 `burn()` 之前，`SdPendleBribeBurner` 的 `sdPENDLE` 余额来自一笔“领取 bribe/奖励”的交易：

- tx：`0x3ffae07496c1921b952d51dbdb9905946bdc69e79d9fc3b509634ac73b9ea866`
- block：`24079741`
- timestamp：`1766546303`（2025-12-24 11:18:23 北京）
- 资金路径（同一笔 tx 内完成）：
  - `MultiMerkleStash`：`0x03e34b085c52985f6a5d27243f20c84bddc01db4` → 转出 `1948.521452029240208503 sdPENDLE`
  - `0x1c0d72a330f2768daf718def8a19bab019eead09`（proxy，implementation `0x353e11ab2da88bfc57fd42c2871301c1f123d4db`）→ 立刻把同额 `sdPENDLE` 转给 `SdPendleBribeBurner`：`0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2`

直观理解：这类基于 Merkle 的 bribe/奖励分发（`MultiMerkleStash`）往往是“攒一段时间再被领取”，所以 `claim` 执行时会出现一次性大额入账；随后 burner 再把这笔钱通过 `depositReward` 变成 `asdPENDLE` 持有人看到的 exchangeRate 跳涨。

### 3.0.1 这笔 Merkle 奖励池“谁打钱进去的”：`Botmarket` 出资（资金主要来自 `0x52ea...`)

这次 `MultiMerkleStash`（`0x03e3...`）针对 `sdPENDLE` 的 **update=`0xa4`**，是在下面这笔交易里完成“打钱 + 更新 merkleRoot”的：

- tx：`0xae6c6eee816b7a99ab66dc927bcab60fe9b579ac55da75c1dc3c85bdea892988`
- timestamp：`1766481839`（2025-12-23 17:23:59 北京）
- `sdPENDLE` 入账到 `MultiMerkleStash`：`5330.308290107408187392 sdPENDLE`
- 直接打款方：`Botmarket` `0xadfbfd06633eb92fc9b58b3152fe92b0a24eb1ff` → `MultiMerkleStash` `0x03e34b085c52985f6a5d27243f20c84bddc01db4`

其中 `Botmarket` 本身是 StakeDAO 的资金归集/出金合约（源码注释：*Contract recipient from sdToken bounties on Votemarket*），受 `governance()` = `0xf930ebbd05ef8b25b1797b9b2109ddc9b0d43063`（Gnosis Safe）控制；只有被白名单的地址（`isAllowed`）才能调用 `withdraw()` 把钱转出（例如 `AllMight 0x0000000a3fc396b89e4c11841b39d9dff85a5d05` 为 `true`）。

进一步往上追 `Botmarket` 的这 `5330.30829 sdPENDLE` 从哪来，可以拆成两笔在 12/23 前入账 `Botmarket` 的来源（两者加总≈5330.30829）：

- **`5165.5 sdPENDLE`**：EOA `0x52ea58f4fc3ced48fa18e909226c1f8a0ef887dc` 直接转给 `Botmarket`
  - tx：`0xc718a2c83d5cb77175a9b58f212a4a13cb1e71ca65b8f3a6a40a3a73c4b1db15`（2025-12-16 21:48:11 北京）
- **`164.808290107408187392 sdPENDLE`**：`AllMight` `0x0000000a3fc396b89e4c11841b39d9dff85a5d05` 转给 `Botmarket`（同 tx 内可见 `sdPENDLE` 从 `0x0` mint 给 `AllMight` 后再转出）
  - tx：`0xb03973035835b48037e216871b0e6675e5b9ea1211ce7f37615f4cae044cd8fd`（2025-12-22 18:06:47 北京）

### 3.1 大额 `DepositReward`（最可能的“跳涨”来源）

- tx：`0xedf67d107fd63918d605726c48817becbbc605692085333edaac6ad853d56d24`
- block：`24079742`
- timestamp：`1766546315`（2025-12-24 11:18:35 北京）
- 事件：`DepositReward`
- 注入量：`1558.817161623392166803 sdPENDLE`

补充：若按 bribe burner 的 10% + 10% + 80% 结构倒推，这次 burn 前的 `sdPENDLE` 余额约 `1948.52145202924020850375`，其中每个 10% 费用约 `194.852145202924020850375`。

### 3.2 同日附近的常规 `Harvest`（对比：量级明显更小）

- `0xa7fa5b79985c490235d209b182df09bfd4408bd5c548e772af8c0d88a811daf8`（2025-12-24 09:55:35 北京）：assets ≈ `74.8904821695 sdPENDLE`
- `0xa5c6b000ef12f540e8d4c6b878de6660a89a23801bd8376bb9eb408de84b4591`（2025-12-24 12:59:11 北京）：assets ≈ `76.7522590997 sdPENDLE`

这些 harvest 会让 exchangeRate 上升，但很难造成“突然飙一下”的观感；而 `1558.8 sdPENDLE` 级别的 `DepositReward` 则足以。

---

## 4. 如何快速定位未来的“突然跳涨”

- 直接筛 `asdPENDLE (0x6064...)` 的 `DepositReward` 事件：基本都对应明显抬升 exchangeRate 的时点。
- 追踪 `SdPendleBribeBurner (0x8bde...)` 的 `burn()` 交易：其触发时间与金额取决于 burner 内累计的 bribes/奖励规模，因此天然“有时小、有时突然很大”。

---

## 5. 全局时间线（近30天，UTC+8）

> 时间窗口（按 block timestamp）：`2025-11-28 17:48:35`（block `23896381`）~ `2025-12-28 17:48:35`（block `24110331`）

### 5.1 Botmarket（`0xadfb...`）近30天 `sdPENDLE` 余额变化与关键转账

说明：由于历史 `balanceOf(blockTag)` 在部分 RPC/工具下不稳定，这里用 `sdPENDLE Transfer` 事件做“流水累加”来还原余额变化。

- 窗口起始余额：`5165.5 sdPENDLE`
- 窗口结束余额：`2057 sdPENDLE`（当前 `sdPENDLE.balanceOf(0xadfb...)`）
- 近30天流入：`18537.624424155795452632 sdPENDLE`
- 近30天流出：`21646.124424155795452632 sdPENDLE`（全部流向 `MultiMerkleStash 0x03e3...`）
- 净变化：`-3108.5 sdPENDLE`

**入金（外部 → Botmarket）**

- `2025-12-01 21:59:59`：`AllMight 0x0000000a3fc...` → `Botmarket` `212.655686496179363578 sdPENDLE`（tx：`0x9219b9df90065269706897a3ca56317c39436d029d96e65133ffc18815e56d58`）
- `2025-12-03 05:43:59`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xb8fb880d9b4e58311e7eea01cc9340de8799ad8ba6209f1beeee09939f4e2723`）
- `2025-12-08 22:07:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `130.637242379906717995 sdPENDLE`（tx：`0x32d59c6bf4eb83eee630b814be4e7c555598886eb565a17e13f16d9b01e1d74e`）
- `2025-12-09 23:55:11`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xe74b4578d7ae86aea6f06b1963687accd75345d70dfcde838461d1c91795117e`）
- `2025-12-16 00:59:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `476.023205172301183667 sdPENDLE`（tx：`0x1a6c56d0218c535e6f2af20ec36432f67d27f3b75648dd27d34836278677e4f0`）
- `2025-12-16 21:48:11`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xc718a2c83d5cb77175a9b58f212a4a13cb1e71ca65b8f3a6a40a3a73c4b1db15`）
- `2025-12-22 18:06:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `164.808290107408187392 sdPENDLE`（tx：`0xb03973035835b48037e216871b0e6675e5b9ea1211ce7f37615f4cae044cd8fd`）
- `2025-12-23 18:55:35`：`0x52ea58f4...` → `Botmarket` `2057 sdPENDLE`（tx：`0x9e152fb01d7e951f213d146de57c17ee6dd45b2d5783089d9cd091b32b149511`）

**出金（Botmarket → MultiMerkleStash，Merkle 奖励池入金）**

- `2025-12-02 17:48:11`：`update=0x9e`，`5378.155686496179363578 sdPENDLE`（tx：`0xca68296356ff9357fe5b2f7a2b8da898f88bfd07ffcd3a18f8c7b3c9d157a88e`）
- `2025-12-09 17:28:23`：`update=0xa0`，`5296.137242379906717995 sdPENDLE`（tx：`0x242cf56995464b262387c46504a2d239c239f6fb053bdb1b194a6d17f1c64281`）
- `2025-12-16 17:19:59`：`update=0xa2`，`5641.523205172301183667 sdPENDLE`（tx：`0x98f6fc12788a0d04507e6752a33905ca641009f4e25cf0ece3283e86b6b412ab`）
- `2025-12-23 17:23:59`：`update=0xa4`，`5330.308290107408187392 sdPENDLE`（tx：`0xae6c6eee816b7a99ab66dc927bcab60fe9b579ac55da75c1dc3c85bdea892988`）

> 观察：每次入金的金额都可以拆成 `5165.5 + X`，其中 `5165.5` 来自 `0x52ea...` 的周期性转账，`X` 来自 `AllMight` 的补差额（同 tx 内常可见 `sdPENDLE` 从 `0x0` mint 给 `AllMight` 后再转出）。

### 5.2 Merkle 奖励入账 → `asdPENDLE` 升值（exchangeRate 跳涨）时间线

这条链路在链上通常表现为“两步连击”，且常由同一个执行者触发：

1) `claim`：`0x11e91bb6d1334585aa37d8f4fde3932c7960b938` 调用 `asdPENDLE 0x6064...`，从 `MultiMerkleStash 0x03e3...` 领取 `sdPENDLE`，经 `0x1c0d72...` 转进 `SdPendleBribeBurner 0x8bde...`  
2) `burn`：同一执行者调用 `burner.burn()`，拆分 burner 内 `sdPENDLE`：10% `treasury 0x3236...`、10%（swap→`SDT`）`delegator 0x6037...`、剩余约 80% 进 `asdPENDLE.depositReward()` → 触发 exchangeRate 跳涨

**跳涨事件（`DepositReward`）与上游 `claim` 对应关系**

- `update=0x9e`
  - `2025-12-03 12:20:35`：`claim` 转入 burner `1959.977146389130894022 sdPENDLE`（tx：`0x2278471472081e46dc8abec5e2795d6f65244addf532f25cf28ae66c20959f95`）
  - `2025-12-03 12:20:47`：`burn` → `DepositReward` `1567.981717111304715218 sdPENDLE`（tx：`0x7ed5237fe83a405a74e6fb2a776ca8749530793fa8300733e038575cedbc32b2`）
- `update=0xa0`
  - `2025-12-10 10:40:23`：`claim` 转入 burner `1920.452686027460458718 sdPENDLE`（tx：`0x0567e6df942ce9fac0507c339dc5b7f6287de262eff249c5973a962ea1e1de82`）
  - `2025-12-10 10:40:35`：`burn` → `DepositReward` `1536.362148821968366976 sdPENDLE`（tx：`0xfe75375e39bc58ec128cfc38f3a0ed8435252e08cdd4ee006ff0478fc1db5d57`）
- `update=0xa2`
  - `2025-12-18 13:42:23`：`claim` 转入 burner `2095.586647342115156789 sdPENDLE`（tx：`0x6a035fcff20179f9776f30b3cf30f838bf9e108f870a900e7d67fc6d544d294e`）
  - `2025-12-18 13:42:59`：`burn` → `DepositReward` `1676.469317873692125433 sdPENDLE`（tx：`0x21398b3496b0fbf33db32e3eee3ffa234a3348178115555d73951e8005d2fdc3`）
- `update=0xa4`（你关注的 12/24 跳涨，详见上面 Case）
  - `2025-12-24 11:18:23`：`claim` 转入 burner `1948.521452029240208503 sdPENDLE`（tx：`0x3ffae07496c1921b952d51dbdb9905946bdc69e79d9fc3b509634ac73b9ea866`）
  - `2025-12-24 11:18:35`：`burn` → `DepositReward` `1558.817161623392166803 sdPENDLE`（tx：`0xedf67d107fd63918d605726c48817becbbc605692085333edaac6ad853d56d24`）

> 观察：这 4 次跳涨里，`DepositReward` 都精准满足 `≈ claim_amount * 80%`，与 burner 的 `10% + 10% + 80%` 拆分逻辑一致；因此“偶尔突然一大笔”，本质就是上游 `claim` 把一段时间累计的 Merkle 奖励一次性结算进来，然后被 burner 一次性 `depositReward` 到 vault。 
