"""
Studio Mode integration test for SentinelHalt + TreasuryVault.

This is the test that exercises the thing tests/direct/ cannot: a real
cross-contract view() call, made by one genuinely deployed contract into
another, on a real GenVM network. Direct Mode's `CallContract` support is
not wired up in this toolchain generation (see the module docstrings in
tests/direct/test_treasury_vault.py and tests/direct/conftest.py for the
full explanation) -- it can test each contract's own logic in isolation,
but it cannot prove that TreasuryVault's is_halted() check actually reaches
a real SentinelHalt deployment. This file is that proof.

IMPORTANT -- this file has NOT been executed by its author. It was written
against genlayer-test's documented Studio Mode API, but the environment it
was written in had no network access to Studio Devnet, so it has never run
against a live network. Treat a first failure here as "check the API usage"
before "check the contracts": the contracts' own logic is covered by
tests/direct/ (165 passing tests). See tests/integration/README.md.

It needs a network to run against and is therefore NOT part of the default
`pytest`/`gltest` collection (see pyproject.toml) -- run it explicitly:

    gltest tests/integration/test_sentinel_vault.py --network studio_devnet -v

Requires DEPLOYER_PRIVATE_KEY in the environment (see deploy/.env.example)
for a funded Studio Devnet account -- deploying and calling contracts on
Studio Devnet costs real (testnet) fees under the v0.6 fee model, unlike
the older, gasless Studio.
"""
import json

from gltest import get_contract_factory, get_default_account, get_validator_factory
from gltest.assertions import tx_execution_succeeded


REPORT_BOND = 10**16  # matches DEFAULT_REPORT_BOND
ONE_GEN = 10**18

EXPLOIT_EVIDENCE_URL = "https://explorer-studio-dev.genlayer.com/fixtures/exploit-report"
CLEAR_EVIDENCE_URL = "https://explorer-studio-dev.genlayer.com/fixtures/postmortem"


def _mock_validators(verdict: str, confidence: int = 90, reasoning: str = "evaluated", count: int = 5):
	"""Real Studio Mode validators would call a real LLM and fetch a real
	URL; for a repeatable CI run, mock both so the verdict is deterministic
	instead of depending on what a live model decides about a fixture page.
	Omit the transaction_context entirely to see genuine multi-validator
	judgment instead."""
	factory = get_validator_factory()
	payload = json.dumps({"verdict": verdict, "confidence": confidence, "reasoning": reasoning})
	validators = factory.batch_create_mock_validators(
		count=count,
		mock_web_response={
			"nondet_web_request": {
				EXPLOIT_EVIDENCE_URL: {"method": "GET", "status": 200, "body": "evidence page content"},
				CLEAR_EVIDENCE_URL: {"method": "GET", "status": 200, "body": "postmortem page content"},
			}
		},
		mock_llm_response={"nondet_exec_prompt": {"": payload}},
		# An empty-string key matches any prompt substring -- every call in
		# this test is judged the same fixed way. Narrow this to a real
		# prompt fragment if a test needs two different mocked verdicts to
		# coexist in the same validator set.
	)
	return {"validators": [v.to_dict() for v in validators]}


def test_sentinel_halt_actually_halts_treasury_vault_live():
	account = get_default_account()

	sentinel = get_contract_factory("SentinelHalt").deploy(args=[REPORT_BOND, 300], account=account)
	vault = get_contract_factory("TreasuryVault").deploy(args=[sentinel.address], account=account)

	# -- register the vault, confirm it starts open ------------------------
	reg_tx = sentinel.register_target(
		args=[vault.address, "TreasuryVault (integration test)", "A minimal demo vault."],
	).transact(account=account)
	assert tx_execution_succeeded(reg_tx)

	cfg_before = json.loads(vault.get_config().call())
	assert cfg_before["halted"] is False

	# -- deposit works while the vault is open ------------------------------
	deposit_tx = vault.deposit().transact(account=account, value=ONE_GEN)
	assert tx_execution_succeeded(deposit_tx)

	balance = json.loads(vault.get_balance_of(args=[account.address]).call())
	assert balance["balance"] == str(ONE_GEN)

	# -- report a confirmed exploit; validators (mocked here) agree --------
	report_ctx = _mock_validators("SUPPORTED", reasoning="Active drain confirmed")
	report_tx = sentinel.report_exploit(
		args=[vault.address, EXPLOIT_EVIDENCE_URL, "Funds are being actively drained"],
	).transact(account=account, value=REPORT_BOND, transaction_context=report_ctx)
	assert tx_execution_succeeded(report_tx)

	target = json.loads(sentinel.get_target(args=[vault.address]).call())
	assert target["status"] == "HALTED"

	# -- THIS is the assertion Direct Mode cannot make: a real cross-contract
	# -- call, from a genuinely separate deployed contract, reflecting
	# -- SentinelHalt's actual on-chain verdict.
	cfg_after = json.loads(vault.get_config().call())
	assert cfg_after["halted"] is True
	assert vault.is_halted().call() is True

	# -- and the real enforcement: a withdrawal genuinely reverts -----------
	withdraw_tx = vault.withdraw(args=[10**17]).transact(account=account)
	assert not tx_execution_succeeded(withdraw_tx)

	# -- clearing requires the same on-chain judgment, not a maintainer's
	# -- own say-so; mock a SUPPORTED clear verdict and confirm recovery ----
	clear_ctx = _mock_validators("SUPPORTED", reasoning="Patch verified, funds secured")
	clear_tx = sentinel.clear_halt(
		args=[vault.address, CLEAR_EVIDENCE_URL, "Vulnerability patched and verified"],
	).transact(account=account, value=REPORT_BOND, transaction_context=clear_ctx)
	assert tx_execution_succeeded(clear_tx)

	assert vault.is_halted().call() is False

	# -- withdrawals work again, live, with no cache to invalidate ----------
	withdraw_tx2 = vault.withdraw(args=[10**17]).transact(account=account)
	assert tx_execution_succeeded(withdraw_tx2)


def test_false_alarm_forfeits_bond_to_target_maintainer():
	account = get_default_account()

	sentinel = get_contract_factory("SentinelHalt").deploy(args=[REPORT_BOND, 0], account=account)  # no cooldown
	vault = get_contract_factory("TreasuryVault").deploy(args=[sentinel.address], account=account)

	sentinel.register_target(
		args=[vault.address, "TreasuryVault (false alarm test)", "A minimal demo vault."],
	).transact(account=account)

	ctx = _mock_validators("NOT_SUPPORTED", reasoning="No evidence of any exploit")
	report_tx = sentinel.report_exploit(
		args=[vault.address, EXPLOIT_EVIDENCE_URL, "I suspect something might be wrong"],
	).transact(account=account, value=REPORT_BOND, transaction_context=ctx)
	assert tx_execution_succeeded(report_tx)

	target = json.loads(sentinel.get_target(args=[vault.address]).call())
	assert target["status"] == "SAFE"  # the false alarm never halted anything
	assert target["available_compensation"] == str(REPORT_BOND)

	# vault is untouched throughout
	assert vault.is_halted().call() is False
