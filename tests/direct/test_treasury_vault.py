"""
Direct Mode tests for contracts/TreasuryVault.py.

One limitation shapes this whole file and is worth stating up front:
TreasuryVault's only real dependency is a single cross-contract view() call
to SentinelHalt (`self._oracle().view().is_halted(...)`), and genlayer-test
0.30.0rc2's Direct Mode does not route that call to a second deployed
contract unless a test manually installs a `_gl_call_hook` (confirmed by
reading wasi_mock.py: an unhandled `CallContract` request silently falls
through an "unknown request" path rather than actually invoking the second
contract's code). `patch_halted`, defined below, works around this by
patching `TreasuryVault._halted` directly at the class level -- not
touching the real oracle call at all -- so that deposit()/withdraw()'s own
accounting and access-control logic can be tested in isolation from a
dependency this harness cannot yet simulate for real.

The genuine end-to-end integration -- an actually deployed SentinelHalt
actually being asked, and a report actually halting live enforcement on the
vault -- is exercised in tests/integration/test_sentinel_vault.py instead,
which runs against a real GenVM network (Studio Devnet) where cross-contract
calls are the real thing, not a mock.

Run with:  gltest tests/direct/test_treasury_vault.py -v
       or:  python3 -m pytest tests/direct/test_treasury_vault.py -v
"""
import json
import sys

import pytest


ONE_GEN = 10**18


def addr_str(value) -> str:
	"""direct_alice/direct_bob/direct_owner/etc. are genlayer Address
	objects if the SDK is already on sys.path by the time that fixture
	runs, or raw bytes otherwise, depending on fixture instantiation order
	-- see conftest.py's module docstring. Comparing a raw-bytes fixture
	value directly against a contract-returned hex string, or passing it
	straight into a contract call, silently does the wrong thing."""
	if isinstance(value, (bytes, bytearray)):
		import genlayer.types as gt
		return str(gt.Address(bytes(value)))
	return str(value)


def _find_contract_class(class_name):
	for mod in list(sys.modules.values()):
		if mod is None:
			continue
		candidate = getattr(mod, class_name, None)
		if isinstance(candidate, type) and candidate.__name__ == class_name:
			return candidate
	raise RuntimeError(class_name + " not found in sys.modules -- deploy it first")


@pytest.fixture
def patch_halted(monkeypatch):
	def _apply(halted: bool):
		cls = _find_contract_class("TreasuryVault")
		monkeypatch.setattr(cls, "_halted", lambda self: halted)
	return _apply


@pytest.fixture
def sentinel_address():
	"""TreasuryVault only ever stores this address and asks it a question
	through the (here, patched) oracle call -- it never needs a real
	SentinelHalt deployment for its own logic to be tested, so a fixed
	placeholder is deliberate rather than deriving one from a named
	account fixture, which would tie this fixture's own correctness to
	fixture-instantiation ordering for no benefit (see conftest.py)."""
	return "0x" + "5e" * 20


@pytest.fixture
def vault(deploy, direct_owner, direct_vm, sentinel_address, patch_halted):
	direct_vm.sender = direct_owner
	contract = deploy("contracts/TreasuryVault.py", sentinel_address)
	patch_halted(False)  # tests opt into halted=True explicitly where it matters
	return contract


def deposit(vault, direct_vm, amount):
	direct_vm.value = amount
	result = json.loads(vault.deposit())
	direct_vm.value = 0
	return result


# -- construction & config --------------------------------------------------

def test_constructor_sets_owner_and_sentinel(vault, direct_owner, sentinel_address):
	cfg = json.loads(vault.get_config())
	# Address.__str__ returns an EIP-55 checksummed (mixed-case) form; the
	# fixture above is plain lowercase, so compare case-insensitively.
	assert cfg["sentinel"].lower() == sentinel_address.lower()
	assert cfg["halted"] is False


# -- deposit: payable-never-raises -------------------------------------------

