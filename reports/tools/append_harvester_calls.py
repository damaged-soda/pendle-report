import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


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


def _decode_harvester_call(
    input_hex: str,
) -> Tuple[str, str, str, str, str, bool]:
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


def _load_seen_hashes(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    seen: Set[str] = set()
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                continue
            if not row:
                continue
            seen.add(row[0].strip().lower())
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/f88e_harvester_calls_7d.csv")
    parser.add_argument(
        "--harvester",
        default="0xfa86aa141e45da5183b42792d99dede3d26ec515",
        help="Only keep tx.to == this address",
    )
    parser.add_argument(
        "--min-ts",
        default="0",
        help="Only keep tx.timestamp >= this (unix seconds)",
    )
    args = parser.parse_args()

    harvester = _normalize_address(args.harvester)
    min_ts = int(args.min_ts)

    payload = json.load(sys.stdin)
    txs: Sequence[Dict[str, Any]] = payload.get("transactions", [])

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_header = not os.path.exists(out_path)
    seen_hashes = _load_seen_hashes(out_path)

    written = 0
    with open(out_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
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

        for tx in txs:
            tx_hash = _normalize_hex(tx.get("hash", ""))
            if not tx_hash:
                continue
            if tx_hash in seen_hashes:
                continue

            to_addr = _normalize_address(tx.get("to", ""))
            if harvester and to_addr != harvester:
                continue

            ts = int(tx.get("timestamp", "0") or "0")
            if ts < min_ts:
                continue

            input_hex = _normalize_hex(tx.get("input", ""))
            selector, func, target, arg1, arg2, decoded = _decode_harvester_call(
                input_hex
            )

            writer.writerow(
                [
                    tx_hash,
                    ts,
                    int(tx.get("block_number", "0") or "0"),
                    _normalize_address(tx.get("from", "")),
                    to_addr,
                    str(tx.get("gas", "")),
                    str(tx.get("gas_price", "")),
                    selector,
                    func,
                    "1" if decoded else "0",
                    target,
                    arg1,
                    arg2,
                    len(input_hex) - 2 if input_hex.startswith("0x") else len(input_hex),
                    input_hex,
                ]
            )
            seen_hashes.add(tx_hash)
            written += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
