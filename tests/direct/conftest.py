"""
Shared fixtures for the Direct Mode test suite.

genlayer-test 0.30.0rc2's Direct Mode does not yet implement a handler for
the ``GetTimestamp`` WASI host call that ``gl.vm.get_timestamp()`` relies on
for deterministic transaction time (verified directly: the call falls
through Direct Mode's "unknown request" path and returns ``None``, so
``gl.vm.get_timestamp().timestamp()`` raises ``AttributeError``). Both
contracts in this project catch exactly that and treat it as "clock
unavailable", which is the correct, safe thing for them to do -- but it
means every time-dependent code path is untestable here without standing
in for the missing host call ourselves.

``deploy`` below is a drop-in replacement for genlayer-test's own
``direct_deploy`` fixture that, immediately after the first successful
deployment in a test (which is what actually puts the SDK's cached package
on ``sys.path`` -- merely depending on ``direct_vm`` does not), patches
``genlayer.vm.get_timestamp`` directly. It patches the SDK's own host-call
entry point, not anything in either contract, so it can only ever fill in
a call the test harness has not wired up yet -- it can never mask a real
bug in contract code.

Related, separate gotcha (each test file defines its own small `addr_str`
helper for this rather than sharing one from here, since plain -- non
fixture -- helpers in conftest.py are not reliably importable from sibling
test files without extra package setup): the named account fixtures
(direct_alice, direct_bob, direct_owner, ...) come back as a real
``genlayer.types.Address`` if the SDK is already on ``sys.path`` by the
time that particular fixture is instantiated, or as raw ``bytes``
otherwise -- which of the two happens depends on where that account
appears in a test's parameter list relative to something that deploys a
contract, not on which named account it is. Comparing a raw-bytes fixture
value directly against a contract-returned hex string, or passing it
directly as a contract call argument, silently does the wrong thing
(``str()`` on bytes gives a Python repr, not a hex address). `addr_str`
normalises either case.
"""
import datetime
import os

import pytest

# Pin the GenVM runtime the Direct Mode tests run on.
#
# Each contract pins one exact GenVM Python runner in its
# `# { "Depends": "py-genlayer:<hash>" }` header, and that hash exists only in
# the GenVM releases that ship it (the rc3 runner has a different hash from
# the rc9/rc10 one). When `GENVM_VERSION` is unset, gltest asks the GitHub
# API for the latest release and, if that call fails -- it is rate-limited
# without a token, and fails outright offline -- silently falls back to a
# hard-coded OLDER release (v0.6.0-rc3). On a cold cache that means the tests
# run on a runtime that does not contain the runner the contracts pin, and
# nearly every test errors at setup. Pinning removes the dependence on that
# moving target. `setdefault` leaves an explicit GENVM_VERSION in the
# environment (for trying a newer runtime) in charge.
#
# Keep this in step with the hash in contracts/*.py:
# `python3 scripts/set_runner_hash.py --show`.
GENVM_RUNTIME_VERSION = "v0.6.0-rc9"
os.environ.setdefault("GENVM_VERSION", GENVM_RUNTIME_VERSION)


class FakeClock:
	def __init__(self, start: int):
		self._now = start

	def get_timestamp(self) -> datetime.datetime:
		return datetime.datetime.fromtimestamp(self._now, datetime.timezone.utc)

	def advance(self, seconds: int) -> None:
		self._now += seconds

	def set(self, epoch: int) -> None:
		self._now = epoch


@pytest.fixture
def fake_clock() -> FakeClock:
	return FakeClock(start=1_700_000_000)


@pytest.fixture
def deploy(direct_deploy, fake_clock, monkeypatch):
	"""Use this in place of direct_deploy in every test in this directory.
	Identical signature; the only difference is that gl.vm.get_timestamp()
	actually works afterward. See the module docstring for why."""
	state = {'patched': False}

	def _deploy(*args, **kwargs):
		contract = direct_deploy(*args, **kwargs)
		if not state['patched']:
			import genlayer.vm as gvm
			monkeypatch.setattr(gvm, 'get_timestamp', fake_clock.get_timestamp)
			state['patched'] = True
		return contract

	return _deploy
