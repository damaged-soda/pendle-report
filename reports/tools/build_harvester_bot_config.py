import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


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


PENDLE_ADDR = "0x808507121b80c02388fad14726482e061b8da827"


@dataclass(frozen=True)
class CallRow:
    tx_hash: str
    timestamp: int
    block_number: int
    selector: str
    target: str
    gas_price: int
    arg1: str
    arg2: str


@dataclass(frozen=True)
class ReceiptRow:
    selector: str
    target: str
    subkey: str
    timestamp: int
    arg1: str
    arg2: str
    tx_gas_price: int
    effective_gas_price: int
    gas_used: int


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


def _job_subkey_from_call(row: CallRow) -> str:
    if row.selector != VAULT_SEL:
        return ""
    try:
        return str(int(row.arg1))
    except ValueError:
        return str(row.arg1 or "")


def _job_subkey_from_receipt(row: ReceiptRow) -> str:
    return row.subkey or ""


def _job_key(selector: str, target: str, subkey: str) -> Tuple[str, str, str]:
    return selector.lower(), target.lower(), str(subkey or "")


def _job_label(selector: str, target: str, subkey: str) -> str:
    meta = TARGET_META.get(target, {})
    if selector == COMPOUNDER_SEL:
        return meta.get("symbol") or (target[:6] + "…" + target[-4:])
    if selector == VAULT_SEL:
        name = meta.get("name") or (target[:6] + "…" + target[-4:])
        return f"{name.split(' ')[0]}({subkey})"
    if selector == FX_SEL:
        return (meta.get("symbol") or (target[:6] + "…" + target[-4:])) + "(base)"
    return target[:6] + "…" + target[-4:]


def _job_type(selector: str) -> str:
    if selector == COMPOUNDER_SEL:
        return "compounder"
    if selector == VAULT_SEL:
        return "vault"
    if selector == FX_SEL:
        return "fxusd"
    return "unknown"


def _job_out_token(selector: str, target: str) -> Optional[Tuple[str, str]]:
    meta = TARGET_META.get(target, {})
    if selector == COMPOUNDER_SEL:
        sym = meta.get("base")
        addr = meta.get("base_addr")
        if sym and addr:
            return sym, addr.lower()
        return None
    if selector == VAULT_SEL:
        # harvest output is cvxCRV
        addr = TARGET_META.get("0x2b95a1dcc3d405535f9ed33c219ab38e8d7e0884", {}).get("base_addr", "")
        return "cvxCRV", addr.lower()
    if selector == FX_SEL:
        sym = meta.get("base")
        addr = meta.get("base_addr")
        if sym and addr:
            return sym, addr.lower()
        return None
    return None


def _call_out_wei(row: CallRow) -> Optional[int]:
    try:
        if row.selector == COMPOUNDER_SEL:
            return int(row.arg1)
        if row.selector == VAULT_SEL:
            return int(row.arg2)
        if row.selector == FX_SEL:
            return int(row.arg1)
    except ValueError:
        return None
    return None


def _receipt_out_wei(row: ReceiptRow) -> Optional[int]:
    try:
        if row.selector == COMPOUNDER_SEL:
            return int(row.arg1)
        if row.selector == VAULT_SEL:
            return int(row.arg2)
        if row.selector == FX_SEL:
            return int(row.arg1)
    except ValueError:
        return None
    return None


def _load_calls(path: str) -> List[CallRow]:
    out: List[CallRow] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                CallRow(
                    tx_hash=str(row.get("tx_hash", "")).lower(),
                    timestamp=int(row.get("timestamp") or "0"),
                    block_number=int(row.get("block_number") or "0"),
                    selector=str(row.get("selector", "")).lower(),
                    target=str(row.get("target", "")).lower(),
                    gas_price=int(row.get("gas_price") or "0"),
                    arg1=str(row.get("arg1", "")),
                    arg2=str(row.get("arg2", "")),
                )
            )
    out.sort(key=lambda r: (r.timestamp, r.tx_hash))
    return out


