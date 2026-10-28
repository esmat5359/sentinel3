#!/usr/bin/env python3
"""
Point every contract's `# { "Depends": "py-genlayer:<hash>" }` header at a
different GenVM runner.

Why this exists: that header pins the exact GenVM Python runner a contract
runs on, and a network only accepts a contract whose runner hash it knows.
The hash changes between GenVM releases (v0.6.0-rc3 uses 5jycge..., the
v0.6.0-rc9/rc10 bundles use babwp9...; Studio Next needs 5jycge...), so a contract pinned to a runner the
target network does not have fails at deploy time, not at lint time. If
Studio Devnet's runtime moves, run this once instead of hand-editing files.

    python3 scripts/set_runner_hash.py <new-hash>        # rewrite headers
    python3 scripts/set_runner_hash.py --show            # print current hashes

`genvm-lint check contracts/SentinelHalt.py` reports when a newer runner is
available and prints its hash.

After changing the hash also update GENVM_RUNTIME_VERSION in
tests/direct/conftest.py (and the `genvm-lint download --version ...` step in
.github/workflows/ci.yml) to the GenVM release that ships the new runner --
the Direct Mode tests pin that release so they never depend on resolving
"latest" at run time.
"""
import pathlib
import re
import sys

HEADER = re.compile(r'^(# \{ "Depends": "py-genlayer:)([0-9a-z]+)(" \})', re.MULTILINE)
CONTRACTS = sorted((pathlib.Path(__file__).resolve().parent.parent / "contracts").glob("*.py"))


def main(argv: list[str]) -> int:
	if len(argv) != 2:
		print(__doc__)
		return 2
	if argv[1] == "--show":
		for path in CONTRACTS:
			match = HEADER.search(path.read_text())
			print(f"{path.name}: {match.group(2) if match else '(no header found)'}")
		return 0
	new_hash = argv[1].strip()
	if not re.fullmatch(r"[0-9a-z]{40,60}", new_hash):
		print("That does not look like a runner hash (expected ~52 lowercase base32 characters).")
		return 2
	for path in CONTRACTS:
		text = path.read_text()
		if not HEADER.search(text):
			print(f"{path.name}: no Depends header found, skipped")
			continue
		path.write_text(HEADER.sub(lambda m: m.group(1) + new_hash + m.group(3), text, count=1))
		print(f"{path.name}: now pins py-genlayer:{new_hash}")
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
