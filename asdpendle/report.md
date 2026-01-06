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

### 3.0.2 Merkle 分发的“规则”：每个用户怎么知道自己能领多少（以及为什么链上看不出固定比例）

这里的 `MultiMerkleStash` 是典型的 **Merkle Distributor** 设计：链上只存一个 `merkleRoot`（承诺），把“给谁分多少”的明细放在链下。

- 链上校验逻辑很简单：`claim(token, index, account, amount, merkleProof)` 只做 `MerkleProof.verify(proof, merkleRoot[token], keccak(index, account, amount))`，通过就把 `amount` 转给 `account`；**合约本身不计算“按入金比例/权重自动分配”**。
- 因此，`0x1c0d72...` 能领多少（以及你问的 `claim_amount / Botmarket_inflow` 比例）不是链上固定参数，而是 **每次 update 由分发方在链下生成的分配表决定**（再把 `merkleRoot` 上链）。
- 经验观察（不构成规则）：在我们抽取的 `update=0x9e/0xa0/0xa2/0xa4/0xa6` 样本里，`claim_amount / Botmarket_inflow` 大致落在 `~36%~38%`，取决于当期分配表中分给该 `account` 的份额。
- 用户/执行者之所以“知道自己能领多少”，靠的是链下发布的分配数据（常见是前端/API/JSON/IPFS/GitHub 等）：里面会给出 `index/amount/proof`，前端再把这些参数拼进 `claim` 交易里。
- 可信性来自 `merkleRoot`：你可以用分配表重算 root，并与链上 `MerkleRootUpdated` 事件的 root 对比；对不上就无法在链上通过校验。
- 这样做的目的主要是减轻链上负担：不用在链上存大表/也不用批量转账；每个领取交易只需 `O(log N)` 的 proof 校验，gas 成本由领取者分摊。

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

> 时间窗口（按 block timestamp）：`2025-12-02 17:36:23`（block `23924925`）~ `2026-01-01 17:36:23`（block `24138923`）

### 5.1 Botmarket（`0xadfb...`）近30天 `sdPENDLE` 余额变化与关键转账

说明：由于历史 `balanceOf(blockTag)` 在部分 RPC/工具下不稳定，这里用 `sdPENDLE Transfer` 事件做“流水累加”来还原余额变化。

- 窗口起始余额：`5378.155686496179363578 sdPENDLE`
- 窗口结束余额：`2057 sdPENDLE`（当前 `sdPENDLE.balanceOf(0xadfb...)`）
- 近30天流入：`20381.968737659616089054 sdPENDLE`
- 近30天流出：`23703.124424155795452632 sdPENDLE`（全部流向 `MultiMerkleStash 0x03e3...`）
- 净变化：`-3321.155686496179363578 sdPENDLE`

**入金（外部 → Botmarket）**

- `2025-12-03 05:43:59`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xb8fb880d9b4e58311e7eea01cc9340de8799ad8ba6209f1beeee09939f4e2723`）
- `2025-12-08 22:07:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `130.637242379906717995 sdPENDLE`（tx：`0x32d59c6bf4eb83eee630b814be4e7c555598886eb565a17e13f16d9b01e1d74e`）
- `2025-12-09 23:55:11`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xe74b4578d7ae86aea6f06b1963687accd75345d70dfcde838461d1c91795117e`）
- `2025-12-16 00:59:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `476.023205172301183667 sdPENDLE`（tx：`0x1a6c56d0218c535e6f2af20ec36432f67d27f3b75648dd27d34836278677e4f0`）
- `2025-12-16 21:48:11`：`0x52ea58f4...` → `Botmarket` `5165.5 sdPENDLE`（tx：`0xc718a2c83d5cb77175a9b58f212a4a13cb1e71ca65b8f3a6a40a3a73c4b1db15`）
- `2025-12-22 18:06:47`：`AllMight 0x0000000a3fc...` → `Botmarket` `164.808290107408187392 sdPENDLE`（tx：`0xb03973035835b48037e216871b0e6675e5b9ea1211ce7f37615f4cae044cd8fd`）
- `2025-12-23 18:55:35`：`0x52ea58f4...` → `Botmarket` `2057 sdPENDLE`（tx：`0x9e152fb01d7e951f213d146de57c17ee6dd45b2d5783089d9cd091b32b149511`）
- `2025-12-30 23:06:59`：`0x52ea58f4...` → `Botmarket` `2057 sdPENDLE`（tx：`0x1e251e5c5ac2af6e8eb5d2661d86ca903214afe4e3b21e8411da9241932f2d26`）

