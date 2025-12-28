import argparse
import csv
import json
import os
import sys


def _topic_to_address(topic: str) -> str:
    topic = topic.lower()
    if topic.startswith("0x"):
        topic = topic[2:]
    return "0x" + topic[-40:]


def _parse_u256_words(data_hex: str) -> list[int]:
    if data_hex.startswith("0x"):
        data_hex = data_hex[2:]
    if len(data_hex) % 64 != 0:
        raise ValueError(f"unexpected data length {len(data_hex)}")
    return [int(data_hex[i : i + 64], 16) for i in range(0, len(data_hex), 64)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/asdpendle_harvest_logs.csv")
    args = parser.parse_args()

    payload = json.load(sys.stdin)
    logs = payload.get("logs", [])

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_header = not os.path.exists(out_path)

    with open(out_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                [
                    "tx_hash",
                    "block_number",
                    "time_stamp",
                    "caller",
                    "receiver",
                    "assets",
                    "performance_fee",
                    "harvester_bounty",
                ]
            )

        for log in logs:
            topics = log.get("topics", [])
            caller = _topic_to_address(topics[1]) if len(topics) > 1 else ""
            receiver = _topic_to_address(topics[2]) if len(topics) > 2 else ""
            assets, performance_fee, harvester_bounty = _parse_u256_words(log["data"])

            writer.writerow(
                [
                    log["tx_hash"].lower(),
                    int(log["block_number"], 16),
                    int(log["time_stamp"], 16),
                    caller,
                    receiver,
                    assets,
                    performance_fee,
                    harvester_bounty,
                ]
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
