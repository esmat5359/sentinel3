"""
Direct Mode tests for contracts/SentinelHalt.py.

Direct Mode runs the actual contract source against genlayer-test's
in-process GenVM-compatible interpreter -- no chain, no network, no mocked
reimplementation of the contract's logic. Every test below exercises the
real, shipped contract file.

Use the `deploy` fixture (from conftest.py) instead of genlayer-test's own
`direct_deploy` -- it is a drop-in replacement that additionally makes
gl.vm.get_timestamp() work, which this contract relies on for every
timestamped action. See conftest.py's module docstring for why, and for why
each test file defines its own `addr_str` helper.

Run with:  gltest tests/direct/test_sentinel_halt.py -v
       or:  python3 -m pytest tests/direct/test_sentinel_halt.py -v
"""
import json

import pytest


REPORT_BOND = 10**16  # matches DEFAULT_REPORT_BOND in the contract
ACTION_COOLDOWN = 300  # matches DEFAULT_ACTION_COOLDOWN_SECONDS in the contract

EXPLOIT_EVIDENCE_URL = "https://explorer.example.com/tx/0xdeadbeef"
CLEAR_EVIDENCE_URL = "https://example.com/postmortem"


def addr_str(value) -> str:
	"""direct_alice/direct_bob/direct_owner/etc. are genlayer Address
	objects if the SDK is already on sys.path by the time that fixture
	runs, or raw bytes otherwise -- which of the two depends on fixture
	instantiation order (whether something that deploys a contract was
	requested earlier in the same test's parameter list), not on which
	named account it is. See conftest.py's module docstring."""
	if isinstance(value, (bytes, bytearray)):
		import genlayer.types as gt
		return str(gt.Address(bytes(value)))
	return str(value)


def mock_verdict(direct_vm, verdict, confidence=85, reasoning="evaluated", content="some evidence content"):
	"""Point both non-deterministic primitives at a fixed, well-formed
	response, matching exactly what _judge expects to parse.

	The LLM response is wrapped in a markdown fence deliberately. Direct
	Mode's mock_llm auto-parses any registered string that happens to be
	valid bare JSON into a dict before the SDK ever sees it -- which then
	fails the SDK's own text-result check, since exec_prompt in text mode
	expects a plain string and does its own parsing. Fencing the JSON
	makes Direct Mode's naive `json.loads` attempt fail (so it is kept as
	a string), and exercises _clean_json's markdown-fence handling for
	real in the process -- the same defensive path a real LLM's own
	occasional fencing would hit.

	mock_web/mock_llm append to a list and the first pattern match wins,
	so calling this a second time in one test (e.g. a different verdict
	for a clear_halt after a report_exploit) would otherwise silently
	keep matching the first registration instead of the new one.
	"""
	direct_vm.clear_mocks()
	direct_vm.mock_web(r".*", {"status": 200, "body": content})
	payload = json.dumps({"verdict": verdict, "confidence": confidence, "reasoning": reasoning})
	direct_vm.mock_llm(r".*", "```json\n" + payload + "\n```")


def mock_llm_malformed(direct_vm, content="some evidence content"):
	direct_vm.clear_mocks()
	direct_vm.mock_web(r".*", {"status": 200, "body": content})
	direct_vm.mock_llm(r".*", "this is not json at all")


def report(sentinel, direct_vm, target, url, claim, bond=REPORT_BOND):
	"""report_exploit is payable: GEN value in Direct Mode is set on the
	shared vm (mirroring how `direct_vm.sender` works), not passed as a
	call argument. Resets to 0 immediately after so a later non-payable
	call in the same test never accidentally carries a leftover value."""
	direct_vm.value = bond
	result = json.loads(sentinel.report_exploit(target, url, claim))
	direct_vm.value = 0
	return result


def clear(sentinel, direct_vm, target, url, claim, bond=REPORT_BOND):
	direct_vm.value = bond
	result = json.loads(sentinel.clear_halt(target, url, claim))
	direct_vm.value = 0
	return result


