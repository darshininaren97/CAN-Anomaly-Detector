from pathlib import Path
from dbc_decoder import decode_file

BASE_DIR = Path(__file__).resolve().parent

LOG_FILE = BASE_DIR / "CAN_log.txt"
DBC_FILE = BASE_DIR / "CAN.dbc"
OUTPUT_FILE = BASE_DIR / "decoded_output.json"


def main():
    print("=== CAN DBC Decoder ===")
    print(f"Log: {LOG_FILE}")
    print(f"DBC: {DBC_FILE}")
    print()

    if not LOG_FILE.exists():
        raise FileNotFoundError(f"Cannot find: {LOG_FILE}")

    if not DBC_FILE.exists():
        raise FileNotFoundError(f"Cannot find: {DBC_FILE}")

    print("Decoding CAN log...")

    results = decode_file(
        dbc_source=DBC_FILE,
        frames_or_file=LOG_FILE,
        output_json=OUTPUT_FILE,
        include_unmatched=True,
    )

    print()
    print(f"Loaded and decoded {len(results)} CAN frames.")
    print(f"Output saved to:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()