**出金（Botmarket → MultiMerkleStash，Merkle 奖励池入金）**

- `2025-12-02 17:48:11`：`update=0x9e`，`5378.155686496179363578 sdPENDLE`（tx：`0xca68296356ff9357fe5b2f7a2b8da898f88bfd07ffcd3a18f8c7b3c9d157a88e`）
- `2025-12-09 17:28:23`：`update=0xa0`，`5296.137242379906717995 sdPENDLE`（tx：`0x242cf56995464b262387c46504a2d239c239f6fb053bdb1b194a6d17f1c64281`）
- `2025-12-16 17:19:59`：`update=0xa2`，`5641.523205172301183667 sdPENDLE`（tx：`0x98f6fc12788a0d04507e6752a33905ca641009f4e25cf0ece3283e86b6b412ab`）
- `2025-12-23 17:23:59`：`update=0xa4`，`5330.308290107408187392 sdPENDLE`（tx：`0xae6c6eee816b7a99ab66dc927bcab60fe9b579ac55da75c1dc3c85bdea892988`）
- `2025-12-30 17:58:23`：`update=0xa6`，`2057 sdPENDLE`（tx：`0x0f9622d8b236db44c4af611ba79304c9affbd3bce6cb5e20ed5f8da6341134a2`）

> 观察：`update=0x9e/0xa0/0xa2/0xa4` 的入金金额都可以拆成 `5165.5 + X`，其中 `5165.5` 来自 `0x52ea...` 的周期性转账，`X` 来自 `AllMight` 的补差额（同 tx 内常可见 `sdPENDLE` 从 `0x0` mint 给 `AllMight` 后再转出）；但 `update=0xa6` 本次入金仅 `2057`，不满足该拆分。

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
- `update=0xa6`
  - `2025-12-31 21:39:11`：`claim` 转入 burner `787.861635830934915248 sdPENDLE`（tx：`0x1da0ab75230b0e39b9e98754781a3f14742c96b9e51e8d771e5448aa2058f354`）
  - `2025-12-31 21:39:23`：`burn` → `DepositReward` `630.289308664747932200 sdPENDLE`（tx：`0x03019cd5d0a8f514f2a2666826953fede9e81c9cb7b22eb2039d39bf8365741f`）

> 观察：这 5 次跳涨里，`DepositReward` 都精准满足 `≈ claim_amount * 80%`，与 burner 的 `10% + 10% + 80%` 拆分逻辑一致；因此“偶尔突然一大笔”，本质就是上游 `claim` 把一段时间累计的 Merkle 奖励一次性结算进来，然后被 burner 一次性 `depositReward` 到 vault。 

---

## 6. 继续往上追：Botmarket 入金的更上游资金链（直到“谁出的钱/资产从哪来”）

### 6.1 主路径：`0x52ea...` 的 `sdPENDLE` 从哪来（Pendle Merkle Claim → 换 PENDLE → StakeDAO mint `sdPENDLE`）

结论先讲：`0x52ea58f4...` 给 `Botmarket` 打的 `sdPENDLE`，并不是“凭空出现”，而是它先从 **Pendle 的 Merkle 分发合约**领到一篮子奖励（`USDT / sENA / RESOLV ...`），再把其中一部分在链上换成 `PENDLE`，最后通过 StakeDAO 的 mint 流程把 `PENDLE` 变成 `sdPENDLE`。

**Pendle Merkle 分发合约**

- `0x3942f7b55094250644cffda7160226caa349a38e`（proxy）  
  - verified implementation：`0x946afc64dcb64bb96688ead4f0d0ac67b1dd7a36`（`PendleMultiTokenMerkleDistributor`）

**Case A：2025-11-22（一次 claim 直接“喂”出 16726.3668 PENDLE → 16726.3668 sdPENDLE）**

