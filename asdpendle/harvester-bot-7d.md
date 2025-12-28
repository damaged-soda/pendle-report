# 机器人 harvester 调用行为（最近 7 天）

研究对象：
- bot: `0xf88e4e3db8ca35ebfd41076ec4bad483c9c4f805`
- harvester: `0xfa86aa141e45da5183b42792d99dede3d26ec515`

窗口（按 bot 最新交易回推 7 天）：
- start: `2025-12-20 17:43:11` (UTC+8)
- end: `2025-12-27 17:43:11` (UTC+8)

## 总览

- 7 天内对 harvester 的调用总数：**937**
- 相邻两笔 tx 时间差（秒）：p50=384, p75=900, p90=1506, p95=2019, p99=3401, max=22092
- 以 gap>120s 切 run：runs=658, run_size p50=1, p90=2, max=7; run_start_gap p50=660, p75=1140, p90=1733

## selector 分布

- `0x04117561`: 772
- `0xc7f884c6`: 132
- `0x78f26f5b`: 33

## Top targets（selector+target）

- `0x04117561` `0x00bac667a4ccf9089ab1db978238c555c4349545`: 206
- `0x04117561` `0xdec800c2b17c9673570fdf54450dc1bd79c8e359`: 160
- `0x04117561` `0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884`: 156
- `0x04117561` `0xb0903ab70a7467ee5756074b31ac88aebb8fb777`: 106
- `0x04117561` `0x43e54c2e7b3e294de3a155785f52ab49d87b9922`: 80
- `0xc7f884c6` `0x3cf54f3a1969be9916dad548f3c084331c4450b5`: 68
- `0xc7f884c6` `0x59866ec5650e9ba00c51f6d681762b48b0ada3de`: 64
- `0x04117561` `0x606462126e4bd5c4d153fe09967e4c46c9c7fecf`: 64
- `0x78f26f5b` `0x549716f858aeff9cb845d4c78c67a7599b0df240`: 33

## asdPENDLE（0x6064…）相关

- 7 天内 asdPENDLE harvest tx 数：**64**
- asdPENDLE harvest 间隔（秒）：p50=8460, p90=13123, max=25152
- Harvest.assets（asdPENDLE 计）：min=58.11, p50=70.21, p90=91.39, max=165.70
- corr(assets, gas_price) ≈ 0.986（gas_price 单位同 Etherscan 返回值）
- corr(gap, gas_price) ≈ 0.796；corr(gap, assets) ≈ 0.864（更像“gas 越贵就等更久/攒更多再 harvest”）
- `minAssets` 与 `Harvest.assets` 基本相等或略小（63 笔匹配中：52 笔完全相等；p90 绝对差≈0.009 asdPENDLE；最大≈0.115），符合“先 eth_call 预估再发 tx，并留一点 buffer 防止 revert”

## 推测的 bot 逻辑（基于链上可观测行为）

- bot 不是‘按固定时间点’ harvest asdPENDLE，而是更像：**高频扫描 + 触发阈值达标才发 tx**。
- asdPENDLE 看起来不规律：它的收益累积/可 harvest 额度增长慢，达标频率只有数小时一次；但 bot 同时还在对很多其它 target 执行 harvest，所以整体时间轴显得“乱”。
- 多笔 tx 同秒/短间隔出现，符合‘一次 run 扫描出多个达标 target，立即批量提交’的模式；run 之间出现长空窗，通常对应‘没有达标项’或‘外部条件（gas/节点/风控）变化’。
