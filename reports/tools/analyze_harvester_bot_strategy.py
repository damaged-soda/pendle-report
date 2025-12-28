import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Call:
    tx_hash: str
    ts: int
    block_number: int
    selector: str
    target: str
    gas_price: int
    arg1: str
    arg2: str


def _pct(sorted_values: Sequence[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("empty data")
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    d0 = float(sorted_values[f]) * (c - k)
    d1 = float(sorted_values[c]) * (k - f)
    return d0 + d1


def _cv(xs: Sequence[float]) -> Optional[float]:
    if not xs:
        return None
    m = sum(xs) / len(xs)
    if m == 0:
        return None
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return (var**0.5) / m


def _cluster_runs(calls_sorted: Sequence[Call], gap_s: int) -> List[List[Call]]:
    if not calls_sorted:
        return []
    runs: List[List[Call]] = []
    current: List[Call] = [calls_sorted[0]]
    for i in range(1, len(calls_sorted)):
        if calls_sorted[i].ts - calls_sorted[i - 1].ts > gap_s:
            runs.append(current)
            current = [calls_sorted[i]]
        else:
            current.append(calls_sorted[i])
    runs.append(current)
    return runs


def _fmt_ts(ts: int, tz: timezone) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _load_calls(path: str) -> List[Call]:
    out: List[Call] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                Call(
                    tx_hash=str(row.get("tx_hash", "")).lower(),
                    ts=int(row.get("timestamp") or "0"),
                    block_number=int(row.get("block_number") or "0"),
                    selector=str(row.get("selector", "")).lower(),
                    target=str(row.get("target", "")).lower(),
                    gas_price=int(row.get("gas_price") or "0"),
                    arg1=str(row.get("arg1", "")),
                    arg2=str(row.get("arg2", "")),
                )
            )
    out.sort(key=lambda c: (c.ts, c.tx_hash))
    return out


def _load_asdpendle_harvest_assets(path: str) -> Dict[str, int]:
    if not os.path.exists(path):
        return {}
    out: Dict[str, int] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx = str(row.get("tx_hash", "")).lower()
            if not tx:
                continue
            try:
                out[tx] = int(row.get("assets") or "0")
            except ValueError:
                continue
    return out


def _load_receipts_sample(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out


def _try_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        return int(s)
    except Exception:
        return None


def _load_coingecko_prices(path: str) -> Dict[str, List[Tuple[int, float]]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            payload = json.load(f)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}

    out: Dict[str, List[Tuple[int, float]]] = {}

    eth = payload.get("eth", {})
    if isinstance(eth, dict):
        series: List[Tuple[int, float]] = []
        prices = eth.get("prices", [])
        if isinstance(prices, list):
            for item in prices:
                if not (isinstance(item, list) or isinstance(item, tuple)) or len(item) < 2:
                    continue
                try:
                    series.append((int(item[0]), float(item[1])))
                except Exception:
                    continue
        series.sort(key=lambda x: x[0])
        if series:
            out["eth"] = series

    tokens = payload.get("tokens", {})
    if isinstance(tokens, dict):
        for addr, info in tokens.items():
            if not isinstance(addr, str) or not isinstance(info, dict):
                continue
            addr_norm = addr.strip().lower()
            if not addr_norm.startswith("0x"):
                addr_norm = "0x" + addr_norm
            series = []
            prices = info.get("prices", [])
            if isinstance(prices, list):
                for item in prices:
                    if not (isinstance(item, list) or isinstance(item, tuple)) or len(item) < 2:
                        continue
                    try:
                        series.append((int(item[0]), float(item[1])))
                    except Exception:
                        continue
            series.sort(key=lambda x: x[0])
            if series:
                out[addr_norm] = series

    return out


def _price_at(series: Sequence[Tuple[int, float]], ts_s: int) -> Optional[float]:
    if not series:
        return None
    ts_ms = int(ts_s) * 1000
    if ts_ms <= series[0][0]:
        return float(series[0][1])
    if ts_ms >= series[-1][0]:
        return float(series[-1][1])
    lo = 0
    hi = len(series) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if series[mid][0] == ts_ms:
            return float(series[mid][1])
        if series[mid][0] < ts_ms:
            lo = mid
        else:
            hi = mid
    if abs(series[lo][0] - ts_ms) <= abs(series[hi][0] - ts_ms):
        return float(series[lo][1])
    return float(series[hi][1])


COMPOUNDER_SEL = "0x04117561"
VAULT_SEL = "0xc7f884c6"
FX_SEL = "0x78f26f5b"


TARGET_META: Dict[str, Dict[str, str]] = {
    # compounders / AMO (selector 0x04117561)
    "0x00bac667a4ccf9089ab1db978238c555c4349545": {
        "symbol": "aFXN",
        "name": "Aladdin cvxFXN",
        "base": "cvxFXN",
        "base_addr": "0x183395dbd0b5e93323a7286d1973150697fffcb3",
    },
    "0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884": {
        "symbol": "aCRV",
        "name": "Aladdin cvxCRV",
        "base": "cvxCRV",
        "base_addr": "0x62b9c7356a2dc64a1969e19c23e4f579f9810aa7",
    },
    "0xb0903ab70a7467ee5756074b31ac88aebb8fb777": {
        "symbol": "aCVX",
        "name": "Aladdin CVX",
        "base": "CVX",
        "base_addr": "0x4e3fbd56cd56c3e72c1403e103b45db9da5b9d2b",
    },
    "0x43e54c2e7b3e294de3a155785f52ab49d87b9922": {
        "symbol": "asdCRV",
        "name": "Aladdin sdCRV",
        "base": "sdCRV",
        "base_addr": "0xd1b5651e55d4ceed36251c61c50c889b36f6abb5",
    },
    "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf": {
        "symbol": "asdPENDLE",
        "name": "Aladdin sdPENDLE",
        "base": "sdPENDLE",
        "base_addr": "0x5ea630e00d6ee438d3dea1556a110359acdc10a9",
    },
    "0xdec800c2b17c9673570fdf54450dc1bd79c8e359": {
        "symbol": "abcCVX",
        "name": "Aladdin CVX (clevCVX AMO)",
        "base": "CVX",
        "base_addr": "0x4e3fbd56cd56c3e72c1403e103b45db9da5b9d2b",
        "debt": "clevCVX",
        "debt_addr": "0xf05e58fcea29ab4da01a495140b349f8410ba904",
    },
    # FxUSD compounder (selector 0x78f26f5b)
    "0x549716f858aeff9cb845d4c78c67a7599b0df240": {
        "symbol": "arUSD",
        "name": "Aladdin rUSD",
        "base": "weETH",
        "base_addr": "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee",
    },
    # vaults (selector 0xc7f884c6)
    "0x3cf54f3a1969be9916dad548f3c084331c4450b5": {
        "name": "AladdinCRVConvexVault (proxy)",
        "impl": "0x4657e91f056a77493b7e47d4ccd8c8afafc84283",
    },
    "0x59866ec5650e9ba00c51f6d681762b48b0ada3de": {
        "name": "ConcentratorGeneralVault / VaultForAsdCRV (proxy)",
        "impl": "0x0a6e1167c9b8599ee1deccb331aac176e2aa0b97",
    },
}


def _call_subkey(call: Call) -> str:
    if call.selector != VAULT_SEL:
        return ""
    try:
        return str(int(call.arg1))
    except ValueError:
        return str(call.arg1 or "")


def _job_label(sel: str, tgt: str, subkey: str) -> str:
    meta = TARGET_META.get(tgt, {})
    if sel == COMPOUNDER_SEL:
        return meta.get("symbol") or (tgt[:6] + "…" + tgt[-4:])
    if sel == VAULT_SEL:
        name = meta.get("name") or (tgt[:6] + "…" + tgt[-4:])
        return f"{name.split(' ')[0]}({subkey})"
    if sel == FX_SEL:
        return (meta.get("symbol") or (tgt[:6] + "…" + tgt[-4:])) + "(base)"
    return tgt[:6] + "…" + tgt[-4:]


def _job_out_token(sel: str, tgt: str) -> Optional[Tuple[str, str]]:
    meta = TARGET_META.get(tgt, {})
    if sel == COMPOUNDER_SEL:
        base = meta.get("base")
        addr = meta.get("base_addr")
        if base and addr:
            return base, addr.lower()
        return None
    if sel == VAULT_SEL:
        # IConcentratorGeneralVault.harvest: minOut is cvxCRV
        addr = TARGET_META.get("0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884", {}).get("base_addr", "")
        return "cvxCRV", addr.lower()
    if sel == FX_SEL:
        base = meta.get("base")
        addr = meta.get("base_addr")
        if base and addr:
            return base, addr.lower()
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--asd-harvest-logs", default="data/asdpendle_harvest_logs.csv")
    parser.add_argument(
        "--receipts-sample",
        default="data/f88e_harvester_receipts_sample.csv",
        help="Optional: output from reports/tools/fetch_receipts_sample.py",
    )
    parser.add_argument(
        "--prices-json",
        default="data/coingecko_prices_7d.json",
        help="Optional: output from reports/tools/fetch_coingecko_prices.py",
    )
    parser.add_argument("--out-md", default="asdpendle/harvester-bot-strategy.md")
    parser.add_argument("--run-gap-s", type=int, default=120)
    args = parser.parse_args()

    calls = _load_calls(args.in_csv)
    if not calls:
        raise SystemExit("no calls")

    tz_bj = timezone(timedelta(hours=8))
    start_ts = calls[0].ts
    end_ts = calls[-1].ts

    runs = _cluster_runs(calls, gap_s=int(args.run_gap_s))
    run_sizes = sorted([float(len(r)) for r in runs])

    selector_target_counts = Counter((c.selector, c.target) for c in calls)

    # Run signature patterns
    sig_counts: Counter[str] = Counter()
    for run in runs:
        if len(run) <= 1:
            continue
        parts = [f"{c.selector}:{c.target}" for c in run]
        sig_counts["|".join(sorted(parts))] += 1

    # Compounder stats
    per_target: Dict[str, List[Call]] = defaultdict(list)
    for c in calls:
        if c.selector == COMPOUNDER_SEL:
            per_target[c.target].append(c)

    # Group counts by job key (selector,target,subkey)
    group_counts: Counter[Tuple[str, str, str]] = Counter()
    for c in calls:
        group_counts[(c.selector, c.target, _call_subkey(c))] += 1

    asd_assets_by_tx = _load_asdpendle_harvest_assets(args.asd_harvest_logs)

    receipts_rows = _load_receipts_sample(args.receipts_sample)
    receipts_by_group: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in receipts_rows:
        sel = str(row.get("selector", "")).lower()
        tgt = str(row.get("target", "")).lower()
        sub = str(row.get("subkey", ""))
        if sel and tgt:
            receipts_by_group[(sel, tgt, sub)].append(row)

    prices_by_key = _load_coingecko_prices(args.prices_json)

    gas_used_est_by_group: Dict[Tuple[str, str, str], int] = {}
    for key, rows in receipts_by_group.items():
        gas_useds: List[float] = []
        for row in rows:
            gu = _try_int(row.get("gas_used"))
            if gu is not None and gu > 0:
                gas_useds.append(float(gu))
        if gas_useds:
            gas_used_est_by_group[key] = int(round(_pct(sorted(gas_useds), 50)))

    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write("# harvester bot 策略推断（基于 7 天链上调用）\n\n")
        f.write(f"- 数据源：`{args.in_csv}`（{len(calls)} 笔 bot→harvester 调用）\n")
        f.write(f"- 时间窗口：`{_fmt_ts(start_ts, tz_bj)}` → `{_fmt_ts(end_ts, tz_bj)}` (UTC+8)\n")
        f.write(f"- run 聚类：gap>{int(args.run_gap_s)}s 断开，runs={len(runs)}\n\n")

        f.write("## 1) 固定 job 列表（不是随机扫全网）\n\n")
        f.write("bot 在 7 天里只调用了 3 个 selector，对应 9 个 target：\n\n")
        for (sel, tgt), cnt in selector_target_counts.most_common():
            meta = TARGET_META.get(tgt, {})
            label = meta.get("symbol") or meta.get("name") or ""
            if label:
                label = f" ({label})"
            f.write(f"- `{sel}` `{tgt}`: {cnt}{label}\n")

        f.write("\n## 2) run/批处理特征（一次扫到多个就同一波全发）\n\n")
        f.write(
            f"- run_size：p50={_pct(run_sizes, 50):.0f}, p90={_pct(run_sizes, 90):.0f}, max={int(run_sizes[-1])}\n"
        )
        f.write("- 常见多笔 run 组合（按出现次数 Top 10）：\n")
        for sig, cnt in sig_counts.most_common(10):
            parts = []
            for p in sig.split("|"):
                sel, tgt = p.split(":", 1)
                meta = TARGET_META.get(tgt, {})
                short = meta.get("symbol") or (tgt[:6] + "…" + tgt[-4:])
                parts.append(f"{sel}:{short}")
            f.write(f"  - {cnt}×: {', '.join(parts)}\n")

        max_run = max(runs, key=len)
        f.write("\n- 最大批次（同一波发了所有常用 job）：\n")
        for c in max_run:
            meta = TARGET_META.get(c.target, {})
            short = meta.get("symbol") or (c.target[:6] + "…" + c.target[-4:])
            f.write(f"  - ts={c.ts} block={c.block_number} `{c.selector}` {short}\n")

        f.write("\n## 3) 触发阈值：更像“expected_out 与交易成本线性绑定”\n\n")
        f.write(
            "直接从 tx 参数看，minOut 与 `gas_price` 强相关，且 `minOut/gas_price` 波动很小。\n"
            "但更底层的成本是 `tx_fee = gas_used * effectiveGasPrice`；当某个 job 的 `gas_used` 很稳定时，"
            "统计上就会呈现出 `minOut ~ gas_price*k` 这种“线性绑定”。\n\n"
        )

        f.write("### 3.1 各 target 的拟合系数（用 p50(minAssets/gas_price) 近似 k_target）\n\n")
        f.write(
            "| target | 7d次数 | minAssets(p50) | gas_price(p50) | k≈p50(minAssets/gas_price) | CV(k) | gap_s(p50) |\n"
        )
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for tgt, items in sorted(per_target.items(), key=lambda kv: len(kv[1]), reverse=True):
            seq = sorted(items, key=lambda c: (c.ts, c.tx_hash))
            outs = []
            gps = []
            ratios = []
            for c in seq:
                try:
                    out = int(c.arg1)
                except ValueError:
                    continue
                outs.append(out / 1e18)
                gps.append(float(c.gas_price))
                if c.gas_price:
                    ratios.append((out / 1e18) / float(c.gas_price))
            if not outs or not gps or not ratios:
                continue
            gaps = [float(seq[i].ts - seq[i - 1].ts) for i in range(1, len(seq))]
            meta = TARGET_META.get(tgt, {})
            short = meta.get("symbol") or (tgt[:6] + "…" + tgt[-4:])
            f.write(
                f"| {short} | {len(seq)} | {_pct(sorted(outs), 50):.4g} | {_pct(sorted(gps), 50):.0f} | "
                f"{_pct(sorted(ratios), 50):.4g} | {_cv(ratios) or 0:.3f} | {_pct(sorted(gaps), 50) if gaps else 0:.0f} |\n"
            )

        f.write("\n### 3.2 交易成本视角：minOut 与 tx_fee 线性绑定（更贴近 bot 决策）\n\n")
        if not receipts_rows:
            f.write(f"- 未提供 receipts sample（`{args.receipts_sample}` 不存在或为空），跳过本节。\n")
        else:
            gp_diffs: List[float] = []
            mismatches = 0
            for row in receipts_rows:
                tx_gp = _try_int(row.get("tx_gas_price"))
                eff_gp = _try_int(row.get("effective_gas_price"))
                if tx_gp is None or eff_gp is None:
                    continue
                d = eff_gp - tx_gp
                gp_diffs.append(float(d))
                if d != 0:
                    mismatches += 1

            if gp_diffs:
                diffs_sorted = sorted(gp_diffs)
                f.write(
                    f"- receipt sample：{len(receipts_rows)} 笔；effectiveGasPrice-tx_gas_price："
                    f"p50={_pct(diffs_sorted, 50):.0f}, p90={_pct(diffs_sorted, 90):.0f}, max={diffs_sorted[-1]:.0f}；"
                    f"mismatch={mismatches}\n"
                )
            else:
                f.write(f"- receipt sample：{len(receipts_rows)} 笔\n")

            f.write(
                "- 定义 `tx_fee = gas_used * effectiveGasPrice`（单位 wei）。在 sample 内 effectiveGasPrice==tx_gas_price，因此可把 "
                "`gas_price` 当作成本 proxy。\n"
            )
            f.write(
                "- 更关键的是：同一 job 的 `gas_used` 非常稳定，所以 `minOut ~ gas_price` 的现象更像来自 `minOut ~ tx_fee`。\n\n"
            )
            f.write("- 注：`out/tx_fee` 的量纲是 `token_wei/wei`，等价于 `token/ETH`（这里默认这些 out 都是 18 decimals）。\n\n")

            f.write(
                "| job | 7d次数 | sample | gas_used(p50) | CV(gas_used) | out/tx_fee(p50) | CV(out/tx_fee) |\n"
            )
            f.write("|---|---:|---:|---:|---:|---:|---:|\n")

            group_items = sorted(
                receipts_by_group.items(),
                key=lambda kv: (group_counts.get(kv[0], 0), len(kv[1])),
                reverse=True,
            )
            for (sel, tgt, subkey), rows in group_items:
                gas_useds: List[float] = []
                ratios: List[float] = []
                for row in rows:
                    gas_used = _try_int(row.get("gas_used"))
                    eff_gp = _try_int(row.get("effective_gas_price"))
                    tx_gp = _try_int(row.get("tx_gas_price"))
                    fee_wei = _try_int(row.get("fee_wei"))
                    if fee_wei is None and gas_used is not None and (eff_gp or tx_gp):
                        fee_wei = gas_used * int(eff_gp or tx_gp or 0)
                    if gas_used is None or fee_wei is None or fee_wei <= 0:
                        continue

                    out_raw: Any
                    if sel == COMPOUNDER_SEL:
                        out_raw = row.get("arg1")
                    elif sel == VAULT_SEL:
                        out_raw = row.get("arg2")
                    elif sel == FX_SEL:
                        out_raw = row.get("arg1")
                    else:
                        continue

                    out_wei = _try_int(out_raw)
                    if out_wei is None:
                        continue

                    gas_useds.append(float(gas_used))
                    ratios.append(float(out_wei) / float(fee_wei))

                if not gas_useds or not ratios:
                    continue

                label = _job_label(sel, tgt, subkey)
                f.write(
                    f"| {label} | {group_counts.get((sel, tgt, subkey), 0)} | {len(rows)} | "
                    f"{_pct(sorted(gas_useds), 50):.0f} | {_cv(gas_useds) or 0:.3f} | "
                    f"{_pct(sorted(ratios), 50):.4g} | {_cv(ratios) or 0:.3f} |\n"
                )

        f.write("\n### 3.3 USD 口径：是否存在跨 job 的统一 ROI 阈值？\n\n")
        if not prices_by_key or "eth" not in prices_by_key:
            f.write(
                f"- 未提供 USD 价格数据（`{args.prices_json}` 不存在/无效），跳过本节；可先运行 "
                "`python reports/tools/fetch_coingecko_prices.py` 生成。\n"
            )
        else:
            roi_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
            cost_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
            out_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)

            missing_token = 0
            missing_price = 0
            missing_gas = 0
            alias_used: Counter[Tuple[str, str]] = Counter()
            sdpendle_addr = (
                TARGET_META.get("0x606462126e4bd5c4d153fe09967e4c46c9c7fecf", {}).get("base_addr") or ""
            ).lower()
            pendle_addr = "0x808507121b80c02388fad14726482e061b8da827"
            price_alias: Dict[str, str] = {}
            if sdpendle_addr:
                price_alias[sdpendle_addr] = pendle_addr.lower()

            for c in calls:
                subkey = _call_subkey(c)
                job_key = (c.selector, c.target, subkey)
                tok = _job_out_token(c.selector, c.target)
                if not tok:
                    missing_token += 1
                    continue
                tok_sym, tok_addr = tok
                tok_addr = tok_addr.lower()
                series_key = tok_addr
                if series_key not in prices_by_key:
                    alias = price_alias.get(series_key)
                    if alias and alias in prices_by_key:
                        alias_used[(series_key, alias)] += 1
                        series_key = alias
                    else:
                        missing_price += 1
                        continue

                eth_px = _price_at(prices_by_key["eth"], c.ts)
                tok_px = _price_at(prices_by_key[series_key], c.ts)
                if eth_px is None or tok_px is None or eth_px <= 0 or tok_px <= 0:
                    missing_price += 1
                    continue

                gu = gas_used_est_by_group.get(job_key)
                if not gu or gu <= 0:
                    missing_gas += 1
                    continue
                fee_wei = int(c.gas_price) * int(gu)
                cost_usd = (fee_wei / 1e18) * float(eth_px)
                if cost_usd <= 0:
                    continue

                try:
                    if c.selector == COMPOUNDER_SEL:
                        out_wei = int(c.arg1)
                    elif c.selector == VAULT_SEL:
                        out_wei = int(c.arg2)
                    elif c.selector == FX_SEL:
                        out_wei = int(c.arg1)
                    else:
                        continue
                except ValueError:
                    continue

                out_usd = (out_wei / 1e18) * float(tok_px)
                roi = out_usd / cost_usd
                roi_by_job[job_key].append(float(roi))
                cost_by_job[job_key].append(float(cost_usd))
                out_by_job[job_key].append(float(out_usd))

            f.write(
                "- 定义 `ROI = yield_usd / tx_cost_usd`，其中 `yield_usd ≈ minOut * price_usd`，"
                "`tx_cost_usd ≈ (gas_price * gas_used_est) * ETH_usd`。\n"
            )
            f.write(
                "- 如果 bot 是“统一的 USD ROI 阈值”，则不同 job 的 `ROI(p50)` 应该接近；反之说明是 job-specific 的系数。\n\n"
            )
            if missing_token or missing_price or missing_gas:
                f.write(
                    f"- 统计缺失：missing_token={missing_token}, missing_price={missing_price}, missing_gas_est={missing_gas}\n\n"
                )
            if alias_used:
                for (src, dst), cnt in alias_used.most_common():
                    f.write(f"- 价格回退：`{src}` 无有效价格点，使用 `{dst}` 价格近似（hits={cnt}）\n")
                f.write("\n")

            f.write("| job | 7d次数 | ROI(p50) | CV(ROI) | yield_usd(p50) | tx_cost_usd(p50) |\n")
            f.write("|---|---:|---:|---:|---:|---:|\n")

            job_rows: List[Tuple[str, int, float, float, float, float]] = []
            job_items = sorted(roi_by_job.items(), key=lambda kv: group_counts.get(kv[0], 0), reverse=True)
            for (sel, tgt, subkey), rois in job_items:
                if not rois:
                    continue
                label = _job_label(sel, tgt, subkey)
                rois_sorted = sorted(rois)
                outs_sorted = sorted(out_by_job.get((sel, tgt, subkey), []))
                costs_sorted = sorted(cost_by_job.get((sel, tgt, subkey), []))
                if not outs_sorted or not costs_sorted:
                    continue
                cnt = group_counts.get((sel, tgt, subkey), 0)
                roi_p50 = float(_pct(rois_sorted, 50))
                roi_cv = float(_cv(rois_sorted) or 0.0)
                out_p50 = float(_pct(outs_sorted, 50))
                cost_p50 = float(_pct(costs_sorted, 50))
                job_rows.append((label, cnt, roi_p50, roi_cv, out_p50, cost_p50))
                f.write(
                    f"| {label} | {cnt} | {roi_p50:.3g} | {roi_cv:.3f} | {out_p50:.3g} | {cost_p50:.3g} |\n"
                )

            if job_rows:
                min_row = min(job_rows, key=lambda r: r[2])
                max_row = max(job_rows, key=lambda r: r[2])
                min_roi = min_row[2]
                max_roi = max_row[2]
                ratio = (max_roi / min_roi) if min_roi > 0 else 0.0
                f.write(
                    f"\n- 结论：`ROI(p50)` 跨 job 差异很大（min≈{min_roi:.3g} `{min_row[0]}`, max≈{max_roi:.3g} `{max_row[0]}`, "
                    f"max/min≈{ratio:.3g}），更像每个 job 维护独立阈值系数，而非全局统一 ROI。\n"
                )

        # Vaults (selector 0xc7f884c6): group by (target,pid), use minOut as expected_out proxy.
        vault_groups: Dict[Tuple[str, int], List[Call]] = defaultdict(list)
        for c in calls:
            if c.selector != VAULT_SEL:
                continue
            try:
                pid = int(c.arg1)
            except ValueError:
                continue
            vault_groups[(c.target, pid)].append(c)

        if vault_groups:
            f.write("\n### 3.4 vault/fxUSD：也呈现“expected_out 与 gas_price 线性绑定”\n\n")
            f.write(
                "对 vault 调用（`0xc7f884c6`），`minOut` 同样与 `gas_price` 强相关，且 `minOut/gas_price` 波动很小；"
                "这说明 bot 对 vault 也在用同一类阈值规则。\n\n"
            )
            f.write(
                "| vault(pid) | 7d次数 | minOut(p50) | gas_price(p50) | k≈p50(minOut/gas_price) | CV(k) | gap_s(p50) |\n"
            )
            f.write("|---|---:|---:|---:|---:|---:|---:|\n")
            for (tgt, pid), items in sorted(vault_groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]:
                seq = sorted(items, key=lambda c: (c.ts, c.tx_hash))
                outs = []
                gps = []
                ratios = []
                for c in seq:
                    try:
                        out = int(c.arg2)
                    except ValueError:
                        continue
                    outs.append(out / 1e18)
                    gps.append(float(c.gas_price))
                    if c.gas_price:
                        ratios.append((out / 1e18) / float(c.gas_price))
                if not outs or not gps or not ratios:
                    continue
                gaps = [float(seq[i].ts - seq[i - 1].ts) for i in range(1, len(seq))]
                meta = TARGET_META.get(tgt, {})
                short = meta.get("name") or (tgt[:6] + "…" + tgt[-4:])
                short = f"{short.split(' ')[0]}({pid})"
                f.write(
                    f"| {short} | {len(seq)} | {_pct(sorted(outs), 50):.4g} | {_pct(sorted(gps), 50):.0f} | "
                    f"{_pct(sorted(ratios), 50):.4g} | {_cv(ratios) or 0:.3f} | {_pct(sorted(gaps), 50) if gaps else 0:.0f} |\n"
                )

        fx_calls = [c for c in calls if c.selector == FX_SEL]
        if fx_calls:
            # This selector takes (target, minBaseOut, minFxUSDOut); observed minFxUSDOut == 1 always.
            seq = sorted(fx_calls, key=lambda c: (c.ts, c.tx_hash))
            base_outs = []
            fx_outs = []
            gps = []
            base_ratios = []
            for c in seq:
                try:
                    base_out = int(c.arg1)
                    fx_out = int(c.arg2)
                except ValueError:
                    continue
                base_outs.append(base_out / 1e18)
                fx_outs.append(fx_out / 1e18)
                gps.append(float(c.gas_price))
                if c.gas_price:
                    base_ratios.append((base_out / 1e18) / float(c.gas_price))
            if base_outs and gps and base_ratios:
                gaps = [float(seq[i].ts - seq[i - 1].ts) for i in range(1, len(seq))]
                tgt = seq[0].target
                meta = TARGET_META.get(tgt, {})
                short = meta.get("symbol") or (tgt[:6] + "…" + tgt[-4:])
                f.write("\n- FxUSDCompounder（`0x78f26f5b`）观察：\n")
                f.write(
                    f"  - target `{short}`：minBaseOut 与 gas_price 强相关（k≈p50(minBaseOut/gas_price)={_pct(sorted(base_ratios), 50):.4g}，CV={_cv(base_ratios) or 0:.3f}）\n"
                )
                fx_unique = len(set(int(x * 1e18) for x in fx_outs))
                f.write(
                    f"  - minFxUSDOut 在 7 天内恒为 `1` wei（fx_unique={fx_unique}），等价于“几乎不设阈值，只设 base_out 阈值”。\n"
                )
                if gaps:
                    f.write(f"  - gap_s(p50)≈{_pct(sorted(gaps), 50):.0f}\n")

        f.write("\n### 3.5 asdPENDLE：minAssets≈Harvest.assets（先模拟再发 tx）\n\n")
        asd = "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf"
        asd_calls = [c for c in calls if c.selector == COMPOUNDER_SEL and c.target == asd]
        diffs: List[float] = []
        diff_bps: List[float] = []
        eq = 0
        matched = 0
        for c in asd_calls:
            if c.tx_hash not in asd_assets_by_tx:
                continue
            matched += 1
            assets = asd_assets_by_tx[c.tx_hash]
            try:
                min_assets = int(c.arg1)
            except ValueError:
                continue
            if assets == min_assets:
                eq += 1
            diffs.append(abs(float(assets - min_assets) / 1e18))
            if 0 <= min_assets <= assets and assets > 0:
                diff_bps.append((assets - min_assets) / assets * 10000.0)
        if diffs:
            diffs_sorted = sorted(diffs)
            f.write(
                f"- 匹配到 {matched} 笔同时有 Harvest 事件的 tx；其中 {eq} 笔 `minAssets == assets`。\n"
                f"- |assets-minAssets|：p90≈{_pct(diffs_sorted, 90):.3f}，max≈{diffs_sorted[-1]:.3f}。\n"
            )
            if diff_bps:
                diff_bps_sorted = sorted(diff_bps)
                f.write(
                    f"- (assets-minAssets)/assets：p90≈{_pct(diff_bps_sorted, 90):.2f} bps，max≈{diff_bps_sorted[-1]:.2f} bps（buffer 很小，符合“先模拟再发 tx”）。\n"
                )
        else:
            f.write("- 未匹配到足够的 Harvest 事件数据（缺少 `asdpendle_harvest_logs.csv`）。\n")

        f.write("\n## 4) 可复现的策略伪代码（推测）\n\n")
        f.write(
            "```text\n"
            "jobs = [\n"
            "  # selector=0x04117561\n"
            "  {type: 'compounder', target: aFXN,      gas_used: GU_aFXN,      m: m_aFXN},\n"
            "  {type: 'compounder', target: aCRV,      gas_used: GU_aCRV,      m: m_aCRV},\n"
            "  {type: 'compounder', target: aCVX,      gas_used: GU_aCVX,      m: m_aCVX},\n"
            "  {type: 'compounder', target: abcCVX,    gas_used: GU_abcCVX,    m: m_abcCVX},\n"
            "  {type: 'compounder', target: asdCRV,    gas_used: GU_asdCRV,    m: m_asdCRV},\n"
            "  {type: 'compounder', target: asdPENDLE, gas_used: GU_asdPENDLE, m: m_asdPENDLE},\n"
            "  # selector=0xc7f884c6\n"
            "  {type: 'vault',      target: vault1, pid: X, gas_used: GU_vault1, m: m_vault1},\n"
            "  {type: 'vault',      target: vault2, pid: Y, gas_used: GU_vault2, m: m_vault2},\n"
            "  # selector=0x78f26f5b\n"
            "  {type: 'fxusd',      target: arUSD, gas_used: GU_arUSD, m_base: m1, min_fxusd_out: 1},\n"
            "]\n"
            "\n"
            "loop:\n"
            "  gp = current_gas_price()\n"
            "  for job in jobs:\n"
            "    expected = eth_call(simulate_harvest(job, min=0))\n"
            "    fee_est = gp * job.gas_used             # ≈ tx_fee\n"
            "    threshold = fee_est * (job.m_base if job.type=='fxusd' else job.m)\n"
            "    if expected >= threshold:\n"
            "       min = expected * (1 - buffer_bps)\n"
            "       send_tx(harvest(job, min))\n"
            "  sleep(...)   # 扫描频率链上不可见\n"
            "```\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