1) `claim`：`0x52ea...` 从 `PendleMultiTokenMerkleDistributor` 领取多种 token（同一 tx 内多笔 ERC20 Transfer）
- `2025-11-22 18:00:35`（tx：`0x4d06b8c922d84ee5cfa292a4075d15da765defd9f02aca6e101f39b9480ef56a`）
  - `sENA` `176971.985820501345019228`（`0x3942...` → `0x52ea...`）
  - `RESOLV` `3644.380439487571361385`（`0x3942...` → `0x52ea...`）
  - `USDT` `111067.81375`（`0x3942...` → `0x52ea...`）

2) `swap`：把奖励换成 `PENDLE`（这 4 笔 `PENDLE` 入账总和 **精确等于**后续 mint 的 `sdPENDLE` 数量）
- `2025-11-22 18:02:59`（tx：`0xf1e4092d0cb5faa010b17ec916508b248e6a1bc8d6d6c02f3f8ac6bf90945acf`）：`RESOLV` → `PENDLE` `220.040557741788909177`
- `2025-11-22 18:06:59`（tx：`0x04d3e74ab8dd62e0c403e3ea96cb7b4edb02128a03020d68abc014a993a78aae`）：`sENA` → `PENDLE` `5543.188375256401211541`
- `2025-11-22 18:13:23`（tx：`0x72e2d96f954426a631f8961bfeb9813ca6cf5d963dd263c39c4befa421de7939`）：`sENA` → `PENDLE` `5491.048186130134047912`
- `2025-11-22 18:18:11`（tx：`0x55e7dd9a214a76aedf702d8cfef7adbb2fa27a75f53a5cb04e4d9be0c94eb974`）：`sENA` → `PENDLE` `5472.089713947938176470`
- 合计：`16726.366833076262345100 PENDLE`

3) `mint`：把 `PENDLE` 变成 `sdPENDLE`（StakeDAO 流程）
- `2025-11-22 18:19:35`（tx：`0x93fc34698b2258150045a4820656409e8c41bc7b7b76a3d5e947159756ac5d93`）
  - `PENDLE 0x8085...` 从 `0x52ea...` 转出到 `0xd8fa...`（StakeDAO 侧地址）
  - `sdPENDLE 0x5ea6...` 从 `0x0` mint 给 `0x52ea...`：`16726.366833076262345100 sdPENDLE`

**Case B：2025-12-22/12-23（claim 到 USDT/sENA/RESOLV → 换 PENDLE → mint `sdPENDLE`）**

1) `claim`（再次从 Pendle Merkle 分发合约领取）
- `2025-12-22 19:29:59`（tx：`0x4873d8f0be8b6a0eddf90eb477b36a4fdc54e34d089db7adb3ebf9dbf0e122bf`）
  - `sENA` `45461.053757427082946191`
  - `RESOLV` `9600.831991615395504707`
  - `USDT` `65046.169638`

2) `swap`：买入 `PENDLE`
- `2025-12-22 19:51:35`（tx：`0xf2d4778a1575ee32dbe4610f3bdc57a410dc526ec083aa39f9aee1209873f9b8`）：`USDC` 支付 `17090` 买入 `8901.738210969715614994 PENDLE`
- `2025-12-23 18:53:47`（tx：`0x1e19b666016d10d8618954ed3c4302b448082e492861cf76017f009ab82cfbf1`）：`USDT` 支付 `14500` 买入 `8230.114387959190476686 PENDLE`

3) `mint`：`PENDLE → sdPENDLE`
- `2025-12-22 19:53:47`（tx：`0x8cde2c83c751c16e2842b7487460927ff483f8863fbe8bde005e3a6333e41ede`）：mint `8901.738210969715614994 sdPENDLE` → `0x52ea...`
- `2025-12-23 18:54:23`（tx：`0xd7e45f255b1b3f6b1cadecd02a0f7b3e7190fd7e9ab8872dacfbb8abe134e6ab`）：mint `8230.114387959190476686 sdPENDLE` → `0x52ea...`

> 这解释了为什么 `Botmarket` 的入金里会反复出现“固定值 `5165.5`”：`0x52ea...` 本质是在“领取奖励 → 换成 PENDLE → mint sdPENDLE”，再按周期把一部分 `sdPENDLE` 划拨到 `Botmarket` 用于 Merkle 奖励池入金。

### 6.1.1 再往上：Pendle Merkle Distributor（`0x3942...`）的钱是谁打进去的

你问的“这笔钱哪来的”，如果把源头再往上延伸一跳：`0x52ea...` 的 `claim` 之所以能拿到 `USDT/sENA/RESOLV`，是因为 `PendleMultiTokenMerkleDistributor`（`0x3942f7...`）事先被“充值/备货”了。

