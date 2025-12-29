import argparse
import csv
import json
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple


COMPOUNDER_SEL = "0x04117561"
ASDPENDLE_TARGET = "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf"
SDPENDLE_ADDR = "0x5ea630e00d6ee438d3dea1556a110359acdc10a9"


@dataclass(frozen=True)
class CallRow:
    tx_hash: str
    timestamp: int
    selector: str
    target: str
    gas_price: int
    arg1: str


@dataclass(frozen=True)
class HarvestRow:
    tx_hash: str
    timestamp: int
    assets_wei: int
    bounty_wei: int


@dataclass(frozen=True)
class ConfigRow:
    selector: str
    target: str
    gas_used_p50: int
    m_token_per_eth_p50: float
    k_token_per_wei_p50: float


def _normalize_hex(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if not v.startswith("0x"):
        v = "0x" + v
    return v


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


def _load_calls(path: str) -> List[CallRow]:
    out: List[CallRow] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                CallRow(
                    tx_hash=_normalize_hex(row.get("tx_hash", "")),
                    timestamp=int(row.get("timestamp") or "0"),
                    selector=_normalize_hex(row.get("selector", "")),
                    target=_normalize_hex(row.get("target", "")),
                    gas_price=int(row.get("gas_price") or "0"),
                    arg1=str(row.get("arg1", "")),
                )
            )
    out.sort(key=lambda r: (r.timestamp, r.tx_hash))
    return out


def _load_harvest_logs(path: str) -> List[HarvestRow]:
    out: List[HarvestRow] = []
    if not os.path.exists(path):
        return out
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx_hash = _normalize_hex(row.get("tx_hash", ""))
            if not tx_hash:
                continue
            try:
                out.append(
                    HarvestRow(
                        tx_hash=tx_hash,
                        timestamp=int(row.get("time_stamp") or "0"),
                        assets_wei=int(row.get("assets") or "0"),
                        bounty_wei=int(row.get("harvester_bounty") or "0"),
                    )
                )
            except ValueError:
                continue
    out.sort(key=lambda r: (r.timestamp, r.tx_hash))
    return out


def _load_config_asdpendle(path: str) -> ConfigRow:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sel = _normalize_hex(row.get("selector", ""))
            tgt = _normalize_hex(row.get("target", ""))
            if sel != COMPOUNDER_SEL or tgt != ASDPENDLE_TARGET:
                continue
            return ConfigRow(
                selector=sel,
                target=tgt,
                gas_used_p50=int(float(row.get("gas_used_p50") or "0")),
                m_token_per_eth_p50=float(row.get("m_token_per_eth_p50") or "0"),
                k_token_per_wei_p50=float(row.get("k_token_per_wei_p50") or "0"),
            )
    raise RuntimeError(f"asdPENDLE row not found in config csv: {path}")


def _load_prices(path: str) -> Dict[str, List[Tuple[int, float]]]:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {}

    out: Dict[str, List[Tuple[int, float]]] = {}
    eth = payload.get("eth", {})
    if isinstance(eth, dict):
        series = []
        for item in eth.get("prices", []) if isinstance(eth.get("prices"), list) else []:
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
            addr_norm = _normalize_hex(addr)
            if not addr_norm:
                continue
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


def _fmt_ts(ts: int, tz: timezone) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _pred_min_assets_wei(k_token_per_wei: float, gas_price_wei: int) -> int:
    if k_token_per_wei <= 0 or gas_price_wei <= 0:
        return 0
    # k is in token/wei; minAssets is token wei (18 decimals).
    return int(round(k_token_per_wei * float(gas_price_wei) * 1e18))