def test_deposit_success_credits_balance_and_registers_holder(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	res = deposit(vault, direct_vm, ONE_GEN)
	assert res["ok"] is True
	assert res["new_balance"] == str(ONE_GEN)

	bal = json.loads(vault.get_balance_of(addr_str(direct_alice)))
	assert bal["balance"] == str(ONE_GEN)

	holders = json.loads(vault.get_holders(0, 10))
	assert holders["total"] == 1
	assert holders["holders"][0]["address"] == addr_str(direct_alice)


def test_deposit_accumulates_across_multiple_calls(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)
	res = deposit(vault, direct_vm, 2 * ONE_GEN)
	assert res["new_balance"] == str(3 * ONE_GEN)

	holders = json.loads(vault.get_holders(0, 10))
	assert holders["total"] == 1  # still one holder, not two entries


def test_deposit_tracks_distinct_holders_separately(vault, direct_vm, direct_alice, direct_bob):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)
	direct_vm.sender = direct_bob
	deposit(vault, direct_vm, 2 * ONE_GEN)

	holders = json.loads(vault.get_holders(0, 10))
	assert holders["total"] == 2
	addrs = {h["address"]: h["balance"] for h in holders["holders"]}
	assert addrs[addr_str(direct_alice)] == str(ONE_GEN)
	assert addrs[addr_str(direct_bob)] == str(2 * ONE_GEN)


def test_deposit_below_minimum_refunds_instead_of_raising(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	res = deposit(vault, direct_vm, 1)  # far below MIN_DEPOSIT
	assert res["ok"] is False
	assert res["refunded"] == "1"

	bal = json.loads(vault.get_balance_of(addr_str(direct_alice)))
	assert bal["balance"] == "0"


def test_deposit_while_halted_refunds_instead_of_raising(vault, direct_vm, direct_alice, patch_halted):
	patch_halted(True)
	direct_vm.sender = direct_alice
	res = deposit(vault, direct_vm, ONE_GEN)
	assert res["ok"] is False
	assert res["reason"] == "vault is halted"
	assert res["refunded"] == str(ONE_GEN)


# -- withdraw: the actual enforcement ------------------------------------------

def test_withdraw_success_debits_balance(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)

	res = json.loads(vault.withdraw(4 * 10**17))
	assert res["ok"] is True
	assert res["remaining_balance"] == str(ONE_GEN - 4 * 10**17)

	bal = json.loads(vault.get_balance_of(addr_str(direct_alice)))
	assert bal["balance"] == str(ONE_GEN - 4 * 10**17)


def test_withdraw_blocked_while_halted(vault, direct_vm, direct_alice, patch_halted):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)

	patch_halted(True)
	with pytest.raises(Exception):
		vault.withdraw(10**17)

	# the balance-debit half of a withdrawal never even starts
	bal = json.loads(vault.get_balance_of(addr_str(direct_alice)))
	assert bal["balance"] == str(ONE_GEN)


def test_withdraw_rejects_amount_exceeding_balance(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)
	with pytest.raises(Exception):
		vault.withdraw(ONE_GEN + 1)


def test_withdraw_rejects_non_positive_amount(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)
	with pytest.raises(Exception):
		vault.withdraw(0)


def test_halt_then_clear_unblocks_withdrawals_again(vault, direct_vm, direct_alice, patch_halted):
	"""Not a real SentinelHalt round-trip (see the module docstring) --
	just confirms the vault re-checks fresh on every call rather than
	caching a stale answer, which is the property the live design is
	actually for."""
	direct_vm.sender = direct_alice
	deposit(vault, direct_vm, ONE_GEN)

	patch_halted(True)
	with pytest.raises(Exception):
		vault.withdraw(10**17)

	patch_halted(False)
	res = json.loads(vault.withdraw(10**17))
	assert res["ok"] is True


# -- owner ----------------------------------------------------------------------

