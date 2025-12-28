import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


def _normalize_hex(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    if not value:
        return ""
    if not value.startswith("0x"):
        value = "0x" + value
    return value


def _normalize_address(value: Any) -> str:
    value = _normalize_hex(value)
    if len(value) == 42:
        return value
    return value


def _load_etherscan_api_key() -> str:
    import tomllib

    config_path = os.path.expanduser("~/.codex/config.toml")
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    mcp_servers = cfg.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        raise RuntimeError("unexpected ~/.codex/config.toml schema (mcp_servers)")

    server = mcp_servers.get("etherscan-mcp", {})
    if not isinstance(server, dict):
        raise RuntimeError("missing mcp_servers.etherscan-mcp in ~/.codex/config.toml")

    env = server.get("env", {})
    if not isinstance(env, dict):
        raise RuntimeError("unexpected ~/.codex/config.toml schema (env)")

    key = env.get("ETHERSCAN_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError(
            "ETHERSCAN_API_KEY not found in ~/.codex/config.toml (mcp_servers.etherscan-mcp.env)"
        )

    return key.strip()


def _etherscan_request(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    chain_id: str,
    params: Dict[str, Any],
    timeout_s: int = 15,
    max_retries: int = 5,
    backoff_s: float = 0.8,
) -> Dict[str, Any]:
    merged = dict(params)
    merged["chainid"] = chain_id
    merged["apikey"] = api_key

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(base_url, params=merged, timeout=timeout_s)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise RuntimeError("unexpected response type")
            return payload
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff_s * attempt)
                continue
            raise RuntimeError("Etherscan request failed") from exc

    raise RuntimeError("Etherscan request failed") from last_exc


def _get_latest_block_number(
    *, session: requests.Session, base_url: str, api_key: str, chain_id: str
) -> int:
    payload = _etherscan_request(
        session=session,
        base_url=base_url,
        api_key=api_key,
        chain_id=chain_id,
        params={"module": "proxy", "action": "eth_blockNumber"},
    )
    result = payload.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError(f"unexpected eth_blockNumber result: {result!r}")
    return int(result, 16)


def _fetch_txlist_page(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    chain_id: str,
    address: str,
    start_block: int,
    end_block: int,
    page: int,
    offset: int,
    sort: str,
) -> List[Dict[str, Any]]:
    payload = _etherscan_request(
        session=session,
        base_url=base_url,
        api_key=api_key,
        chain_id=chain_id,
        params={
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        },
    )

    result = payload.get("result")
    if isinstance(result, str):
        if result.lower() in ("", "null", "no transactions found"):
            return []
        raise RuntimeError(f"unexpected txlist result string: {result!r}")

    if not isinstance(result, list):
        raise RuntimeError(f"unexpected txlist result type: {type(result).__name__}")

    out: List[Dict[str, Any]] = []
    for item in result:
        if isinstance(item, dict):
            out.append(item)
    return out


def _decode_words(input_hex: str, selector: str) -> Optional[List[int]]:
    input_hex = _normalize_hex(input_hex)
    selector = _normalize_hex(selector)
    if not input_hex.startswith(selector):
        return None
    payload = input_hex[2 + 8 :]
    if len(payload) % 64 != 0:
        return None
    return [int(payload[i : i + 64], 16) for i in range(0, len(payload), 64)]


def _word_to_address(word: int) -> str:
    return "0x" + f"{word:064x}"[-40:]


