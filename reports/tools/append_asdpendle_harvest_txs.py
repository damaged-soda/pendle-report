import argparse
import csv
import json
import os
import sys
from typing import Optional, Tuple


def _hex_to_address(word_hex: str) -> str:
    word_hex = word_hex.lower()
    if word_hex.startswith("0x"):
        word_hex = word_hex[2:]
    if len(word_hex) != 64:
        raise ValueError(f"expected 32-byte word hex, got len={len(word_hex)}")
    return "0x" + word_hex[-40:]


def _decode_harvest_call_input(
    input_hex: str, *, selector: str
) -> Optional[Tuple[str, int]]:
    if not isinstance(input_hex, str):
        return None
    input_hex = input_hex.lower()
    selector = selector.lower()
    if not selector.startswith("0x"):
        selector = "0x" + selector
    if not input_hex.startswith(selector):
        return None
    if input_hex.startswith("0x"):
        input_hex = input_hex[2:]
    selector_hex = selector[2:]
    if not input_hex.startswith(selector_hex):
        return None
    payload = input_hex[len(selector_hex) :]
    if len(payload) < 128:
        return None
    compounder = _hex_to_address(payload[0:64])
    min_assets = int(payload[64:128], 16)
    return compounder, min_assets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/asdpendle_harvest_txs.csv")
    parser.add_argument(
        "--harvester",
        default="0xfa86aa141e45da5183b42792d99dede3d26ec515",
    )
    parser.add_argument(
        "--compounder",
        default="0x606462126e4bd5c4d153fe09967e4c46c9c7fecf",
    )
    parser.add_argument("--selector", default="0x04117561")
    args = parser.parse_args()

    harvester = args.harvester.lower()
    compounder_target = args.compounder.lower()

    payload = json.load(sys.stdin)
    txs = payload.get("transactions", [])

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_header = not os.path.exists(out_path)

    written = 0
    with open(out_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                [
                    "tx_hash",
                    "timestamp",
                    "from",
                    "to",
                    "block_number",
                    "compounder",
                    "min_assets",
                ]
            )

        for tx in txs:
            to_addr = str(tx.get("to", "")).lower()
            if to_addr != harvester:
                continue
            decoded = _decode_harvest_call_input(tx.get("input", ""), selector=args.selector)
            if decoded is None:
                continue
            compounder, min_assets = decoded
            if compounder.lower() != compounder_target:
                continue

            writer.writerow(
                [
                    tx["hash"].lower(),
                    int(tx["timestamp"]),
                    str(tx.get("from", "")).lower(),
                    to_addr,
                    int(tx["block_number"]),
                    compounder.lower(),
                    min_assets,
                ]
            )
            written += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
