# 只抓「claim 把 `sdPENDLE` 转入 `burner`」的监听方案（最简）

> 如果你的目标只是“看到 `claim` 到账 burner 的那一下”，不需要 mempool。直接订阅链上日志即可。  
> 背景与链路解释见：`asdpendle/report.md`

---

## 1. 你要抓的到底是什么

`claim` 成功时，同一笔交易里会出现一条（或多条）ERC20 日志：

- `sdPENDLE.Transfer(from=?, to=SdPendleBribeBurner, amount)`

其中：

- `sdPENDLE`：`0x5ea630e00d6ee438d3dea1556a110359acdc10a9`
- `SdPendleBribeBurner`：`0x8bde1d771423b8d2fe0b046b934fb9a7f956ade2`
- `Transfer` topic0：`0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`

> 注意：这是 **mined 后的日志**，不是 pending；EVM 未执行前不存在“事件”。

---

## 2. WebSocket 订阅（eth_subscribe logs）

用任意支持 WSS 的以太坊节点（Alchemy/Infura/自建等）发：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "eth_subscribe",
  "params": [
    "logs",
    {
      "address": "0x5ea630e00d6ee438d3dea1556a110359acdc10a9",
      "topics": [
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        null,
        "0x0000000000000000000000008bde1d771423b8d2fe0b046b934fb9a7f956ade2"
      ]
    }
  ]
}
```

含义：

- `address=sdPENDLE`：只看 `sdPENDLE` 合约发出的日志
- `topics[0]=Transfer`：只看 `Transfer` 事件
- `topics[2]=to=burner`：只看转入 burner 的那部分 `Transfer`

收到的日志里：

- `topics[1]` 是 `from`（32 bytes padded address）
- `data` 是 `amount`（`uint256`）

---

## 3. “是不是 claim”的进一步筛选（可选）

仅用 `to=burner` 已经很接近你要的东西；如果你想更像“只抓 claim”，可以再做一层**本地**筛选：

- 白名单 `from`（例如你报告里常见的中转 `0x1c0d72a330f2768daf718def8a19bab019eead09`），或
- 结合同 tx 内的其它特征（例如同 tx 内还出现 `MultiMerkleStash` 的转出）。

> 不建议把 `from` 写死在 `topics[1]` 里：路径/中转地址未来可能变化；本地过滤更灵活。

---

## 4. 工程注意事项（别踩坑）

- **确认数 / reorg**：WSS 日志可能来自最新块；如果你要做重要动作，建议等 2~5 个确认。
- **重复消息**：重连/节点实现差异可能导致重复推送；用 `(blockHash, txHash, logIndex)` 去重。
- **只抓到“到账”**：`claim → burn` 往往只差几十秒，甚至可能同块发生；如果你想在两者之间做交易，靠日志通常来不及，需要改回抓 pending（mempool）。