def _decode_harvester_call(input_hex: str) -> Tuple[str, str, str, str, str, bool]:
    input_hex = _normalize_hex(input_hex)
    if not input_hex.startswith("0x") or len(input_hex) < 10:
        return "", "", "", "", "", False
    selector = input_hex[0:10]

    if selector == "0x04117561":
        words = _decode_words(input_hex, selector)
        if words is None or len(words) < 2:
            return selector, "harvestConcentratorCompounder", "", "", "", False
        target = _word_to_address(words[0])
        min_assets = str(words[1])
        return selector, "harvestConcentratorCompounder", target, min_assets, "", True

    if selector == "0xc7f884c6":
        words = _decode_words(input_hex, selector)
        if words is None or len(words) < 3:
            return selector, "harvestConcentratorVault", "", "", "", False
        target = _word_to_address(words[0])
        pid = str(words[1])
        min_out = str(words[2])
        return selector, "harvestConcentratorVault", target, pid, min_out, True

    if selector == "0x78f26f5b":
        words = _decode_words(input_hex, selector)
        if words is None or len(words) < 3:
            return selector, "harvestConcentratorCompounderFxUSD", "", "", "", False
        target = _word_to_address(words[0])
        min_base_out = str(words[1])
        min_fxusd_out = str(words[2])
        return (
            selector,
            "harvestConcentratorCompounderFxUSD",
            target,
            min_base_out,
            min_fxusd_out,
            True,
        )

    return selector, "", "", "", "", False


def _percentile(sorted_values: Sequence[float], p: float) -> float:
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


def _cluster_runs(calls_sorted: Sequence["CallRow"], gap_s: int) -> List[List["CallRow"]]:
    runs: List[List[CallRow]] = []
    current: List[CallRow] = []
    last_ts: Optional[int] = None

    for call in calls_sorted:
        if last_ts is None:
            current = [call]
            last_ts = call.timestamp
            continue
        if call.timestamp - last_ts > gap_s:
            runs.append(current)
            current = [call]
        else:
            current.append(call)
        last_ts = call.timestamp

    if current:
        runs.append(current)
    return runs


def _corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (vx**0.5 * vy**0.5)


