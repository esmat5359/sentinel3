"""
Direct Mode tests for SentinelHalt's pull-payment credit ledger.

Why the ledger exists: no payable / AI-judged path pushes GEN out any more.
A refund is an entry in `credits`, and its owner pulls it with the plain,
deterministic `withdraw_credit()`. These tests pin that behavior and the one
accounting invariant the live end-to-end script also checks:

    on-chain balance == credits_outstanding + compensation_outstanding

(Direct Mode does not credit a contract's balance when a payable call carries
value, so tests that check the invariant mirror the chain with `deal`.)
"""
import json

import pytest

from test_sentinel_halt import (  # noqa: F401  (fixtures are used by name)
	ACTION_COOLDOWN,
	CLEAR_EVIDENCE_URL,
	EXPLOIT_EVIDENCE_URL,
	REPORT_BOND,
	addr_str,
	clear,
	mock_verdict,
	registered_target,
	report,
	sentinel,
)


def credit_of(sentinel, who) -> int:
	return int(json.loads(sentinel.get_credit(addr_str(who)))["credit"])


def stats_of(sentinel) -> dict:
	return json.loads(sentinel.get_stats())


# -- crediting ------------------------------------------------------------------

def test_supported_verdict_credits_the_bond_back(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "active drain")
	assert res["verdict"] == "SUPPORTED"
	assert credit_of(sentinel, direct_alice) == REPORT_BOND
	assert stats_of(sentinel)["credits_outstanding"] == str(REPORT_BOND)


def test_inconclusive_verdict_credits_the_bond_back(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "INCONCLUSIVE")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	assert credit_of(sentinel, direct_alice) == REPORT_BOND