@pytest.fixture
def sentinel(deploy, direct_owner, direct_vm):
	direct_vm.sender = direct_owner
	return deploy("contracts/SentinelHalt.py", REPORT_BOND, ACTION_COOLDOWN)


@pytest.fixture
def registered_target(sentinel, direct_vm, direct_bob):
	"""A registered target address, owned (registered_by) by direct_bob.
	SentinelHalt never deploys or calls the target itself -- registration
	only needs an address, so a plain address string is enough to exercise
	every rule in this contract without depending on a second contract
	deployment at all."""
	target_address = "0x" + "ab" * 20
	direct_vm.sender = direct_bob
	res = json.loads(sentinel.register_target(target_address, "Demo Protocol", "A protocol used for testing."))
	assert res["ok"] is True
	return target_address


# -- construction & config --------------------------------------------------

def test_constructor_sets_owner_and_clamps_bond(deploy, direct_owner, direct_vm):
	direct_vm.sender = direct_owner
	s = deploy("contracts/SentinelHalt.py", 1, 0)  # far below MIN_REPORT_BOND
	cfg = json.loads(s.get_config())
	assert cfg["owner"] == addr_str(direct_owner)
	assert cfg["report_bond"] == cfg["min_report_bond"]


# -- registration -------------------------------------------------------------

def test_register_target_success(sentinel, direct_vm, direct_bob):
	target_address = "0x" + "11" * 20
	direct_vm.sender = direct_bob
	res = json.loads(sentinel.register_target(target_address, "My Protocol", "Does things."))
	assert res["ok"] is True
	assert res["status"] == "SAFE"

	t = json.loads(sentinel.get_target(target_address))
	assert t["found"] is True
	assert t["status"] == "SAFE"
	assert t["registered_by"] == addr_str(direct_bob)
	assert t["report_count"] == 0


