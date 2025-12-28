import argparse
import csv
import os
import time
from dataclasses import dataclass
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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
    max_retries: int = 8,
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
    value = value.strip().lower()
    if not value:
        return None
    if value.startswith("0x"):
        return int(value, 16)
    if value.isdigit():
        return int(value, 10)
    return None


def _load_seen_hashes(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    seen: Set[str] = set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx = _normalize_hex(row.get("tx_hash", ""))
            if tx:
                seen.add(tx)
    return seen


@dataclass(frozen=True)
class CallRow:
    tx_hash: str
    timestamp: int
    selector: str
    target: str
    arg1: str
    arg2: str
    gas_price: int


def _read_calls(path: str) -> List[CallRow]:
    out: List[CallRow] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                CallRow(
                    tx_hash=_normalize_hex(row.get("tx_hash", "")),
                    timestamp=int(row.get("timestamp") or "0"),
                    selector=str(row.get("selector", "")).lower(),
                    target=str(row.get("target", "")).lower(),
                    arg1=str(row.get("arg1", "")),
                    arg2=str(row.get("arg2", "")),
                    gas_price=int(row.get("gas_price") or "0"),
                )
            )
    out.sort(key=lambda r: (r.timestamp, r.tx_hash))
    return out


def _pick_quantile_indices(n: int, quantiles: Sequence[float]) -> List[int]:
    if n <= 0:
        return []
    idxs: List[int] = []
    for q in quantiles:
        q_clamped = min(max(q, 0.0), 1.0)
        idx = int(round(q_clamped * (n - 1)))
        idxs.append(idx)
    # De-dup while preserving order
    seen: Set[int] = set()
    out: List[int] = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _sample_calls(calls: Sequence[CallRow], max_samples: int) -> List[CallRow]:
    if len(calls) <= max_samples:
        return list(calls)

    # Primary: quantiles by gas_price to cover low/med/high gas regimes.
    calls_by_gas = sorted(calls, key=lambda r: (r.gas_price, r.timestamp, r.tx_hash))
    quantiles = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    idxs = _pick_quantile_indices(len(calls_by_gas), quantiles)
    picked = [calls_by_gas[i] for i in idxs]

    # Fill remaining slots by time-uniform sampling.
    if len(picked) < max_samples:
        step = max(1, floor(len(calls) / (max_samples - len(picked))))
        for i in range(0, len(calls), step):
            picked.append(calls[i])
            if len(picked) >= max_samples:
                break

    # De-dup by tx_hash preserving order.
    seen_tx: Set[str] = set()
    out: List[CallRow] = []
    for r in picked:
        if r.tx_hash and r.tx_hash not in seen_tx:
            seen_tx.add(r.tx_hash)
            out.append(r)
        if len(out) >= max_samples:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-csv", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument("--out", default="data/f88e_harvester_receipts_sample.csv")
    parser.add_argument("--chain-id", default="1")
    parser.add_argument("--base-url", default="https://api.etherscan.io/v2/api")
    parser.add_argument("--max-samples-per-group", type=int, default=10)
    parser.add_argument("--sleep-ms", type=int, default=250)
    args = parser.parse_args()

    api_key = _load_etherscan_api_key()
    base_url = str(args.base_url).rstrip("/")
    chain_id = str(args.chain_id)

    calls = _read_calls(args.calls_csv)
    if not calls:
        raise RuntimeError("no calls found")

    seen = _load_seen_hashes(args.out)

    # Group calls by job key.
    groups: Dict[Tuple[str, str, str], List[CallRow]] = {}
    for r in calls:
        # key = (selector, target, subkey)
        if r.selector == "0xc7f884c6":
            # vault: arg1 is pid
            subkey = r.arg1 or ""
        else:
            subkey = ""
        key = (r.selector, r.target, subkey)
        groups.setdefault(key, []).append(r)

    # Sample within each group; prioritize largest groups first.
    group_items = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    samples: List[Tuple[Tuple[str, str, str], CallRow]] = []
    for key, items in group_items:
        picked = _sample_calls(items, max_samples=int(args.max_samples_per_group))
        for r in picked:
            if r.tx_hash and r.tx_hash not in seen:
                samples.append((key, r))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    write_header = not os.path.exists(args.out)
    session = requests.Session()
    session.headers.update({"X-API-Key": api_key})

    with open(args.out, "a", newline="") as f:
        fieldnames = [
            "tx_hash",
            "timestamp",
            "selector",
            "target",
            "subkey",
            "arg1",
            "arg2",
            "tx_gas_price",
            "receipt_status",
            "gas_used",
            "effective_gas_price",
            "fee_wei",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for (selector, target, subkey), r in samples:
            tx_hash = r.tx_hash
            payload = _etherscan_request(
                session=session,
                base_url=base_url,
                api_key=api_key,
                chain_id=chain_id,
                params={
                    "module": "proxy",
                    "action": "eth_getTransactionReceipt",
                    "txhash": tx_hash,
                },
            )
            receipt = payload.get("result")
            if not isinstance(receipt, dict):
                # Skip if missing (shouldn't happen for confirmed txs).
                continue

            gas_used = _hex_to_int(receipt.get("gasUsed"))
            eff_gp = _hex_to_int(receipt.get("effectiveGasPrice"))
            status = _hex_to_int(receipt.get("status"))
            fee_wei = None
            if gas_used is not None and eff_gp is not None:
                fee_wei = gas_used * eff_gp

            writer.writerow(
                {
                    "tx_hash": tx_hash,
                    "timestamp": r.timestamp,
                    "selector": selector,
                    "target": target,
                    "subkey": subkey,
                    "arg1": r.arg1,
                    "arg2": r.arg2,
                    "tx_gas_price": r.gas_price,
                    "receipt_status": status if status is not None else "",
                    "gas_used": gas_used if gas_used is not None else "",
                    "effective_gas_price": eff_gp if eff_gp is not None else "",
                    "fee_wei": fee_wei if fee_wei is not None else "",
                }
            )
            seen.add(tx_hash)

            sleep_s = max(0.0, float(args.sleep_ms) / 1000.0)
            if sleep_s:
                time.sleep(sleep_s)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

