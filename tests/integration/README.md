# Integration tests

> **Status: written, not yet executed.** The environment this project was
> built in had no network access to Studio Devnet, so
> `test_sentinel_vault.py` has never run against a live network. The Direct Mode tests under `tests/direct/` are the verified suite; this file
> is the test that proves the one thing they cannot, and it is the first
> thing to run once you have a funded Studio Devnet account. If it fails on
> first run, check the API usage (fee parameters, `transaction_context`
> shapes) before suspecting the contracts.

`test_sentinel_vault.py` exercises what `tests/direct/` cannot: a real
cross-contract `view()` call made by one genuinely deployed contract into
another, on a real GenVM network.

## Running it

```bash
pip install -r requirements-dev.txt
cp gltest.config.example.yaml gltest.config.yaml
cp deploy/.env.example .env   # fill in DEPLOYER_PRIVATE_KEY
gltest tests/integration/test_sentinel_vault.py --network studio_devnet -v
```

The config is shipped as an *example* on purpose: gltest resolves every
`${VAR}` in `gltest.config.yaml` for all networks as soon as it loads, so an
active copy would make the offline Direct Mode tests demand a private key
too. Copy it into place only for this live test (and delete it afterwards
if you want plain `pytest` to stay keyless).

The funded account behind `DEPLOYER_PRIVATE_KEY` pays real (testnet) fees
for every deploy and write call under the v0.6 fee model.

## What it proves that Direct Mode cannot

`tests/direct/test_treasury_vault.py` patches `TreasuryVault._halted`
directly at the class level, because Direct Mode does not route
cross-contract `CallContract` requests to a second deployed contract unless
a test installs a `_gl_call_hook`. That limits the *test harness*, not the
contracts -- but it means Direct Mode alone cannot demonstrate that
`TreasuryVault.is_halted()` genuinely reaches a real `SentinelHalt`.

This file deploys both contracts, registers the vault, deposits, submits an
exploit report (mocked validators, so the verdict is deterministic for CI),
and asserts the vault's own on-chain state -- fetched through its own
`get_config()`/`is_halted()`, which call `SentinelHalt` internally --
reflects the halt. It then attempts a withdrawal and confirms it reverts,
clears the halt through the same judged process, and confirms withdrawals
work again. A second test confirms a false alarm forfeits its bond to the
target's maintainer without ever halting the vault.

## Using real validators instead of mocked ones

Drop the `transaction_context=...` argument from the `.transact(...)` calls
to see genuine multi-validator judgment against real fixture pages. That
better tests the *prompt*, at the cost of determinism.