def test_register_target_rejects_duplicate(sentinel, registered_target, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		sentinel.register_target(registered_target, "Someone Else's Name", "Different scope.")


def test_register_target_rejects_self_registration(sentinel, direct_vm, direct_owner):
	direct_vm.sender = direct_owner
	with pytest.raises(Exception):
		sentinel.register_target(str(sentinel.address), "Self", "Should be rejected.")


def test_register_target_rejects_oversized_name(sentinel, direct_vm, direct_bob):
	direct_vm.sender = direct_bob
	with pytest.raises(Exception):
		sentinel.register_target("0x" + "22" * 20, "x" * 200, "scope")


def test_update_scope_only_by_registrant(sentinel, registered_target, direct_vm, direct_alice, direct_bob):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		sentinel.update_scope(registered_target, "hijacked scope")

	direct_vm.sender = direct_bob
	res = json.loads(sentinel.update_scope(registered_target, "updated scope text"))
	assert res["ok"] is True
	t = json.loads(sentinel.get_target(registered_target))
	assert t["scope"] == "updated scope text"


# -- report_exploit: payable-never-raises, rejection paths ----------------------

def test_report_exploit_unknown_target_refunds(sentinel, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, "0x" + "99" * 20, EXPLOIT_EVIDENCE_URL, "claim")
	assert res["ok"] is False
	assert res["refunded"] == str(REPORT_BOND)


def test_report_exploit_insufficient_bond_refunds(sentinel, registered_target, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	short = REPORT_BOND - 1
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim", bond=short)
	assert res["ok"] is False
	assert res["refunded"] == str(short)


def test_report_exploit_while_paused_refunds(sentinel, registered_target, direct_vm, direct_owner, direct_alice):
	direct_vm.sender = direct_owner
	sentinel.set_paused(True)

	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	assert res["ok"] is False
	assert "paused" in res["reason"]


def test_report_exploit_empty_claim_refunds(sentinel, registered_target, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "")
	assert res["ok"] is False


# -- report_exploit: AI-judged resolution -----------------------------------

def test_report_exploit_supported_halts_target_and_returns_bond(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED", confidence=91, reasoning="Active drain confirmed on-chain")
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "Active exploit draining funds")

	assert res["ok"] is True
	assert res["verdict"] == "SUPPORTED"
	assert res["status"] == "HALTED"
	assert res["bond_forfeited"] is False

	t = json.loads(sentinel.get_target(registered_target))
	assert t["status"] == "HALTED"
	assert t["report_count"] == 1
	assert t["halt_count"] == 1

	assert sentinel.is_halted(registered_target) is True

	stats = json.loads(sentinel.get_stats())
	assert stats["supported"] == 1


def test_report_exploit_not_supported_forfeits_bond_to_registrant(
		sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "NOT_SUPPORTED", confidence=70, reasoning="No evidence of an exploit")
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "I think something is wrong")

	assert res["ok"] is True
	assert res["verdict"] == "NOT_SUPPORTED"
	assert res["status"] == "SAFE"  # unaffected
	assert res["bond_forfeited"] is True

	t = json.loads(sentinel.get_target(registered_target))
	assert t["available_compensation"] == str(REPORT_BOND)

	stats = json.loads(sentinel.get_reporter_stats(addr_str(direct_alice)))
	assert stats["not_supported_count"] == 1


def test_report_exploit_inconclusive_changes_nothing_and_returns_bond(
		sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "INCONCLUSIVE", confidence=0, reasoning="Content unrelated to this contract")
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")

	assert res["ok"] is True
	assert res["verdict"] == "INCONCLUSIVE"
	assert res["status"] == "SAFE"
	assert res["bond_forfeited"] is False

	t = json.loads(sentinel.get_target(registered_target))
	assert t["available_compensation"] == "0"


def test_report_exploit_already_halted_refunds(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	first = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")
	assert first["status"] == "HALTED"

	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim again")
	assert res["ok"] is False
	assert "already" in res["reason"]


# -- clear_halt: mirrors report_exploit, requires HALTED -----------------------

def test_clear_halt_requires_halted_status(sentinel, registered_target, direct_vm, direct_bob):
	direct_vm.sender = direct_bob
	res = clear(sentinel, direct_vm, registered_target, CLEAR_EVIDENCE_URL, "all clear")
	assert res["ok"] is False
	assert "not halted" in res["reason"]


def test_clear_halt_supported_restores_safe_status(
		sentinel, registered_target, direct_vm, direct_alice, direct_bob, fake_clock):
	mock_verdict(direct_vm, "SUPPORTED", reasoning="Exploit confirmed active")
	direct_vm.sender = direct_alice
	halted = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "active exploit")
	assert halted["status"] == "HALTED"

	# HALT and CLEAR on the same target share one cooldown clock by design
	# -- a target should not be able to flip states again immediately.
	fake_clock.advance(ACTION_COOLDOWN + 1)

	mock_verdict(direct_vm, "SUPPORTED", reasoning="Patch deployed and verified")
	direct_vm.sender = direct_bob
	cleared = clear(sentinel, direct_vm, registered_target, CLEAR_EVIDENCE_URL, "patched and verified safe")
	assert cleared["ok"] is True
	assert cleared["status"] == "SAFE"
	assert sentinel.is_halted(registered_target) is False


def test_clear_halt_not_supported_keeps_halted_and_forfeits_bond(
		sentinel, registered_target, direct_vm, direct_alice, direct_bob, fake_clock):
	mock_verdict(direct_vm, "SUPPORTED", reasoning="Exploit confirmed active")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "active exploit")

	fake_clock.advance(ACTION_COOLDOWN + 1)

	mock_verdict(direct_vm, "NOT_SUPPORTED", reasoning="No evidence the issue was actually fixed")
	direct_vm.sender = direct_bob
	res = clear(sentinel, direct_vm, registered_target, CLEAR_EVIDENCE_URL, "should be fine now")
	assert res["ok"] is True
	assert res["status"] == "HALTED"
	assert res["bond_forfeited"] is True