def test_set_sentinel_owner_only(vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		vault.set_sentinel(addr_str(direct_alice))


def test_set_sentinel_updates_config(vault, direct_vm, direct_owner, direct_alice):
	direct_vm.sender = direct_owner
	res = json.loads(vault.set_sentinel(addr_str(direct_alice)))
	assert res["ok"] is True
	cfg = json.loads(vault.get_config())
	assert cfg["sentinel"] == addr_str(direct_alice)


# -- views ------------------------------------------------------------------------

def test_get_balance_of_unknown_address_is_zero(vault, direct_alice):
	bal = json.loads(vault.get_balance_of(addr_str(direct_alice)))
	assert bal["balance"] == "0"


def test_get_holders_pagination(vault, direct_vm, direct_alice, direct_bob, direct_charlie):
	for who in (direct_alice, direct_bob, direct_charlie):
		direct_vm.sender = who
		deposit(vault, direct_vm, ONE_GEN)

	page = json.loads(vault.get_holders(0, 2))
	assert page["total"] == 3
	assert page["count"] == 2

	page2 = json.loads(vault.get_holders(2, 2))
	assert page2["count"] == 1


def test_is_halted_reflects_patched_oracle(vault, patch_halted):
	assert vault.is_halted() is False
	patch_halted(True)
	assert vault.is_halted() is True


# -- fail-closed oracle ----------------------------------------------------------
#
# The tests above patch `_halted` itself. These patch only the oracle handle,
# so the REAL `_halted` runs against every shape of answer a broken or hostile
# oracle could give. Only an explicit False may open the vault.

class _StubOracle:
	def __init__(self, answer):
		self.answer = answer

	def view(self):
		return self

	def is_halted(self, target):
		if isinstance(self.answer, BaseException):
			raise self.answer
		return self.answer


@pytest.fixture
def raw_vault(deploy, direct_owner, direct_vm, sentinel_address):
	"""A vault whose real `_halted` is left in place."""
	direct_vm.sender = direct_owner
	return deploy("contracts/TreasuryVault.py", sentinel_address)


def _stub_oracle(monkeypatch, answer):
	monkeypatch.setattr(_find_contract_class("TreasuryVault"), "_oracle", lambda self: _StubOracle(answer))


@pytest.mark.parametrize("answer,expected", [
	(False, False),
	(True, True),
	(None, True),
	(0, True),
	(1, True),
	("", True),
	("false", True),
	([], True),
	(RuntimeError("oracle unreachable"), True),
	(KeyError("no such method"), True),
])
def test_vault_opens_only_when_the_oracle_says_exactly_false(raw_vault, monkeypatch, answer, expected):
	_stub_oracle(monkeypatch, answer)
	assert raw_vault.is_halted() is expected


def test_withdraw_is_blocked_when_the_oracle_is_down(raw_vault, direct_vm, direct_alice, monkeypatch):
	_stub_oracle(monkeypatch, False)
	direct_vm.sender = direct_alice
	assert deposit(raw_vault, direct_vm, ONE_GEN)["ok"] is True

	_stub_oracle(monkeypatch, RuntimeError("oracle unreachable"))
	with pytest.raises(Exception):
		raw_vault.withdraw(ONE_GEN // 2)
	assert json.loads(raw_vault.get_balance_of(addr_str(direct_alice)))["balance"] == str(ONE_GEN)


def test_deposit_is_refused_not_raised_when_the_oracle_is_down(raw_vault, direct_vm, direct_alice, monkeypatch):
	_stub_oracle(monkeypatch, None)  # not an explicit False
	direct_vm.sender = direct_alice
	res = deposit(raw_vault, direct_vm, ONE_GEN)
	assert res["ok"] is False
	assert res["refunded"] == str(ONE_GEN)
	assert json.loads(raw_vault.get_balance_of(addr_str(direct_alice)))["balance"] == "0"


def test_the_vault_asks_about_itself_and_nobody_else(raw_vault, monkeypatch):
	asked = []

	class _Recording(_StubOracle):
		def is_halted(self, target):
			asked.append(target)
			return False

	monkeypatch.setattr(_find_contract_class("TreasuryVault"), "_oracle", lambda self: _Recording(False))
	raw_vault.is_halted()
	assert len(asked) == 1
	assert asked[0].lower() == addr_str(raw_vault.address).lower()


def test_a_stranger_cannot_repoint_the_vault_at_a_friendly_oracle(raw_vault, direct_vm, direct_alice):
	direct_vm.sender = direct_alice
	with pytest.raises(Exception):
		raw_vault.set_sentinel("0x" + "12" * 20)
