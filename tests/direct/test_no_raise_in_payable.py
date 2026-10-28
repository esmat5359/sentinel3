"""
Structural guard for the money-safety rule both contracts rely on.

A GenVM ``gl.vm.UserError`` rolls back contract *storage* but does not return
the GEN that rode in with the call -- it would sit in the contract with no
record of whose it is. So every ``@gl.public.write.payable`` method must
refund-and-return instead of raising, on every path.

This is a static check over the contract source (it needs neither a network
nor the GenVM runtime), so it also catches a ``raise`` added to a payable
path years from now by someone who has never read the contract docstrings.
It deliberately walks nested functions and helper-free bodies alike: any
``raise`` statement textually inside a payable method fails the test.

Note what it does NOT cover: a payable method that *calls* a helper which
raises. The contracts keep every payable path's helpers (``_reject``,
``_pay``, ``_resolve_action``) raise-free by construction, and the Direct
Mode tests exercise those paths with real values -- this test is the cheap
tripwire for the direct case, not a proof of the transitive one.
"""
import ast
import pathlib

import pytest

CONTRACTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "contracts"
CONTRACT_FILES = sorted(CONTRACTS_DIR.glob("*.py"))


def _is_payable(node: ast.FunctionDef) -> bool:
	return any("payable" in ast.unparse(dec) for dec in node.decorator_list)


@pytest.mark.parametrize("path", CONTRACT_FILES, ids=lambda p: p.name)
def test_no_raise_inside_any_payable_method(path):
	tree = ast.parse(path.read_text())
	offenders = []
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and _is_payable(node):
			for inner in ast.walk(node):
				if isinstance(inner, ast.Raise):
					offenders.append(f"{node.name} (line {inner.lineno})")
	assert not offenders, f"{path.name}: raise inside payable method(s): {offenders}"


def test_payable_methods_are_the_ones_we_expect():
	"""If a new payable method appears, this fails -- forcing a deliberate
	look at whether it needs the refund-and-return treatment."""
	found = {}
	for path in CONTRACT_FILES:
		tree = ast.parse(path.read_text())
		found[path.name] = sorted(
			n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and _is_payable(n))
	assert found == {
		"SentinelHalt.py": ["clear_halt", "report_exploit"],
		"TreasuryVault.py": ["deposit"],
	}


def _self_calls(fn: ast.FunctionDef) -> set:
	"""Names of `self.<name>(...)` calls anywhere inside `fn` (nested defs included)."""
	names = set()
	for node in ast.walk(fn):
		if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
				and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
			names.add(node.func.attr)
	return names


@pytest.mark.parametrize("path", CONTRACT_FILES, ids=lambda p: p.name)
def test_no_raise_in_any_helper_reachable_from_a_payable_method(path):
	"""The tripwire above only sees a `raise` written directly inside a payable
	method. This one follows `self.<helper>()` calls transitively through the
	contract class, so a `raise` hidden in `_reject`, `_credit`, `_action_problem`
	and friends is caught too. (Module-level functions are out of scope: the one
	that raises, `_judge`, is called inside a try/except in the payable path.)"""
	tree = ast.parse(path.read_text())
	methods = {}
	for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
		for fn in cls.body:
			if isinstance(fn, ast.FunctionDef):
				methods[fn.name] = fn

	pending = [name for name, fn in methods.items() if _is_payable(fn)]
	reachable = set()
	while pending:
		name = pending.pop()
		if name in reachable or name not in methods:
			continue
		reachable.add(name)
		pending.extend(_self_calls(methods[name]))

	offenders = []
	for name in sorted(reachable):
		for inner in ast.walk(methods[name]):
			if isinstance(inner, ast.Raise):
				offenders.append(f"{name} (line {inner.lineno})")
	assert not offenders, f"{path.name}: raise in a helper reachable from a payable method: {offenders}"