# -- infrastructure failures never raise from a payable path, never become a verdict --

def test_report_exploit_web_failure_returns_retry_later(sentinel, registered_target, direct_vm, direct_alice):
	# Deliberately no mock_web registered at all: GenVM's WebRender call has
	# nothing to match against and raises MockNotFoundError, exactly the
	# shape of a real fetch failure (DNS, timeout, connection reset) from
	# _judge's point of view -- it only ever sees "the call raised".
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")

	assert res["ok"] is True
	assert res["verdict"] == "RETRY_LATER"
	assert res["status"] == "SAFE"  # left exactly as it was

	stats = json.loads(sentinel.get_stats())
	assert stats["retry_later"] == 1
	assert stats["supported"] == 0
	assert stats["not_supported"] == 0
	assert stats["inconclusive"] == 0  # a retry is not a verdict either


def test_report_exploit_llm_unavailable_returns_retry_later(sentinel, registered_target, direct_vm, direct_alice):
	# The page fetch succeeds, but no mock_llm is registered, so the
	# exec_prompt call raises MockNotFoundError -- the shape of a real LLM
	# provider outage.
	direct_vm.mock_web(r".*", {"status": 200, "body": "some evidence content"})
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")

	assert res["ok"] is True
	assert res["verdict"] == "RETRY_LATER"


def test_report_exploit_malformed_llm_output_returns_retry_later(
		sentinel, registered_target, direct_vm, direct_alice):
	mock_llm_malformed(direct_vm)
	direct_vm.sender = direct_alice
	res = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim")

	assert res["ok"] is True
	assert res["verdict"] == "RETRY_LATER"


# -- preview_action: non-binding -----------------------------------------------

def test_preview_action_does_not_mutate_state_or_require_bond(
		sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "SUPPORTED")
	direct_vm.sender = direct_alice
	res = json.loads(sentinel.preview_action(
		registered_target, "HALT", EXPLOIT_EVIDENCE_URL, "hypothetical claim"))

	assert res["ok"] is True
	assert res["preview_verdict"] == "SUPPORTED"
	assert res["binding"] is False

	t = json.loads(sentinel.get_target(registered_target))
	assert t["status"] == "SAFE"  # unchanged
	assert t["report_count"] == 0  # no report was recorded


def test_preview_action_rejects_unknown_action_name(sentinel, registered_target, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		sentinel.preview_action(registered_target, "NUKE", EXPLOIT_EVIDENCE_URL, "claim")


# -- cooldown -------------------------------------------------------------------

def test_action_cooldown_blocks_rapid_repeated_reports(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	first = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "first claim")
	assert first["ok"] is True  # resolved (NOT_SUPPORTED), not rejected

	second = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "second claim immediately after")
	assert second["ok"] is False
	assert "cooling down" in second["reason"]


def test_action_cooldown_lifts_once_it_elapses(sentinel, registered_target, direct_vm, direct_alice, fake_clock):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "first claim")

	fake_clock.advance(ACTION_COOLDOWN + 1)

	mock_verdict(direct_vm, "SUPPORTED")
	second = report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "second claim after cooldown")
	assert second["ok"] is True
	assert second["verdict"] == "SUPPORTED"


# -- claim_compensation ------------------------------------------------------------

def test_claim_compensation_only_by_registrant(sentinel, registered_target, direct_vm, direct_alice, direct_bob):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "bogus claim")

	direct_vm.sender = direct_alice  # not the registrant (direct_bob registered this target)
	with pytest.raises(Exception):
		sentinel.claim_compensation(registered_target, addr_str(direct_alice), REPORT_BOND)


