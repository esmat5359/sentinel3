"""
Runs scripts/live_e2e.py's REAL scenarios through Direct Mode.

The live script cannot be exercised without a funded network, so its logic is
tested here against the real SentinelHalt code, with evidence pages and the LLM
mocked per fixture. That catches script bugs (wrong assertions, bad state
bookkeeping, report rendering) before a live run burns minutes on them.

Scenarios that need a second deployed contract (the vault's cross-contract
call) are skipped by design: that link is exactly what only a live network can
prove. Contract-side behavior is covered by the other files in this directory.
"""
import json
import pathlib
import re
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import live_e2e as e2e  # noqa: E402

VERDICTS = {
	"exploit_active": "SUPPORTED", "postmortem_fixed": "SUPPORTED",
	"benign_status": "NOT_SUPPORTED", "generic_security_article": "NOT_SUPPORTED",
	"historical_patched": "NOT_SUPPORTED", "injection_attack": "NOT_SUPPORTED",
}


class DirectEnv:
	live = False
	cross_contract = False
	models_transfers = True

	def __init__(self, deploy, vm, clock, accounts):
		self._deploy, self.vm, self.clock = deploy, vm, clock
		self.accounts = accounts
		self.contract = None
		self.balance = 0
		self._n = 0
		vm.clear_mocks()
		for name in e2e.FIXTURES:
			body = "" if name == "empty" else "MARK_" + name
			vm.mock_web(r"/%s\.md$" % name, {"status": 200, "body": body})
			if name in VERDICTS:
				payload = json.dumps({"verdict": VERDICTS[name], "confidence": 90, "reasoning": "stub"})
				vm.mock_llm("MARK_" + name, "```json\n" + payload + "\n```")

	def address(self, role):
		a = self.accounts[role]
		if isinstance(a, (bytes, bytearray)):
			import genlayer.types as gt
			return str(gt.Address(bytes(a)))
		return str(a)

	def fresh_address(self):
		self._n += 1
		return "0x" + ("%040x" % (0xabc000 + self._n))

	def evidence(self, name):
		return "https://fixtures.test/%s.md" % name

	def sleep(self, seconds):
		self.clock.advance(int(seconds))

	def deploy(self, role, name, args):
		assert name == "SentinelHalt"
		self.vm.sender = self.accounts[role]
		self.contract = self._deploy("contracts/SentinelHalt.py", *args)
		return str(self.contract.address), ""

	def write(self, role, addr, method, args, value=0):
		self.vm.sender = self.accounts[role]
		self.vm.value = value
		if value:
			self.balance += value
			self.vm.deal(self.contract.address, self.balance)
		try:
			raw = getattr(self.contract, method)(*args)
		except Exception as e:  # a revert: the chain hands the value back
			if value:
				self.balance -= value
				self.vm.deal(self.contract.address, self.balance)
			return e2e.Tx(False, "", "reverted", None, str(e)[:200])
		finally:
			self.vm.value = 0
		ret = json.loads(raw) if isinstance(raw, str) and raw[:1] == "{" else None
		if ret and method in ("withdraw_credit", "claim_compensation") and ret.get("withdrawn"):
			self.balance -= int(ret["withdrawn"])
			self.vm.deal(self.contract.address, self.balance)
		return e2e.Tx(True, "", "accepted", ret, "")

	def read(self, addr, method, args):
		v = getattr(self.contract, method)(*args)
		return json.loads(v) if isinstance(v, str) and v[:1] in "{[" else v


def make_args(**over):
	base = dict(retries=1, cooldown=60, settle=0, strict_transfers=True, quick=False)
	base.update(over)
	return types.SimpleNamespace(**base)


@pytest.fixture
def env(deploy, direct_vm, fake_clock, direct_owner, direct_alice, direct_bob, direct_charlie, direct_accounts):
	accounts = {"owner": direct_owner, "maintainer": direct_bob, "reporter": direct_alice,
				"attacker": direct_charlie, "stranger": direct_accounts[7]}
	return DirectEnv(deploy, direct_vm, fake_clock, accounts)


def test_every_offline_scenario_passes_against_the_real_contract(env):
	ctx = e2e.Ctx(env, make_args())
	results = e2e.run_all(ctx)
	by_id = {r.id: r for r in results}
	failed = {r.id: r.detail for r in results if r.status == e2e.FAIL}
	assert not failed, failed

	# the scenarios that need a live network are skipped, everything else ran and passed
	live_only = {"F3", "F7", "F9", "A7", "A8"}
	for r in results:
		if r.id in live_only:
			assert r.status == e2e.SKIP, r.id
		else:
			assert r.status in (e2e.PASS, e2e.WARN), (r.id, r.status, r.detail)
	assert by_id["F5"].status == e2e.PASS and by_id["F8"].status == e2e.PASS
	assert by_id["Z1"].status == e2e.PASS
	assert ctx.invariants and ctx.invariants[-1]["status"] == "equal"


def test_the_script_catches_a_vault_that_never_gets_halted(env):
	"""A scenario that cannot fail is worthless: make the judge refuse the real
	exploit and check the run reports FAIL and skips what depends on it."""
	VERDICTS_BACKUP = dict(VERDICTS)
	try:
		VERDICTS["exploit_active"] = "NOT_SUPPORTED"
		env2 = DirectEnv(env._deploy, env.vm, env.clock, env.accounts)
		ctx = e2e.Ctx(env2, make_args())
		by_id = {r.id: r for r in e2e.run_all(ctx)}
	finally:
		VERDICTS.clear(); VERDICTS.update(VERDICTS_BACKUP)
	assert by_id["F5"].status == e2e.FAIL
	assert by_id["F6"].status == e2e.SKIP and by_id["F8"].status == e2e.SKIP


def test_the_script_flags_an_unsafe_supported_verdict_on_hostile_evidence(env):
	VERDICTS_BACKUP = dict(VERDICTS)
	try:
		VERDICTS["injection_attack"] = "SUPPORTED"
		env2 = DirectEnv(env._deploy, env.vm, env.clock, env.accounts)
		ctx = e2e.Ctx(env2, make_args())
		by_id = {r.id: r for r in e2e.run_all(ctx)}
	finally:
		VERDICTS.clear(); VERDICTS.update(VERDICTS_BACKUP)
	assert by_id["A9"].status == e2e.FAIL and "UNSAFE" in by_id["A9"].detail


def test_report_renders_and_injects_into_a_readme(env, tmp_path):
	ctx = e2e.Ctx(env, make_args(quick=True))
	results = e2e.run_all(ctx)
	md = e2e.render_markdown({"network": "offline", "chain id": 0, "contracts": {"SentinelHalt": "0x1"}},
	                         results, ctx.invariants)
	assert "Live end-to-end report" in md and "| F5 |" in md
	readme = tmp_path / "README.md"
	readme.write_text("# T\n\n" + e2e.MARKER_START + "\nSTALE_BLOCK_XYZ\n" + e2e.MARKER_END + "\n\nfooter\n")
	e2e.inject_readme(readme, md)
	text = readme.read_text()
	assert "STALE_BLOCK_XYZ" not in text and "footer" in text and text.count(e2e.MARKER_START) == 1
	e2e.inject_readme(readme, md)  # idempotent
	assert readme.read_text().count(e2e.MARKER_START) == 1
	bare = tmp_path / "B.md"
	bare.write_text("# no markers")
	e2e.inject_readme(bare, md)
	assert e2e.MARKER_START in bare.read_text()