def test_not_supported_verdict_forfeits_and_does_not_credit(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	assert credit_of(sentinel, direct_alice) == 0
	stats = stats_of(sentinel)
	assert stats["credits_outstanding"] == "0"
	assert stats["compensation_outstanding"] == str(REPORT_BOND)


def test_retry_later_credits_the_bond_back(sentinel, registered_target, direct_vm, direct_alice):
	direct_vm.clear_mocks()  # nothing registered: the fetch itself fails
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	assert res["verdict"] == "RETRY_LATER"
	assert credit_of(sentinel, direct_alice) == REPORT_BOND


@pytest.mark.parametrize("target,bond", [
	("0x" + "99" * 20, REPORT_BOND),          # unknown target
	("not-an-address", REPORT_BOND),          # malformed target
	("0x" + "99" * 20, REPORT_BOND // 2),     # under-bonded
])
def test_every_rejection_credits_the_full_value(sentinel, direct_vm, direct_alice, target, bond):
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, target, EXPLOIT_EVIDENCE_URL, "claim", bond=bond)
	assert res["ok"] is False
	assert res["credited"] is True
	assert res["refunded"] == str(bond)
	assert credit_of(sentinel, direct_alice) == bond


# -- over-payment -----------------------------------------------------------------

def test_overpayment_is_credited_back_and_never_forfeited(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim", bond=REPORT_BOND * 5)
	assert res["bond_forfeited"] is True

	# Only the required bond is forfeited; the other four are the sender's.
	t = json.loads(sentinel.get_target(registered_target))
	assert t["accrued_compensation"] == str(REPORT_BOND)
	assert credit_of(sentinel, direct_alice) == REPORT_BOND * 4

	r = json.loads(sentinel.get_report(res["report_id"]))
	assert r["bond"] == str(REPORT_BOND)


def test_overpayment_on_supported_credits_everything(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim", bond=REPORT_BOND * 3)
	assert credit_of(sentinel, direct_alice) == REPORT_BOND * 3


# -- withdraw_credit ----------------------------------------------------------------

def _supported_report(sentinel, direct_vm, direct_alice, target):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, target, EXPLOIT_EVIDENCE_URL, "claim")
	direct_vm.deal(sentinel.address, REPORT_BOND)  # the chain credits the bond


def test_withdraw_credit_pays_out_and_zeroes_the_ledger(sentinel, registered_target, direct_vm, direct_alice):
	_supported_report(sentinel, direct_vm, direct_alice, registered_target)
	res = json.loads(sentinel.withdraw_credit(0))
	assert res["ok"] is True
	assert res["withdrawn"] == str(REPORT_BOND)
	assert res["remaining_credit"] == "0"
	assert credit_of(sentinel, direct_alice) == 0
	assert stats_of(sentinel)["credits_outstanding"] == "0"


def test_withdraw_credit_partial_then_rest(sentinel, registered_target, direct_vm, direct_alice):
	_supported_report(sentinel, direct_vm, direct_alice, registered_target)
	first = json.loads(sentinel.withdraw_credit(REPORT_BOND // 4))
	assert first["withdrawn"] == str(REPORT_BOND // 4)
	assert credit_of(sentinel, direct_alice) == REPORT_BOND - REPORT_BOND // 4
	second = json.loads(sentinel.withdraw_credit(10**30))  # more than owed -> clamps to everything
	assert second["withdrawn"] == str(REPORT_BOND - REPORT_BOND // 4)
	assert credit_of(sentinel, direct_alice) == 0


def test_withdraw_credit_twice_cannot_double_spend(sentinel, registered_target, direct_vm, direct_alice):
	_supported_report(sentinel, direct_vm, direct_alice, registered_target)
	sentinel.withdraw_credit(0)
	with pytest.raises(Exception):
		sentinel.withdraw_credit(0)


def test_withdraw_credit_with_no_credit_raises(sentinel, direct_vm, direct_charlie):
	direct_vm.sender = direct_charlie
	with pytest.raises(Exception):
		sentinel.withdraw_credit(0)


def test_nobody_can_withdraw_someone_elses_credit(
		sentinel, registered_target, direct_vm, direct_alice, direct_bob):
	_supported_report(sentinel, direct_vm, direct_alice, registered_target)
	direct_vm.sender = direct_bob  # bob has no credit of his own
	with pytest.raises(Exception):
		sentinel.withdraw_credit(REPORT_BOND)
	assert credit_of(sentinel, direct_alice) == REPORT_BOND


def test_withdraw_credit_refuses_when_balance_is_below_the_credit(
		sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	# balance deliberately left at zero: a ledger entry must never be paid
	# out of money the contract does not hold.
	with pytest.raises(Exception):
		sentinel.withdraw_credit(0)
	assert credit_of(sentinel, direct_alice) == REPORT_BOND  # untouched on failure


def test_pause_never_blocks_pulling_your_own_money(
		sentinel, registered_target, direct_vm, direct_owner, direct_alice):
	_supported_report(sentinel, direct_vm, direct_alice, registered_target)
	direct_vm.sender = direct_owner
	sentinel.set_paused(True)
	direct_vm.sender = direct_alice
	assert json.loads(sentinel.withdraw_credit(0))["ok"] is True


# -- the conservation invariant ---------------------------------------------------

def test_every_wei_is_accounted_for_across_a_mixed_history(
		sentinel, registered_target, direct_vm, direct_alice, direct_charlie, fake_clock):
	received = 0

	def settle(value):
		nonlocal received
		received += value
		direct_vm.deal(sentinel.address, received)

	# rejected (under-bonded), forfeited, inconclusive, supported halt, over-paid clear
	direct_vm.sender = direct_alice
	settle(REPORT_BOND // 2)
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "x", bond=REPORT_BOND // 2)

	mock_verdict(direct_vm, "NOT_SUPPORTED")
	settle(REPORT_BOND)
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "false alarm")

	direct_vm.sender = direct_charlie
	mock_verdict(direct_vm, "INCONCLUSIVE")
	settle(REPORT_BOND)
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "unclear")

	fake_clock.advance(ACTION_COOLDOWN + 1)
	mock_verdict(direct_vm, "SUPPORTED")
	settle(REPORT_BOND)
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "real exploit")

	fake_clock.advance(ACTION_COOLDOWN + 1)
	mock_verdict(direct_vm, "SUPPORTED")
	settle(REPORT_BOND * 3)
	clear(sentinel, direct_vm, registered_target, CLEAR_EVIDENCE_URL, "fixed", bond=REPORT_BOND * 3)

	stats = stats_of(sentinel)
	assert int(stats["on_chain_balance"]) == received
	assert int(stats["credits_outstanding"]) + int(stats["compensation_outstanding"]) == received

	# After a pull, the ledger shrinks by exactly what was withdrawn. (The
	# on-chain balance only drops once the chain applies the transfer, which
	# Direct Mode does not simulate, so the ledger side is what is asserted.)
	before = int(stats["credits_outstanding"])
	owed = credit_of(sentinel, direct_charlie)
	assert owed > 0
	res = json.loads(sentinel.withdraw_credit(0))
	assert res["withdrawn"] == str(owed)
	after = stats_of(sentinel)
	assert int(after["credits_outstanding"]) == before - owed
	assert credit_of(sentinel, direct_charlie) == 0
	# the forfeited bond is still owed to the registrant
	assert after["compensation_outstanding"] == str(REPORT_BOND)