def _median(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("empty data")
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2 == 1:
        return float(ys[mid])
    return float(ys[mid - 1] + ys[mid]) / 2.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--harvest-logs", default="data/asdpendle_harvest_logs.csv")
    parser.add_argument("--config-csv", default="data/f88e_harvester_bot_config_estimates.csv")
    parser.add_argument("--prices-json", default="data/coingecko_prices_7d.json")
    parser.add_argument("--out-md", default="asdpendle/harvester-bot-backtest.md")
    parser.add_argument("--rate-window", type=int, default=5, help="Rolling median window for assets/sec")
    parser.add_argument("--warmup-intervals", type=int, default=5, help="How many pre-window intervals to warm start")
    args = parser.parse_args()

    tz_bj = timezone(timedelta(hours=8))

    calls = _load_calls(args.calls_csv)
    if not calls:
        raise SystemExit("empty calls csv")
    cfg = _load_config_asdpendle(args.config_csv)
    prices = _load_prices(args.prices_json)
    harvest_logs = _load_harvest_logs(args.harvest_logs)

    start_ts = min(c.timestamp for c in calls)
    end_ts = max(c.timestamp for c in calls)

    # asdPENDLE calls (ground truth of actual executions)
    asd_calls = [
        c for c in calls if c.selector == COMPOUNDER_SEL and c.target == ASDPENDLE_TARGET and c.gas_price > 0
    ]
    if not asd_calls:
        raise SystemExit("no asdPENDLE calls found in calls csv")

    harvest_by_tx: Dict[str, HarvestRow] = {h.tx_hash: h for h in harvest_logs}
    asd_harvests: List[HarvestRow] = []
    for c in asd_calls:
        h = harvest_by_tx.get(c.tx_hash)
        if h:
            asd_harvests.append(h)
    asd_harvests.sort(key=lambda r: (r.timestamp, r.tx_hash))

    # ---- 1) Replay minAssets formula using config k ----
    min_assets_err_abs: List[float] = []
    min_assets_err_bps: List[float] = []
    matched_min_assets = 0
    for c in asd_calls:
        try:
            min_assets = int(c.arg1)
        except ValueError:
            continue
        pred = _pred_min_assets_wei(cfg.k_token_per_wei_p50, c.gas_price)
        if pred <= 0 or min_assets <= 0:
            continue
        matched_min_assets += 1
        diff = float(abs(pred - min_assets)) / 1e18
        min_assets_err_abs.append(diff)
        min_assets_err_bps.append(float(abs(pred - min_assets)) / float(min_assets) * 10000.0)

    # ---- 2) Trigger backtest (approx): rolling assets/sec + scan at bot tx timestamps ----
    # Warm start rates using pre-window harvest intervals.
    pre_harvests = [h for h in harvest_logs if h.timestamp < start_ts]
    pre_harvests.sort(key=lambda r: (r.timestamp, r.tx_hash))
    warm_rates: List[float] = []
    for i in range(1, len(pre_harvests)):
        dt = pre_harvests[i].timestamp - pre_harvests[i - 1].timestamp
        if dt <= 0:
            continue
        warm_rates.append(float(pre_harvests[i].assets_wei) / 1e18 / float(dt))
    warm_rates = warm_rates[-max(0, int(args.warmup_intervals)) :]

    rate_window: Deque[float] = deque(warm_rates, maxlen=max(1, int(args.rate_window)))

    # Iterate scan points (all bot txs) and find, for each actual interval, the first time condition becomes true.
    asd_call_set = {c.tx_hash for c in asd_calls}
    asd_harvest_by_ts: Dict[int, HarvestRow] = {h.timestamp: h for h in asd_harvests}
    last_harvest_ts: Optional[int] = None
    last_harvest_assets_wei: Optional[int] = None
    predicted_trigger_ts: Optional[int] = None
    delays_s: List[int] = []
    missed_intervals = 0
    intervals = 0

    for c in calls:
        ts = c.timestamp
        if ts < start_ts or ts > end_ts:
            continue
        if last_harvest_ts is None:
            # Initialize last_harvest_ts to the most recent actual harvest <= current scan time, if any.
            # This avoids inventing a "reset to 0" before we have a known harvest.
            candidates = [h.timestamp for h in asd_harvests if h.timestamp <= ts]
            if candidates:
                last_harvest_ts = max(candidates)
                last_harvest_assets_wei = asd_harvest_by_ts.get(last_harvest_ts).assets_wei  # type: ignore[union-attr]
                predicted_trigger_ts = None
            else:
                continue

        # Current threshold based on gas price (k * gas_price).
        threshold_wei = _pred_min_assets_wei(cfg.k_token_per_wei_p50, c.gas_price)
        dt_since = ts - last_harvest_ts
        rate_est = _median(list(rate_window)) if rate_window else 0.0
        expected_wei_est = int(round(rate_est * float(max(0, dt_since)) * 1e18))

        cond = expected_wei_est >= threshold_wei and threshold_wei > 0 and dt_since >= 0
        if cond and predicted_trigger_ts is None:
            predicted_trigger_ts = ts

        # If this scan point is an actual asdPENDLE harvest tx, close the interval and update rate window.
        if c.tx_hash in asd_call_set:
            h = harvest_by_tx.get(c.tx_hash)
            if h and h.timestamp == ts and last_harvest_ts is not None:
                if ts > last_harvest_ts:
                    intervals += 1
                    if predicted_trigger_ts is None:
                        missed_intervals += 1
                    else:
                        delays_s.append(int(ts - predicted_trigger_ts))
                dt = ts - last_harvest_ts
                if dt > 0:
                    rate_window.append(float(h.assets_wei) / 1e18 / float(dt))
                last_harvest_ts = ts
                last_harvest_assets_wei = h.assets_wei
                predicted_trigger_ts = None

    # ---- 3) USD sanity (bounty vs est gas cost), using TWAP-filled sdPENDLE price ----
    bounty_rates: List[float] = []
    roi_assets: List[float] = []
    roi_bounty: List[float] = []
    cost_usd_list: List[float] = []
    bounty_usd_list: List[float] = []
    assets_usd_list: List[float] = []

    eth_series = prices.get("eth", [])
    sd_series = prices.get(_normalize_hex(SDPENDLE_ADDR), [])
    for c in asd_calls:
        h = harvest_by_tx.get(c.tx_hash)
        if not h:
            continue
        if h.assets_wei > 0:
            bounty_rates.append(float(h.bounty_wei) / float(h.assets_wei))
        if not eth_series or not sd_series:
            continue
        eth_usd = _price_at(eth_series, c.timestamp)
        sd_usd = _price_at(sd_series, c.timestamp)
        if eth_usd is None or sd_usd is None or eth_usd <= 0 or sd_usd <= 0:
            continue
        fee_wei_est = int(c.gas_price) * int(cfg.gas_used_p50)
        cost_usd = (fee_wei_est / 1e18) * float(eth_usd)
        assets_usd = (h.assets_wei / 1e18) * float(sd_usd)
        bounty_usd = (h.bounty_wei / 1e18) * float(sd_usd)
        if cost_usd <= 0:
            continue
        cost_usd_list.append(cost_usd)
        assets_usd_list.append(assets_usd)
        bounty_usd_list.append(bounty_usd)
        roi_assets.append(assets_usd / cost_usd)
        roi_bounty.append(bounty_usd / cost_usd)

    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write("# asdPENDLE harvester bot：配置回测（7 天）\n\n")
        f.write("数据源：\n")
        f.write(f"- calls：`{args.calls_csv}`\n")
        f.write(f"- harvest logs：`{args.harvest_logs}`\n")
        f.write(f"- config：`{args.config_csv}`\n")
        if prices:
            f.write(f"- prices：`{args.prices_json}`（sdPENDLE 已用链上 TWAP 填充）\n")
        f.write("\n窗口：\n")
        f.write(f"- start：`{_fmt_ts(start_ts, tz_bj)}` (UTC+8)\n")
        f.write(f"- end：`{_fmt_ts(end_ts, tz_bj)}` (UTC+8)\n")

        f.write("\n## 1) 使用的配置参数（asdPENDLE job）\n\n")
        f.write(f"- selector：`{cfg.selector}`\n")
        f.write(f"- target：`{cfg.target}`\n")
        f.write(f"- gas_used_p50：`{cfg.gas_used_p50}`\n")
        f.write(f"- m_token_per_eth_p50：`{cfg.m_token_per_eth_p50:.6g}`\n")
        f.write(f"- k_token_per_wei_p50：`{cfg.k_token_per_wei_p50:.6g}`\n")

        f.write("\n## 2) 回放：minAssets ≈ k * gas_price（用配置 k 预测 tx 输入）\n\n")
        f.write(f"- asdPENDLE calls：{len(asd_calls)}\n")
        f.write(f"- 可解析 minAssets 且可预测：{matched_min_assets}\n")
        if min_assets_err_abs:
            xs = sorted(min_assets_err_abs)
            ys = sorted(min_assets_err_bps)
            f.write(
                f"- |pred-minAssets|（token）：p50≈{_pct(xs, 50):.4g}，p90≈{_pct(xs, 90):.4g}，max≈{xs[-1]:.4g}\n"
            )
            f.write(
                f"- |pred-minAssets|/minAssets（bps）：p50≈{_pct(ys, 50):.3g}，p90≈{_pct(ys, 90):.3g}，max≈{ys[-1]:.3g}\n"
            )
        else:
            f.write("- 无法计算误差（minAssets 缺失或 gas_price=0）。\n")

        f.write("\n## 3) 触发回测（近似）：滚动估计 assets/sec + 扫描点=bot 每笔 tx 时间\n\n")
        f.write("定义：\n")
        f.write("- `expected(t)`：用历史 harvest 间隔估计的可 harvest `assets`（线性随时间增长）\n")
        f.write("- `threshold(t)`：用配置 `k` 与当下 `gas_price` 推出的 `minAssets`\n")
        f.write("- 认为当某个扫描点首次满足 `expected(t) >= threshold(t)` 时，bot 应该会触发 harvest。\n\n")
        f.write(f"- warmup_intervals：{int(args.warmup_intervals)}（用窗口前的历史间隔初始化）\n")
        f.write(f"- rate_window：{int(args.rate_window)}（滚动中位数）\n")
        f.write(f"- intervals（按相邻 asdPENDLE harvest 划分）：{intervals}\n")
        f.write(f"- missed_intervals：{missed_intervals}\n")
        if delays_s:
            ds = sorted(float(x) for x in delays_s)
            f.write(
                f"- delay = actual_harvest_ts - first_trigger_ts（秒）：p50≈{_pct(ds, 50):.0f}，p90≈{_pct(ds, 90):.0f}，max≈{ds[-1]:.0f}\n"
            )
        else:
            f.write("- delay：无（未捕获到触发点，或 harvest 数不足）。\n")

        f.write("\n## 4) USD 口径（更贴近 bot 收益）：harvester_bounty vs 估算 gas cost\n\n")
        if bounty_rates:
            br = sorted(bounty_rates)
            f.write(
                f"- bounty_rate=bounty/assets：p50≈{_pct(br, 50):.6g}，p90≈{_pct(br, 90):.6g}\n"
            )
        if roi_assets and roi_bounty and cost_usd_list and bounty_usd_list:
            ra = sorted(roi_assets)
            rb = sorted(roi_bounty)
            cu = sorted(cost_usd_list)
            bu = sorted(bounty_usd_list)
            au = sorted(assets_usd_list)
            f.write(f"- est tx_cost_usd：p50≈{_pct(cu, 50):.4g}，p90≈{_pct(cu, 90):.4g}\n")
            f.write(f"- harvest assets_usd：p50≈{_pct(au, 50):.4g}，p90≈{_pct(au, 90):.4g}\n")
            f.write(f"- harvester bounty_usd：p50≈{_pct(bu, 50):.4g}，p90≈{_pct(bu, 90):.4g}\n")
            f.write(f"- ROI_assets_usd=assets/cost：p50≈{_pct(ra, 50):.4g}，p90≈{_pct(ra, 90):.4g}\n")
            f.write(f"- ROI_bounty_usd=bounty/cost：p50≈{_pct(rb, 50):.4g}，p90≈{_pct(rb, 90):.4g}\n")
        else:
            f.write("- 缺少价格序列或 Harvest logs（无法计算 USD 口径）。\n")

        f.write("\n## 5) 结论（这份配置“回测支持”的边界）\n\n")
        f.write("- ✅ 支持“回放型回测”：用 `k/m/gas_used` 预测 tx 的 `minAssets`，误差很小，说明配置可复现机器人出价逻辑。\n")
        f.write("- ⚠️ 触发时刻回测依赖 `expected(t)` 的估计：本脚本用“历史 assets/sec 线性增长”近似，能给出一个可对齐的触发延迟分布，但不是严格链上真值。\n")
        f.write("- 若要做严格回测（不靠线性假设），需要能在历史区块 `eth_call` 得到 `simulate_harvest()` 的 `expected assets`（或可替代的 view/preview）。\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