**12/17（北京）`0xeea6...` 给 `0x3942...` 充值（直接给 Merkle 发放池打钱）**

- `2025-12-17 17:41:23`（tx：`0x8874a8fe5cb286124ca15fc85210d618a23e201b6d8324e38c594c8e2383a892`，block `24031503`）
  - `USDT` `1,408,691`（`0xeea6...` → `0x3942...`）
- `2025-12-17 18:07:59`（tx：`0x4ca1545831e323e895e9cb2c7a4c53292d2540d5f190523ff712fd073fd88415`，block `24031634`）
  - `sENA` `951,099.2`（`0xeea6...` → `0x3942...`）
- `2025-12-17 18:08:35`（tx：`0xcbb5cc43ba30ac5472191bd31e24acd029f9c6098318392bafb220b3dfe114a9`，block `24031637`）
  - `RESOLV` `200,860.8`（`0xeea6...` → `0x3942...`）
- 同批次还包含其它 token 入金（例如 `FF` `745,228`，tx：`0x752721fb36c3034f492055e4faebf871ee2911658214bb0e4bb5894cec0dbea9`，block `24031638`）。

**再往上追一跳：`0xeea6...` 的 `sENA/RESOLV` 来自一个 Gnosis Safe（多签）**

- `2025-12-17 15:34:11`（tx：`0x39d8be6793287c9e72658751c85d7cd857e1cad861885ae1e676a3327779de3d`，block `24030871`）
  - `sENA` `1,188,874`（`0x8270400d...` → `0xeea6...`）
  - `RESOLV` `251,076`（`0x8270400d...` → `0xeea6...`）
  - 同 tx 还有其它 token（例如 `FF` `931,353`）一并转入。
- `0x8270400d528c34e1596ef367eedec99080a1b592` 是 Gnosis Safe proxy（2/6 多签）：
  - `getThreshold()` = `2`
  - `getOwners()` = `0x231fc5...`, `0xdf0002...`, `0x61d615...`, `0xf58270...`, `0x4c3857...`, `0xc1cbc2...`

**继续往上：`0x8270400d...` 自己的 `sENA/RESOLV` 是谁打给它的**

- `sENA`
  - `2025-12-10 13:46:47`（tx：`0x4b3258707019fdd601442f1c036f77bd72f1da7529684c858cac3d332427c291`，block `23980332`）
    - `0xc29e837d...` → `0xc328dfcd...`（同 tx 内 8 笔 Transfer，每笔 `148,609.3159443724 sENA`，合计 `1,188,874.5275549792`）
  - `2025-12-10 13:58:11`（tx：`0x96276912a0ff27e2f124238112c5c2fe6b1f50fed07c567678f6cef7c30da442`，block `23980387`）
    - `0xc328dfcd...` → `0x8270400d...`：`1,188,874.5275549792 sENA`
- `RESOLV`
  - `2025-12-10 13:44:47`（tx：`0xf223de0883d498a592a55b3d4d3d8fb2581e5377cfa416bce8feddde6473af06`，block `23980322`）
    - `0x75320c40...` → `0xc328dfcd...`：`119,530.333333333333333333 RESOLV`
  - `2025-12-10 17:57:35`（tx：`0x2cabd91e8da8ae6401fd0c0a2f62e513ab6906b0a4ff1fc410a3684350326bd7`，block `23981564`）
    - `0xfe4bce4b...` → `0xc328dfcd...`：`1,858.961517347711953662 RESOLV`
    - `0x502f9f85...` → `0xc328dfcd...`：`129,687 RESOLV`
  - `2025-12-10 13:58:11`（tx：`0x96276912a0ff27e2f124238112c5c2fe6b1f50fed07c567678f6cef7c30da442`，block `23980387`）
    - `0xc328dfcd...` → `0x8270400d...`：`119,530.333333333333333333 RESOLV`
  - `2025-12-10 18:00:23`（tx：`0xe57b5b5bf1bcfb741720b8b6ca91936802e3fef461a0c34569bbe490e8d8263e`，block `23981577`）
    - `0xc328dfcd...` → `0x8270400d...`：`131,545.961517347711953662 RESOLV`