def test_claim_compensation_is_not_blocked_by_other_peoples_refunds(
		sentinel, registered_target, direct_vm, direct_alice, direct_bob, fake_clock):
	# Regression: compensation used to be gated on a global "time since the last
	# outbound transfer". Any refund to anyone reset that clock, so a stranger
	# could keep the registrant from ever claiming. Refunds are credits now and
	# claims are gated only by what was actually accrued.
	mock_verdict(direct_vm, "INCONCLUSIVE")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "first claim")

	fake_clock.advance(ACTION_COOLDOWN + 1)
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "second claim")

	direct_vm.deal(sentinel.address, REPORT_BOND * 10)
	direct_vm.sender = direct_bob
	res = json.loads(sentinel.claim_compensation(registered_target, addr_str(direct_bob), REPORT_BOND))
	assert res["ok"] is True


def test_claim_compensation_pays_accrued_amount_and_debits_ledger(
		sentinel, registered_target, direct_vm, direct_alice, direct_bob, fake_clock):
	mock_verdict(direct_vm, "NOT_SUPPORTED")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "false alarm")

	# claim_compensation caps a withdrawal at self.balance as a safety net.
	# Direct Mode does not credit a contract's balance automatically when a
	# payable call carries value (direct_vm.value only controls what
	# gl.message.value reports for that one call), so credit it by hand. A real
	# deployment does not need this: the chain credits the GEN itself.
	direct_vm.deal(sentinel.address, REPORT_BOND * 10)

	direct_vm.sender = direct_bob
	res = json.loads(sentinel.claim_compensation(registered_target, addr_str(direct_bob), REPORT_BOND))
	assert res["ok"] is True
	assert res["withdrawn"] == str(REPORT_BOND)

	t = json.loads(sentinel.get_target(registered_target))
	assert t["available_compensation"] == "0"
	assert json.loads(sentinel.get_stats())["compensation_outstanding"] == "0"


# -- owner-only controls -----------------------------------------------------------

def test_set_paused_owner_only(sentinel, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		sentinel.set_paused(True)


def test_set_report_bond_owner_only_and_clamped(sentinel, direct_vm, direct_owner):
	direct_vm.sender = direct_owner
	res = json.loads(sentinel.set_report_bond(10**30))  # far above MAX_REPORT_BOND
	assert res["ok"] is True
	cfg = json.loads(sentinel.get_config())
	assert cfg["report_bond"] == cfg["max_report_bond"]


def test_transfer_ownership(sentinel, direct_vm, direct_owner, direct_alice):
	direct_vm.sender = direct_owner
	res = json.loads(sentinel.transfer_ownership(addr_str(direct_alice)))
	assert res["ok"] is True

	direct_vm.sender = direct_owner  # old owner can no longer act
	with pytest.raises(Exception):
		sentinel.set_paused(True)

	direct_vm.sender = direct_alice
	res2 = json.loads(sentinel.set_paused(True))
	assert res2["ok"] is True


# -- views: pagination and listing -------------------------------------------------

def test_get_targets_pagination(sentinel, direct_vm, direct_bob):
	direct_vm.sender = direct_bob
	for i in range(5):
		sentinel.register_target("0x" + str(i) * 40, "Protocol " + str(i), "scope")

	page = json.loads(sentinel.get_targets(0, 3))
	assert page["total"] == 5
	assert page["count"] == 3

	page2 = json.loads(sentinel.get_targets(3, 3))
	assert page2["count"] == 2


def test_get_target_reports_lists_history(sentinel, registered_target, direct_vm, direct_alice):
	mock_verdict(direct_vm, "INCONCLUSIVE")
	direct_vm.sender = direct_alice
	report(sentinel, direct_vm, registered_target, EXPLOIT_EVIDENCE_URL, "claim one")

	history = json.loads(sentinel.get_target_reports(registered_target))
	assert history["count"] == 1
	assert history["reports"][0]["verdict"] == "INCONCLUSIVE"


def test_get_target_unregistered_reports_not_found(sentinel):
	res = json.loads(sentinel.get_target("0x" + "ff" * 20))
	assert res["found"] is False
