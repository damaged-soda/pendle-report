# Pendle (0x808507121B80c02388fAd14726482e061B8da827) 研究报告

## 合约概览
- 主网普通合约（非代理），Solidity 0.7.6。
- ERC20：名称 Pendle，符号 PENDLE，18 位小数，支持 Compound 式投票委托/快照（delegate / delegateBySig / getPriorVotes）。
- 治理地址：0x8119ec16f0573b7dac7c0cb94eb504fb32456ee1；pendingGovernance 为空。
- 标识函数：isPendleToken() 返回 true。
- 燃烧开关：isBurningAllowed=false，未开启时 burn() 不可用。

## 部署与初始分配（区块 12320098，2021-04-27 03:59:03 UTC）
总初始铸造 188,700,000 PENDLE：
- 94,917,125 → 0x8849d0d4c35679aa78df1b5b4ceca358d57635df（团队）
-, 46,000,000 → 0xc21a74c7150fed22c7ca0bf9a15bbe0ddb4977cc（生态基金）
- 16,582,875 → 0x9b26afff63e4139cb5a3ea9955903ffffcc1d79b（销售多签）
- 31,200,000 → 0xe8d28e2ca24bb16fc7e6549ef937e05981d02606（流动性激励地址）

## 当前状态（最新块）
- totalSupply ≈ 281,527,448.4585 PENDLE；较初始新增约 92.83M 来自流动性激励。
- lastWeekEmissionSent = 204；lastWeeklyEmission ≈ 167,541.0182 PENDLE（最近一周发放额）。
- emissionRateMultiplierNumerator = 989000000000 / 1e12 → 0.989（周衰减系数，周 1–259 生效）。
- terminalInflationRateNumerator = 379848538 / 1e12 → 0.000379848538（周通胀率，约年化 2%，周 ≥260 生效）。
- liquidityIncentivesRecipient = 0xe8d28e2ca24bb16fc7e6549ef937e05981d02606；只有该地址可 claim 激励。
- configChangesInitiated = 0（无待应用参数变更）。

## 激励与通胀机制
- 按周结算（_getCurrentWeek = floor((block.timestamp - startTime)/7天) + 1，startTime=1619495943）。
- claimLiquidityEmissions：仅激励地址可调用，按未结算周数循环铸造：
  - 周 ≤259：本周铸造 = 上周铸造 × 0.989。
  - 周 ≥260：本周铸造 = totalSupply × 0.000379848538。
- applyConfigChanges 前会先结算旧配置下的所有待发激励，防止参数切换覆盖历史。

## 权限与管理
- 只有治理可：transferGovernance/claimGovernance、initiateConfigChanges → applyConfigChanges（带时间锁）、救援 ETH/任意 ERC20。
- 可调参数（需时间锁后生效）：周衰减系数、终端通胀率、激励接收地址、是否允许燃烧。
- 救援接口：withdrawEther / withdrawToken，接收任意目标地址。

## 数据来源（etherscan-mcp 工具）
- detect_proxy（判定非代理）。
- fetch_contract（ABI 与源码）。
- call_function：name/symbol/decimals/totalSupply/governance/pendingGovernance/emissionRateMultiplierNumerator/terminalInflationRateNumerator/lastWeeklyEmission/lastWeekEmissionSent/startTime/liquidityIncentivesRecipient/isBurningAllowed/configChangesInitiated。
- query_logs（部署区块 Transfer 事件解析初始分配）。