- `0xc328dfcd2c8450e2487a91daa9b75629075b7a43` 也是 Gnosis Safe proxy（2/5 多签），且 owners 与 `0x8270400d...` 有显著重合。

> 所以，对“谁给 Pendle Merkle 发放池打钱”这个问题：在你关心的这次周期里，**直接出资地址**是 `0xeea6...`；而 `sENA/RESOLV` 的更上游（再往上追两跳）落在 `0x8270400d...` / `0xc328dfcd...` 这组多签与其上游的 token 侧合约地址上。

### 6.2 补差额路径：`AllMight 0x000...a3fc` 的 `sdPENDLE` 从哪来（先拿到 PENDLE → 再换/铸 sdPENDLE）

`AllMight 0x0000000a3fc396b89e4c11841b39d9dff85a5d05` 这部分“补差额”的 `sdPENDLE`，链上特征是：通常由 `0x90569d8a...` 这类执行者发起一笔“打包交易”，在同一 tx 里完成 **买 `PENDLE` → 转成 `sdPENDLE` → 转给 `Botmarket`**。

**关键中间件**

- `Curve PENDLE/sdPENDLE pool`：`0x26f3f26f46cbee59d1f8860865e13aa39e36a8c0`（`coins(0)=PENDLE 0x8085...`，`coins(1)=sdPENDLE 0x5ea6...`）
- `ParaSwap Augustus V6`：`0x6a000f20005980200259b80c5102003040001068`（verified）

**AllMight → Botmarket 的 4 次“补差额”对应的 PENDLE 来源**

- `2025-12-01 21:59:59`（tx：`0x9219b9df90065269706897a3ca56317c39436d029d96e65133ffc18815e56d58`）
  - `0x6a00...` → `AllMight`：`211.155000266240281641 PENDLE`
  - `AllMight` 在 `0x26f3...` 把 `PENDLE` 换成 `212.655686496179363578 sdPENDLE`，并在同 tx 里转给 `Botmarket`
- `2025-12-08 22:07:47`（tx：`0x32d59c6bf4eb83eee630b814be4e7c555598886eb565a17e13f16d9b01e1d74e`）
  - `0x6a00...` → `AllMight`：`118.474172226350103058 PENDLE`
  - 后续 `PENDLE`→`sdPENDLE` 并转 `Botmarket`：`130.637242379906717995 sdPENDLE`
- `2025-12-16 00:59:47`（tx：`0x1a6c56d0218c535e6f2af20ec36432f67d27f3b75648dd27d34836278677e4f0`）
  - `0xcf55...` → `AllMight`：`452.317987201427505152 PENDLE`
  - 后续 `PENDLE`→`sdPENDLE` 并转 `Botmarket`：`476.023205172301183667 sdPENDLE`
- `2025-12-22 18:06:47`（tx：`0xb03973035835b48037e216871b0e6675e5b9ea1211ce7f37615f4cae044cd8fd`）
  - `0x6a00...` → `AllMight`：`164.808290107408201131 PENDLE`
  - 通过 StakeDAO mint（`0x7f5c...`）直接铸成 `164.808290107408187392 sdPENDLE`，并转给 `Botmarket`

**这些 `PENDLE` 的买入资金（再往上追一跳）通常来自 `Botmarket` 自己的其它 token 库存**

- `0x9219b9df...`：`Botmarket` → `AllMight` 转入 `fxUSD 315.8197`、`RSUP 829.6393`，随后在同 tx 内被换成 `PENDLE` 再换成 `sdPENDLE`
- `0x32d59c6b...`：`Botmarket` → `AllMight` 转入 `fxUSD 289.0205`
- `0x1a6c56d0...`：`Botmarket` → `AllMight` 转入 `SDEX 396,264.8367`
- `0xb0397303...`：`Botmarket` → `AllMight` 转入 `fxUSD 311.5549`

> 因此，“谁在给 StakeDAO 的 Merkle 打钱”这件事可以拆成两类：  
> 1) `0x52ea...`：以 Pendle Merkle 奖励（`USDT/sENA/RESOLV`）为源头，链上换成 `PENDLE` 再铸 `sdPENDLE`；  
> 2) `AllMight`：通过路由器（`ParaSwap`/`0xcf55...`）先拿到 `PENDLE`，再通过 `Curve` 或 `mint` 变成 `sdPENDLE` 补差额进 `Botmarket`。 
