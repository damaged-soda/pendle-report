import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


def _load_time_range_from_calls(path: str) -> Tuple[int, int]:
    ts_min: Optional[int] = None
    ts_max: Optional[int] = None
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row.get("timestamp") or "0")
            except ValueError:
                continue
            if ts <= 0:
                continue
            ts_min = ts if ts_min is None else min(ts_min, ts)
            ts_max = ts if ts_max is None else max(ts_max, ts)
    if ts_min is None or ts_max is None:
        raise RuntimeError("failed to infer time range from calls csv")
    return ts_min, ts_max


def _sleep_s(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)


def _request_json(
    *,
    session: requests.Session,
    url: str,
    timeout_s: int = 30,
    max_retries: int = 10,
    backoff_s: float = 5.0,
) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout_s)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.strip().isdigit() else backoff_s * attempt
                _sleep_s(delay)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise RuntimeError("unexpected response type")
            return payload
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                _sleep_s(backoff_s * attempt)
                continue
            raise RuntimeError(f"request failed: {url}") from exc
    raise RuntimeError(f"request failed: {url}") from last_exc


def _market_chart_range_eth_url(*, vs: str, from_ts: int, to_ts: int) -> str:
    return (
        "https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range"
        f"?vs_currency={vs}&from={from_ts}&to={to_ts}"
    )


def _market_chart_range_contract_url(*, contract_addr: str, vs: str, from_ts: int, to_ts: int) -> str:
    addr = contract_addr.strip().lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr
    return (
        "https://api.coingecko.com/api/v3/coins/ethereum/contract/"
        f"{addr}/market_chart/range?vs_currency={vs}&from={from_ts}&to={to_ts}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--out", default="data/coingecko_prices_7d.json")
    parser.add_argument("--vs", default="usd")
    parser.add_argument("--from-ts", type=int, default=0)
    parser.add_argument("--to-ts", type=int, default=0)
    parser.add_argument("--pad-s", type=int, default=6 * 3600, help="pad seconds around inferred range")
    parser.add_argument("--min-sleep-s", type=float, default=2.0, help="sleep between successful requests")
    args = parser.parse_args()

    from_ts = int(args.from_ts)
    to_ts = int(args.to_ts)
    if not from_ts or not to_ts:
        a, b = _load_time_range_from_calls(args.calls_csv)
        from_ts = a - int(args.pad_s)
        to_ts = b + int(args.pad_s)

    vs = str(args.vs).strip().lower() or "usd"

    tokens: Dict[str, Dict[str, str]] = {
        "cvxFXN": {"address": "0x183395dbd0b5e93323a7286d1973150697fffcb3"},
        "cvxCRV": {"address": "0x62b9c7356a2dc64a1969e19c23e4f579f9810aa7"},
        "CVX": {"address": "0x4e3fbd56cd56c3e72c1403e103b45db9da5b9d2b"},
        "sdCRV": {"address": "0xd1b5651e55d4ceed36251c61c50c889b36f6abb5"},
        "sdPENDLE": {"address": "0x5ea630e00d6ee438d3dea1556a110359acdc10a9"},
        "PENDLE": {"address": "0x808507121b80c02388fad14726482e061b8da827"},
        "weETH": {"address": "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee"},
    }

    existing: Dict[str, Any] = {}
    if os.path.exists(args.out):
        try:
            with open(args.out) as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    session = requests.Session()
    session.headers.update({"User-Agent": "etherscan-mcp-use/0.1"})

    out: Dict[str, Any] = dict(existing)
    out.setdefault("meta", {})
    meta = out["meta"]
    if isinstance(meta, dict):
        meta.update(
            {
                "source": "coingecko",
                "vs_currency": vs,
                "from_ts": from_ts,
                "to_ts": to_ts,
                "generated_at": int(datetime.now(tz=timezone.utc).timestamp()),
            }
        )

    # ETH
    if "eth" not in out:
        url = _market_chart_range_eth_url(vs=vs, from_ts=from_ts, to_ts=to_ts)
        payload = _request_json(session=session, url=url)
        out["eth"] = {
            "type": "coingecko_id",
            "id": "ethereum",
            "prices": payload.get("prices", []),
        }
        _sleep_s(float(args.min_sleep_s))

    # Tokens by contract
    out.setdefault("tokens", {})
    out_tokens = out["tokens"]
    if not isinstance(out_tokens, dict):
        out_tokens = {}
        out["tokens"] = out_tokens

    for sym, info in tokens.items():
        addr = str(info["address"]).lower()
        if addr in out_tokens:
            continue
        url = _market_chart_range_contract_url(contract_addr=addr, vs=vs, from_ts=from_ts, to_ts=to_ts)
        payload = _request_json(session=session, url=url)
        out_tokens[addr] = {
            "symbol": sym,
            "address": addr,
            "prices": payload.get("prices", []),
        }
        _sleep_s(float(args.min_sleep_s))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