def _load_receipts(path: str) -> List[ReceiptRow]:
    out: List[ReceiptRow] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sel = str(row.get("selector", "")).lower()
            tgt = str(row.get("target", "")).lower()
            out.append(
                ReceiptRow(
                    selector=sel,
                    target=tgt,
                    subkey=str(row.get("subkey", "")),
                    timestamp=int(row.get("timestamp") or "0"),
                    arg1=str(row.get("arg1", "")),
                    arg2=str(row.get("arg2", "")),
                    tx_gas_price=int(row.get("tx_gas_price") or "0"),
                    effective_gas_price=int(row.get("effective_gas_price") or "0"),
                    gas_used=int(row.get("gas_used") or "0"),
                )
            )
    return out


def _load_prices(path: str) -> Dict[str, List[Tuple[int, float]]]:
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


def _fmt_ts(ts: int, tz: timezone) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--receipts-sample", default="data/f88e_harvester_receipts_sample.csv")
    parser.add_argument("--prices-json", default="data/coingecko_prices_7d.json")
    parser.add_argument("--out-md", default="asdpendle/harvester-bot-config.md")
    parser.add_argument("--out-csv", default="data/f88e_harvester_bot_config_estimates.csv")
    args = parser.parse_args()

    calls = _load_calls(args.calls_csv)
    receipts = _load_receipts(args.receipts_sample)
    prices = _load_prices(args.prices_json)

    tz_bj = timezone(timedelta(hours=8))
    start_ts = min(c.timestamp for c in calls) if calls else 0
    end_ts = max(c.timestamp for c in calls) if calls else 0

    job_counts: Counter[Tuple[str, str, str]] = Counter()
    job_ts: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
    for c in calls:
        key = _job_key(c.selector, c.target, _job_subkey_from_call(c))
        job_counts[key] += 1
        job_ts[key].append(c.timestamp)

    # Call-level k := out_token/gas_price (token/wei), using tx arg as proxy.
    k_token_per_wei_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    for c in calls:
        out_wei = _call_out_wei(c)
        if out_wei is None or c.gas_price <= 0:
            continue
        key = _job_key(c.selector, c.target, _job_subkey_from_call(c))
        k_token_per_wei_by_job[key].append((out_wei / 1e18) / float(c.gas_price))

    # Receipt-level gas_used + m := out_wei/fee_wei (token/ETH)
    gas_used_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    m_token_per_eth_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    for r in receipts:
        fee_wei = int(r.gas_used) * int(r.effective_gas_price or r.tx_gas_price)
        if fee_wei <= 0:
            continue
        out_wei = _receipt_out_wei(r)
        if out_wei is None or out_wei <= 0:
            continue
        key = _job_key(r.selector, r.target, _job_subkey_from_receipt(r))
        gas_used_by_job[key].append(float(r.gas_used))
        m_token_per_eth_by_job[key].append(float(out_wei) / float(fee_wei))

    gas_used_p50: Dict[Tuple[str, str, str], int] = {}
    for key, xs in gas_used_by_job.items():
        if xs:
            gas_used_p50[key] = int(round(_pct(sorted(xs), 50)))

    # USD ROI (call-level), cost_usd uses gas_used_p50 as estimate.
    roi_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    yield_usd_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    cost_usd_by_job: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    price_alias_used: Counter[Tuple[str, str]] = Counter()

    if prices and "eth" in prices:
        sdpendle_addr = TARGET_META.get("0x606462126e4bd5c4d153fe09967e4c46c9c7fecf", {}).get("base_addr", "")
        alias_map: Dict[str, str] = {}
        if sdpendle_addr:
            alias_map[sdpendle_addr.lower()] = PENDLE_ADDR.lower()

        for c in calls:
            key = _job_key(c.selector, c.target, _job_subkey_from_call(c))
            gu = gas_used_p50.get(key)
            if not gu or gu <= 0 or c.gas_price <= 0:
                continue
            out_wei = _call_out_wei(c)
            if out_wei is None or out_wei <= 0:
                continue
            token = _job_out_token(c.selector, c.target)
            if not token:
                continue
            _sym, addr = token
            addr = addr.lower()
            series_key = addr
            if series_key not in prices:
                alias = alias_map.get(series_key)
                if alias and alias in prices:
                    price_alias_used[(series_key, alias)] += 1
                    series_key = alias
                else:
                    continue
            eth_px = _price_at(prices["eth"], c.timestamp)
            tok_px = _price_at(prices[series_key], c.timestamp)
            if eth_px is None or tok_px is None or eth_px <= 0 or tok_px <= 0:
                continue
            fee_wei = int(c.gas_price) * int(gu)
            cost_usd = (fee_wei / 1e18) * float(eth_px)
            out_usd = (out_wei / 1e18) * float(tok_px)
            if cost_usd <= 0:
                continue
            roi_by_job[key].append(float(out_usd / cost_usd))
            yield_usd_by_job[key].append(float(out_usd))
            cost_usd_by_job[key].append(float(cost_usd))

    # Build config rows
    rows: List[Dict[str, Any]] = []
    for key, cnt in sorted(job_counts.items(), key=lambda kv: kv[1], reverse=True):
        sel, tgt, sub = key
        label = _job_label(sel, tgt, sub)
        token = _job_out_token(sel, tgt)
        token_sym = token[0] if token else ""
        token_addr = token[1] if token else ""

        # gaps
        ts_list = sorted(job_ts.get(key, []))
        gaps = [float(ts_list[i] - ts_list[i - 1]) for i in range(1, len(ts_list))]

        # receipt-derived
        gu_list = sorted(gas_used_by_job.get(key, []))
        m_list = sorted(m_token_per_eth_by_job.get(key, []))
        gu_p50 = float(_pct(gu_list, 50)) if gu_list else 0.0
        m_p50 = float(_pct(m_list, 50)) if m_list else 0.0
        k_from_receipt = (gu_p50 * m_p50 / 1e18) if gu_p50 and m_p50 else 0.0

        # call-derived
        k_list = sorted(k_token_per_wei_by_job.get(key, []))
        k_call_p50 = float(_pct(k_list, 50)) if k_list else 0.0

        roi_list = sorted(roi_by_job.get(key, []))
        y_list = sorted(yield_usd_by_job.get(key, []))
        c_list = sorted(cost_usd_by_job.get(key, []))

        roi_p50 = float(_pct(roi_list, 50)) if roi_list else 0.0
        roi_cv = float(_cv(roi_list) or 0.0) if roi_list else 0.0

        rows.append(
            {
                "job": label,
                "type": _job_type(sel),
                "selector": sel,
                "target": tgt,
                "subkey": sub,
                "out_token": token_sym,
                "out_token_addr": token_addr,
                "calls_7d": int(cnt),
                "gap_s_p50": float(_pct(sorted(gaps), 50)) if gaps else 0.0,
                "gas_used_p50": int(round(gu_p50)) if gu_p50 else 0,
                "gas_used_cv": float(_cv(gu_list) or 0.0) if gu_list else 0.0,
                "m_token_per_eth_p50": float(m_p50),
                "m_token_per_eth_cv": float(_cv(m_list) or 0.0) if m_list else 0.0,
                "k_token_per_wei_p50": float(k_call_p50),
                "k_token_per_wei_p50_from_receipt": float(k_from_receipt),
                "roi_usd_p50": float(roi_p50),
                "roi_usd_cv": float(roi_cv),
                "yield_usd_p50": float(_pct(y_list, 50)) if y_list else 0.0,
                "tx_cost_usd_p50": float(_pct(c_list, 50)) if c_list else 0.0,
            }
        )

    # Tiering (USD ROI)
    def tier(roi_p50: float) -> str:
        if roi_p50 >= 1000:
            return "T4 (>=1000)"
        if roi_p50 >= 150:
            return "T3 (150-1000)"
        if roi_p50 >= 70:
            return "T2 (70-150)"
        if roi_p50 > 0:
            return "T1 (<70)"
        return "NA"

    for r in rows:
        r["tier_usd_roi"] = tier(float(r.get("roi_usd_p50") or 0.0))

    os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
    with open(args.out_csv, "w", newline="") as f:
        fields = [
            "job",
            "type",
            "selector",
            "target",
            "subkey",
            "out_token",
            "out_token_addr",
            "calls_7d",
            "gap_s_p50",
            "gas_used_p50",
            "gas_used_cv",
            "m_token_per_eth_p50",
            "m_token_per_eth_cv",
            "k_token_per_wei_p50",
            "k_token_per_wei_p50_from_receipt",
            "roi_usd_p50",
            "roi_usd_cv",
            "yield_usd_p50",
            "tx_cost_usd_p50",
            "tier_usd_roi",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write("# harvester bot 配置表（推测 / 7d 反推）\n\n")
        f.write(f"- calls：`{args.calls_csv}`\n")
        f.write(f"- receipts sample：`{args.receipts_sample}`（用于 gas_used 与 m_token_per_eth）\n")
        f.write(f"- prices：`{args.prices_json}`（USD 口径 ROI）\n")
        if start_ts and end_ts:
            f.write(f"- 时间窗口：`{_fmt_ts(start_ts, tz_bj)}` → `{_fmt_ts(end_ts, tz_bj)}` (UTC+8)\n")
        f.write("\n")

        f.write("## 说明（关键口径）\n\n")
        f.write(
            "- `k_token_per_wei_p50`：p50(minOut/gas_price)，单位 `token/wei`（最贴近链上入参特征）。\n"
            "- `m_token_per_eth_p50`：p50(minOut/tx_fee)，单位 `token/ETH`（tx_fee=gas_used*gas_price）。\n"
            "- `roi_usd_p50`：p50(yield_usd/tx_cost_usd)，其中 yield_usd≈minOut*token_usd，tx_cost_usd≈tx_fee*ETH_usd。\n"
            "- 注意：这里用 minOut 近似 expected_out（bot 可能会留少量 buffer），因此这些阈值偏保守。\n\n"
        )

        if price_alias_used:
            for (src, dst), cnt in price_alias_used.most_common():
                f.write(f"- 价格回退：`{src}` 无有效价格点，使用 `{dst}` 价格近似（hits={cnt}）\n")
            f.write("\n")

        f.write("## ROI 档位（p50）\n\n")
        tier_order = ["T4 (>=1000)", "T3 (150-1000)", "T2 (70-150)", "T1 (<70)", "NA"]
        by_tier: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_tier[str(r.get("tier_usd_roi") or "NA")].append(r)
        for t in tier_order:
            items = by_tier.get(t, [])
            if not items:
                continue
            items_sorted = sorted(items, key=lambda x: float(x.get("roi_usd_p50") or 0.0), reverse=True)
            parts = [f"{it['job']}({float(it.get('roi_usd_p50') or 0.0):.3g})" for it in items_sorted]
            f.write(f"- {t}: " + ", ".join(parts) + "\n")
        f.write("\n")

        f.write("## 配置表（按 7d 调用次数排序）\n\n")
        f.write(
            "| job | type | selector | target | subkey | out_token | calls_7d | gap_s(p50) | gas_used(p50) | "
            "m_token/ETH(p50) | k_token/wei(p50) | ROI_usd(p50) | tier |\n"
        )
        f.write("|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|\n")
        for r in rows:
            f.write(
                f"| {r['job']} | {r['type']} | `{r['selector']}` | `{r['target']}` | {r['subkey'] or ''} | "
                f"{r['out_token']} | {r['calls_7d']} | {r['gap_s_p50']:.0f} | {r['gas_used_p50']} | "
                f"{r['m_token_per_eth_p50']:.4g} | {r['k_token_per_wei_p50']:.4g} | {r['roi_usd_p50']:.4g} | "
                f"{r['tier_usd_roi']} |\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
