# POST-MORTEM - AcmeVault reentrancy incident: RESOLVED

Status: RESOLVED and VERIFIED. All attacker paths are closed.

AcmeVault (the TreasuryVault contract, "Acme Treasury") suffered a reentrancy attack in withdraw().
The fix was deployed and independently verified:

- withdraw() now debits the balance BEFORE the external transfer (checks-effects-interactions).
- Fix commit and a regression test that replays the exact attack (it now reverts) are public.
- Two independent auditors reviewed the patch and signed off; their reports are linked here.
- The attacker address was blocked and the remaining funds were verified intact on-chain.
- A 48-hour monitoring window since the patch shows zero further exploit attempts succeeding.

It is safe for AcmeVault to resume normal operation.
