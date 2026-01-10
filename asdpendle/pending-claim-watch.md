# MVP：用 `alchemy_pendingTransactions` 抓「claim（harvestBribe）pending」

## 目标

只做最小可用：用 Alchemy WSS 订阅 pending 交易，先按 `toAddress=asdPENDLE` **粗筛**，再在本地按 `input selector` **细筛**，输出“疑似 claim pending”告警。

## 常量（ETH Mainnet）

- `asdPENDLE`：`0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`
- `harvestBribe((address,uint256,uint256,bytes32[]))` selector：`0x417e3310`

---

## 1) 订阅：粗筛（Alchemy 侧）

`alchemy_pendingTransactions` 支持按 `fromAddress/toAddress` 过滤 pending；为了后续细筛拿到 `input`，必须设置 `hashesOnly=false`。

### wscat 示例

先连 WSS（把 `YOUR_KEY` 换成你的 key）：

```bash
wscat -c wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
```

再发订阅请求：

```json
{"jsonrpc":"2.0","id":2,"method":"eth_subscribe","params":["alchemy_pendingTransactions",{"toAddress":["0x606462126e4bd5c4d153fe09967e4c46c9c7fecf"],"hashesOnly":false}]}
```

你会收到形如 `eth_subscription` 的推送，其中 `params.result` 是一笔 pending 交易对象（`to/from/nonce/input/gasPrice/...`）。

---

## 2) 细筛：本地按 selector 过滤

对每条推送的 pending tx，做一个最小判断：

- `tx.to.toLowerCase() == asdPENDLE`（防御性校验）
- `tx.input.startsWith("0x417e3310")` → 认为是目标「claim（harvestBribe）pending」

输出建议（MVP 够用）：

- `hash`, `from`, `nonce`, `gasPrice`（或 `maxFeePerGas/maxPriorityFeePerGas`）, `input.slice(0,10)`

---

## 3) 实用参数与限制（按 Alchemy 规则）

- **只覆盖 Alchemy mempool**：你只能收到“进入 Alchemy mempool 的 pending”。
- **网络支持**：`alchemy_pendingTransactions` 仅支持 `ETH Mainnet / ETH Sepolia / Matic Mainnet`（这里默认用 ETH Mainnet）。
- **地址数上限**：`fromAddress + toAddress` 合计最多 **1000 个唯一地址**。
- **`fromAddress` 与 `toAddress` 同时给时是 OR**：会返回 `fromAddress` 发出的 tx **或** `toAddress` 收到的 tx（不是 AND）。MVP 里只用 `toAddress=[asdPENDLE]` 最直观。
