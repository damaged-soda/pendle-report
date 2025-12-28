import argparse
import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


SDPENDLE_ADDR = "0x5ea630e00d6ee438d3dea1556a110359acdc10a9"
PENDLE_ADDR = "0x808507121b80c02388fad14726482e061b8da827"
WETH_ADDR = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

# Uniswap V3: PENDLE/WETH fee=3000 (liquidity>0)
UNI_V3_POOL_PENDLE_WETH_3000 = "0x57af956d3e2cca3b86f3d8c6772c03ddca3eaacb"

# Chainlink ETH/USD
CHAINLINK_ETH_USD = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
CHAINLINK_ETH_USD_DECIMALS = 8
CHAINLINK_LATEST_ROUND_DATA = "0xfeaf968c"

# observe(uint32[]) selector = 0x883bdbfd
OBSERVE_SELECTOR = bytes.fromhex("883bdbfd")

LN_1_0001 = math.log(1.0001)


def _normalize_hex(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if not v.startswith("0x"):
        v = "0x" + v
    return v


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


def _is_rate_limited(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    candidates: List[str] = []
    for k in ("message", "result"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            candidates.append(v)
    err = payload.get("error")
    if isinstance(err, dict):
        v = err.get("message")
        if isinstance(v, str) and v:
            candidates.append(v)
    hay = " ".join(candidates).lower()
    return (
        "rate limit" in hay
        or "max calls per sec" in hay
        or "too many requests" in hay
        or "request limit reached" in hay
    )


def _etherscan_request(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    chain_id: str,
    params: Dict[str, Any],
    timeout_s: int = 20,
    max_retries: int = 10,
    backoff_s: float = 0.9,
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
            if _is_rate_limited(payload) and attempt < max_retries:
                time.sleep(backoff_s * attempt)
                continue
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


def _hex_to_int(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v.startswith("0x"):
        return int(v, 16)
    if v.isdigit():
        return int(v, 10)
    return None


def _to_hex_quantity(value: int) -> str:
    if value < 0:
        raise ValueError("negative quantity")
    return hex(int(value))


def _encode_observe(seconds_ago: int) -> str:
    if seconds_ago < 0:
        raise ValueError("seconds_ago must be >= 0")
    # observe(uint32[]) with [secondsAgo, 0]
    # ABI encoding:
    # 0: selector
    # 4..: offset=0x20
    # at offset: length=2, elem0=secondsAgo, elem1=0
    head = OBSERVE_SELECTOR + (32).to_bytes(32, "big")
    body = (2).to_bytes(32, "big") + int(seconds_ago).to_bytes(32, "big") + (0).to_bytes(32, "big")
    return "0x" + (head + body).hex()


def _decode_observe_return(data_hex: str) -> Tuple[List[int], List[int]]:
    data = _normalize_hex(data_hex)
    if not data.startswith("0x"):
        raise ValueError("invalid hex")
    raw = bytes.fromhex(data[2:])
    if len(raw) < 64:
        raise ValueError("short return data")

    def word(i: int) -> bytes:
        start = i * 32
        end = start + 32
        return raw[start:end]

    tick_off = int.from_bytes(word(0), "big")
    spl_off = int.from_bytes(word(1), "big")

    def decode_int256_at(offset: int) -> int:
        w = raw[offset : offset + 32]
        if len(w) != 32:
            raise ValueError("short word")
        x = int.from_bytes(w, "big")
        if x >= 2**255:
            x -= 2**256
        return x

    def decode_uint256_at(offset: int) -> int:
        w = raw[offset : offset + 32]
        if len(w) != 32:
            raise ValueError("short word")
        return int.from_bytes(w, "big")

    def decode_int_array(offset: int) -> List[int]:
        ln = decode_uint256_at(offset)
        out: List[int] = []
        base = offset + 32
        for i in range(ln):
            out.append(decode_int256_at(base + 32 * i))
        return out

    def decode_uint_array(offset: int) -> List[int]:
        ln = decode_uint256_at(offset)
        out: List[int] = []
        base = offset + 32
        for i in range(ln):
            out.append(decode_uint256_at(base + 32 * i))
        return out

    ticks = decode_int_array(tick_off)
    spls = decode_uint_array(spl_off)
    return ticks, spls


def _arithmetic_mean_tick(tick_cumulatives: Sequence[int], seconds_ago: int) -> int:
    if len(tick_cumulatives) < 2:
        raise ValueError("need 2 tick cumulatives")
    if seconds_ago <= 0:
        raise ValueError("seconds_ago must be > 0")
    delta = tick_cumulatives[1] - tick_cumulatives[0]
    mean = int(delta / seconds_ago)  # toward zero
    if delta < 0 and (delta % seconds_ago) != 0:
        mean -= 1  # round toward negative infinity (Uniswap OracleLibrary)
    return mean


def _pendle_eth_from_tick(mean_tick: int) -> float:
    # Uniswap v3 tick is log_{1.0001}(token1/token0) in raw units.
    # For the chosen pool token0=PENDLE, token1=WETH => token1/token0 = ETH per PENDLE.
    return math.exp(float(mean_tick) * LN_1_0001)


def _load_eth_prices_from_prices_json(path: str) -> List[Tuple[int, float]]:
    with open(path) as f:
        payload = json.load(f)
    eth = payload.get("eth", {})
    prices = eth.get("prices", []) if isinstance(eth, dict) else []
    out: List[Tuple[int, float]] = []
    if isinstance(prices, list):
        for item in prices:
            if not (isinstance(item, list) or isinstance(item, tuple)) or len(item) < 2:
                continue
            try:
                out.append((int(item[0]), float(item[1])))
            except Exception:
                continue
    out.sort(key=lambda x: x[0])
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


def _load_sdpendle_call_blocks(path: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sel = str(row.get("selector", "")).lower()
            tgt = str(row.get("target", "")).lower()
            if sel != "0x04117561":
                continue
            if tgt != "0x606462126e4bd5c4d153fe09967e4c46c9c7fecf":
                continue
            try:
                bn = int(row.get("block_number") or "0")
                ts = int(row.get("timestamp") or "0")
            except ValueError:
                continue
            if bn <= 0 or ts <= 0:
                continue
            out.append((bn, ts))
    # de-dup by block_number (keep earliest ts for that block)
    seen: Dict[int, int] = {}
    for bn, ts in out:
        if bn not in seen or ts < seen[bn]:
            seen[bn] = ts
    return sorted([(bn, ts) for bn, ts in seen.items()], key=lambda x: x[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--prices-json", default="data/coingecko_prices_7d.json")
    parser.add_argument("--out", default="data/coingecko_prices_7d.json")
    parser.add_argument("--twap-seconds", type=int, default=1800)
    parser.add_argument(
        "--eth-usd-source",
        default="chainlink",
        choices=["chainlink", "coingecko"],
        help="How to convert ETH to USD for sdPENDLE USD pricing",
    )
    parser.add_argument("--chain-id", default="1")
    parser.add_argument("--base-url", default="https://api.etherscan.io/v2/api")
    parser.add_argument("--sleep-ms", type=int, default=350)
    args = parser.parse_args()

    twap_s = int(args.twap_seconds)
    if twap_s <= 0:
        raise SystemExit("--twap-seconds must be > 0")

    blocks = _load_sdpendle_call_blocks(args.calls_csv)
    if not blocks:
        raise SystemExit("no asdPENDLE calls found in calls csv")

    eth_prices: List[Tuple[int, float]] = []
    if args.eth_usd_source == "coingecko":
        eth_prices = _load_eth_prices_from_prices_json(args.prices_json)
        if not eth_prices:
            raise SystemExit("missing eth price series in prices json (needed for USD conversion)")

    api_key = _load_etherscan_api_key()
    base_url = str(args.base_url).rstrip("/")
    chain_id = str(args.chain_id)

    with open(args.prices_json) as f:
        prices_payload = json.load(f)
    if not isinstance(prices_payload, dict):
        raise SystemExit("prices json invalid")
    prices_payload.setdefault("tokens", {})
    if not isinstance(prices_payload["tokens"], dict):
        prices_payload["tokens"] = {}

    session = requests.Session()
    session.headers.update({"X-API-Key": api_key, "User-Agent": "etherscan-mcp-use/0.1"})

    series_out: List[List[float]] = []
    for bn, ts in blocks:
        eth_usd: Optional[float] = None
        if args.eth_usd_source == "chainlink":
            px_payload = _etherscan_request(
                session=session,
                base_url=base_url,
                api_key=api_key,
                chain_id=chain_id,
                params={
                    "module": "proxy",
                    "action": "eth_call",
                    "to": CHAINLINK_ETH_USD,
                    "data": CHAINLINK_LATEST_ROUND_DATA,
                    "tag": _to_hex_quantity(bn),
                },
            )
            px_hex = px_payload.get("result")
            if not isinstance(px_hex, str) or not px_hex.startswith("0x") or len(px_hex) < 2 + 32 * 5 * 2:
                raise RuntimeError(f"unexpected chainlink eth_call result at block {bn}")
            raw = bytes.fromhex(px_hex[2:])
            # latestRoundData() returns (uint80, int256 answer, uint256, uint256, uint80)
            answer = int.from_bytes(raw[32:64], "big", signed=True)
            if answer <= 0:
                raise RuntimeError(f"invalid chainlink eth_usd={answer} at block {bn}")
            eth_usd = float(answer) / float(10**CHAINLINK_ETH_USD_DECIMALS)
            time.sleep(max(0.0, float(args.sleep_ms) / 1000.0))

        data = _encode_observe(twap_s)
        payload = _etherscan_request(
            session=session,
            base_url=base_url,
            api_key=api_key,
            chain_id=chain_id,
            params={
                "module": "proxy",
                "action": "eth_call",
                "to": UNI_V3_POOL_PENDLE_WETH_3000,
                "data": data,
                "tag": _to_hex_quantity(bn),
            },
        )
        result = payload.get("result")
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RuntimeError(f"unexpected eth_call result at block {bn}")
        ticks, _spl = _decode_observe_return(result)
        if len(ticks) < 2:
            raise RuntimeError(f"observe returned insufficient ticks at block {bn}")
        mean_tick = _arithmetic_mean_tick(ticks[:2], twap_s)
        pendle_eth = _pendle_eth_from_tick(mean_tick)  # ETH per PENDLE
        if args.eth_usd_source == "coingecko":
            eth_usd = _price_at(eth_prices, ts)
        if eth_usd is None or eth_usd <= 0:
            raise RuntimeError(f"missing eth_usd at ts={ts} (source={args.eth_usd_source})")
        sdpendle_usd = float(pendle_eth) * float(eth_usd)  # assume sdPENDLE ~ PENDLE
        series_out.append([float(ts) * 1000.0, float(sdpendle_usd)])
        time.sleep(max(0.0, float(args.sleep_ms) / 1000.0))

    # De-dup timestamps (keep last)
    uniq: Dict[int, float] = {}
    for ms, px in series_out:
        uniq[int(ms)] = float(px)
    series = [[float(ms), float(px)] for ms, px in sorted(uniq.items())]

    prices_payload["tokens"].setdefault(SDPENDLE_ADDR, {"symbol": "sdPENDLE", "address": SDPENDLE_ADDR})
    sd_entry = prices_payload["tokens"][SDPENDLE_ADDR]
    if isinstance(sd_entry, dict):
        sd_entry["symbol"] = sd_entry.get("symbol") or "sdPENDLE"
        sd_entry["address"] = SDPENDLE_ADDR
        sd_entry["prices"] = series
        sd_entry["source"] = {
            "type": "uniswap_v3_twap",
            "pool": UNI_V3_POOL_PENDLE_WETH_3000,
            "pair": f"{PENDLE_ADDR}/{WETH_ADDR}",
            "twap_seconds": twap_s,
            "eth_usd_source": str(args.eth_usd_source),
            "note": "Compute PENDLE/ETH TWAP from UniswapV3 pool and convert to USD; assumes sdPENDLE ~= PENDLE.",
        }

    prices_payload.setdefault("meta", {})
    if isinstance(prices_payload["meta"], dict):
        prices_payload["meta"]["sdpendle_override"] = {
            "generated_at": int(datetime.now(tz=timezone.utc).timestamp()),
            "method": "uniswap_v3_twap_pendle_weth * eth_usd_series",
        }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(prices_payload, f)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