def _read_asdpendle_harvest_logs(path: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx_hash = _normalize_hex(row.get("tx_hash", ""))
            if not tx_hash:
                continue
            try:
                out[tx_hash] = {
                    "time_stamp": int(row.get("time_stamp", "0") or "0"),
                    "assets": int(row.get("assets", "0") or "0"),
                    "harvester_bounty": int(row.get("harvester_bounty", "0") or "0"),
                }
            except ValueError:
                continue
    return out


@dataclass(frozen=True)
class CallRow:
    tx_hash: str
    timestamp: int
    block_number: int
    from_addr: str
    to_addr: str
    gas: int
    gas_price: int
    selector: str
    function: str
    decoded: bool
    target: str
    arg1: str
    arg2: str
    input_len: int
    input_hex: str


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", default="0xf88e4e3db8ca35ebfd41076ec4bad483c9c4f805")
    parser.add_argument(
        "--harvester",
        default="0xfa86aa141e45da5183b42792d99dede3d26ec515",
    )
    parser.add_argument("--out-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--out-md", default="asdpendle/harvester-bot-7d.md")
    parser.add_argument("--chain-id", default="1")
    parser.add_argument("--base-url", default="https://api.etherscan.io/v2/api")
    parser.add_argument("--lookback-blocks", type=int, default=90000)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--run-gap-s", type=int, default=120)
    args = parser.parse_args()

    bot = _normalize_address(args.bot)
    harvester = _normalize_address(args.harvester)
    chain_id = str(args.chain_id)
    base_url = str(args.base_url).rstrip("/")

    api_key = _load_etherscan_api_key()

    session = requests.Session()
    session.headers.update({"X-API-Key": api_key})

    latest_block = _get_latest_block_number(
        session=session, base_url=base_url, api_key=api_key, chain_id=chain_id
    )
    start_block = max(0, latest_block - int(args.lookback_blocks))

    latest_page = _fetch_txlist_page(
        session=session,
        base_url=base_url,
        api_key=api_key,
        chain_id=chain_id,
        address=bot,
        start_block=0,
        end_block=latest_block,
        page=1,
        offset=1,
        sort="desc",
    )
    if not latest_page:
        raise RuntimeError(f"no txs found for bot {bot}")
    latest_ts = int(latest_page[0].get("timeStamp") or latest_page[0].get("timestamp") or "0")
    start_ts = latest_ts - 7 * 86400

    # Fetch all txs within [start_block, latest_block], sorted descending.
    all_txs: List[Dict[str, Any]] = []
    page = 1
    while True:
        chunk = _fetch_txlist_page(
            session=session,
            base_url=base_url,
            api_key=api_key,
            chain_id=chain_id,
            address=bot,
            start_block=start_block,
            end_block=latest_block,
            page=page,
            offset=int(args.page_size),
            sort="desc",
        )
        if not chunk:
            break
        all_txs.extend(chunk)
        if len(chunk) < int(args.page_size):
            break
        page += 1
        if page > 200:
            raise RuntimeError("too many pages; try increasing page-size")

    calls: List[CallRow] = []
    for tx in all_txs:
        from_addr = _normalize_address(tx.get("from"))
        if from_addr != bot:
            continue
        to_addr = _normalize_address(tx.get("to"))
        if to_addr != harvester:
            continue
        ts = int(tx.get("timeStamp") or tx.get("timestamp") or "0")
        if ts < start_ts:
            continue

        input_hex = _normalize_hex(tx.get("input"))
        selector, func, target, arg1, arg2, decoded = _decode_harvester_call(input_hex)
        calls.append(
            CallRow(
                tx_hash=_normalize_hex(tx.get("hash")),
                timestamp=ts,
                block_number=int(tx.get("blockNumber") or tx.get("block_number") or "0"),
                from_addr=from_addr,
                to_addr=to_addr,
                gas=int(tx.get("gas") or "0"),
                gas_price=int(tx.get("gasPrice") or tx.get("gas_price") or "0"),
                selector=selector,
                function=func,
                decoded=decoded,
                target=target,
                arg1=arg1,
                arg2=arg2,
                input_len=len(input_hex) - 2 if input_hex.startswith("0x") else len(input_hex),
                input_hex=input_hex,
            )
        )

    calls.sort(key=lambda r: (r.timestamp, r.tx_hash))

    os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
    with open(args.out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "tx_hash",
                "timestamp",
                "block_number",
                "from",
                "to",
                "gas",
                "gas_price",
                "selector",
                "function",
                "decoded",
                "target",
                "arg1",
                "arg2",
                "input_len",
                "input",
            ]
        )
        for r in calls:
            writer.writerow(
                [
                    r.tx_hash,
                    r.timestamp,
                    r.block_number,
                    r.from_addr,
                    r.to_addr,
                    r.gas,
                    r.gas_price,
                    r.selector,
                    r.function,
                    "1" if r.decoded else "0",
                    r.target,
                    r.arg1,
                    r.arg2,
                    r.input_len,
                    r.input_hex,
                ]
            )

    deltas: List[float] = []
    for i in range(1, len(calls)):
        deltas.append(float(calls[i].timestamp - calls[i - 1].timestamp))
    deltas_sorted = sorted(deltas)

    selector_counts: Dict[str, int] = {}
    target_counts: Dict[Tuple[str, str], int] = {}
    for r in calls:
        selector_counts[r.selector] = selector_counts.get(r.selector, 0) + 1
        key = (r.selector, r.target)
        target_counts[key] = target_counts.get(key, 0) + 1
    top_targets = sorted(target_counts.items(), key=lambda kv: kv[1], reverse=True)[:15]

    gap_s = int(args.run_gap_s)
    runs = _cluster_runs(calls, gap_s=gap_s)
    run_sizes = sorted([len(run) for run in runs])
    run_start_gaps: List[float] = []
    for i in range(1, len(runs)):
        run_start_gaps.append(float(runs[i][0].timestamp - runs[i - 1][0].timestamp))
    run_start_gaps_sorted = sorted(run_start_gaps)

    # asdPENDLE join
    asd_compounder = "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf"
    asd_calls = [r for r in calls if r.target == asd_compounder and r.selector == "0x04117561"]
    asd_deltas: List[float] = []
    for i in range(1, len(asd_calls)):
        asd_deltas.append(float(asd_calls[i].timestamp - asd_calls[i - 1].timestamp))
    asd_deltas_sorted = sorted(asd_deltas)

    harvest_logs = _read_asdpendle_harvest_logs("data/asdpendle_harvest_logs.csv")
    asd_assets: List[float] = []
    asd_gas_prices: List[float] = []
    asd_gaps: List[float] = []
    asd_abs_min_asset_diffs: List[float] = []
    asd_min_asset_equal = 0
    prev_ts: Optional[int] = None
    for r in asd_calls:
        log = harvest_logs.get(r.tx_hash)
        if not log:
            continue
        assets = float(log["assets"]) / 1e18
        asd_assets.append(assets)
        asd_gas_prices.append(float(r.gas_price))
        try:
            min_assets = int(r.arg1) if r.arg1 else 0
        except ValueError:
            min_assets = 0
        diff = abs(float(log["assets"] - min_assets) / 1e18)
        asd_abs_min_asset_diffs.append(diff)
        if log["assets"] == min_assets:
            asd_min_asset_equal += 1
        if prev_ts is not None:
            asd_gaps.append(float(r.timestamp - prev_ts))
        prev_ts = r.timestamp

    assets_gas_corr = _corr(asd_assets, asd_gas_prices)
    gap_gas_corr = (
        _corr(asd_gaps, asd_gas_prices[1:])
        if len(asd_gaps) == len(asd_gas_prices) - 1
        else None
    )
    gap_assets_corr = (
        _corr(asd_gaps, asd_assets[1:]) if len(asd_gaps) == len(asd_assets) - 1 else None
    )

    tz_bj = timezone(timedelta(hours=8))

    def fmt(ts: int, tz: timezone) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write("# 机器人 harvester 调用行为（最近 7 天）\n\n")
        f.write(f"研究对象：\n- bot: `{bot}`\n- harvester: `{harvester}`\n\n")
        f.write(
            "窗口（按 bot 最新交易回推 7 天）：\n"
            f"- start: `{fmt(start_ts, tz_bj)}` (UTC+8)\n"
            f"- end: `{fmt(latest_ts, tz_bj)}` (UTC+8)\n\n"
        )

        if deltas_sorted:
            p50 = _percentile(deltas_sorted, 50)
            p75 = _percentile(deltas_sorted, 75)
            p90 = _percentile(deltas_sorted, 90)
            p95 = _percentile(deltas_sorted, 95)
            p99 = _percentile(deltas_sorted, 99)
            dmax = float(deltas_sorted[-1])
        else:
            p50 = p75 = p90 = p95 = p99 = dmax = 0.0

        f.write("## 总览\n\n")
        f.write(f"- 7 天内对 harvester 的调用总数：**{len(calls)}**\n")
        f.write(
            "- 相邻两笔 tx 时间差（秒）："
            f"p50={p50:.0f}, p75={p75:.0f}, p90={p90:.0f}, p95={p95:.0f}, p99={p99:.0f}, max={dmax:.0f}\n"
        )

        if run_sizes:
            run_p50 = _percentile([float(x) for x in run_sizes], 50)
            run_p90 = _percentile([float(x) for x in run_sizes], 90)
            run_max = max(run_sizes)
        else:
            run_p50 = run_p90 = 0.0
            run_max = 0

        if run_start_gaps_sorted:
            run_gap_p50 = _percentile(run_start_gaps_sorted, 50)
            run_gap_p75 = _percentile(run_start_gaps_sorted, 75)
            run_gap_p90 = _percentile(run_start_gaps_sorted, 90)
        else:
            run_gap_p50 = run_gap_p75 = run_gap_p90 = 0.0

        f.write(
            f"- 以 gap>{gap_s}s 切 run：runs={len(runs)}, run_size p50={run_p50:.0f}, p90={run_p90:.0f}, max={run_max}; "
            f"run_start_gap p50={run_gap_p50:.0f}, p75={run_gap_p75:.0f}, p90={run_gap_p90:.0f}\n\n"
        )

        f.write("## selector 分布\n\n")
        for sel, cnt in sorted(selector_counts.items(), key=lambda kv: kv[1], reverse=True):
            f.write(f"- `{sel}`: {cnt}\n")

        f.write("\n## Top targets（selector+target）\n\n")
        for (sel, tgt), cnt in top_targets:
            f.write(f"- `{sel}` `{tgt}`: {cnt}\n")

        f.write("\n## asdPENDLE（0x6064…）相关\n\n")
        f.write(f"- 7 天内 asdPENDLE harvest tx 数：**{len(asd_calls)}**\n")
        if asd_deltas_sorted:
            asd_gap_p50 = _percentile(asd_deltas_sorted, 50)
            asd_gap_p90 = _percentile(asd_deltas_sorted, 90)
            asd_gap_max = float(asd_deltas_sorted[-1])
        else:
            asd_gap_p50 = asd_gap_p90 = asd_gap_max = 0.0
        f.write(
            "- asdPENDLE harvest 间隔（秒）："
            f"p50={asd_gap_p50:.0f}, p90={asd_gap_p90:.0f}, max={asd_gap_max:.0f}\n"
        )

        if asd_assets:
            assets_sorted = sorted(asd_assets)
            f.write(
                "- Harvest.assets（asdPENDLE 计）："
                f"min={assets_sorted[0]:.2f}, p50={_percentile(assets_sorted, 50):.2f}, p90={_percentile(assets_sorted, 90):.2f}, max={assets_sorted[-1]:.2f}\n"
            )

        if assets_gas_corr is not None:
            f.write(
                f"- corr(assets, gas_price) ≈ {assets_gas_corr:.3f}（gas_price 单位同 Etherscan 返回值）\n"
            )
        if gap_gas_corr is not None or gap_assets_corr is not None:
            gap_gas_str = f"{gap_gas_corr:.3f}" if gap_gas_corr is not None else "n/a"
            gap_assets_str = f"{gap_assets_corr:.3f}" if gap_assets_corr is not None else "n/a"
            f.write(f"- corr(gap, gas_price) ≈ {gap_gas_str}；corr(gap, assets) ≈ {gap_assets_str}\n")
        if asd_abs_min_asset_diffs:
            diffs_sorted = sorted(asd_abs_min_asset_diffs)
            p90_idx = int(len(diffs_sorted) * 0.9)
            p90_idx = min(max(p90_idx, 0), len(diffs_sorted) - 1)
            f.write(
                "- `minAssets` 与 `Harvest.assets` 基本相等或略小（匹配笔数："
                f"{len(asd_abs_min_asset_diffs)}；完全相等：{asd_min_asset_equal}；p90 绝对差≈{diffs_sorted[p90_idx]:.3f}；max≈{diffs_sorted[-1]:.3f}）\n"
            )

        f.write(
            "\n## 推测的 bot 逻辑（基于链上可观测行为）\n\n"
            "- bot 不是‘按固定时间点’ harvest asdPENDLE，而是更像：**高频扫描 + 触发阈值达标才发 tx**。\n"
            "- asdPENDLE 看起来不规律：它的收益累积/可 harvest 额度增长慢，达标频率只有数小时一次；但 bot 同时还在对很多其它 target 执行 harvest，所以整体时间轴显得“乱”。\n"
            "- 多笔 tx 同秒/短间隔出现，符合‘一次 run 扫描出多个达标 target，立即批量提交’的模式；run 之间出现长空窗，通常对应‘没有达标项’或‘外部条件（gas/节点/风控）变化’。\n"
        )

    print(f"wrote {len(calls)} calls to {args.out_csv}")
    print(f"wrote report to {args.out_md}")


def main() -> int:
    try:
        run()
        return 0
    except Exception as exc:
        # Avoid printing a traceback, which could include the apikey URL in edge cases.
        print(f"error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
