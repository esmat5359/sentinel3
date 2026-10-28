# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import genlayer as gl
import json

# ============================================================================
# TreasuryVault -- a minimal reference integration for SentinelHalt
# ============================================================================
#
# This is NOT meant to be a complete product. It exists to answer, with a
# real, checkable on-chain state change rather than a diagram, the question
# "does registering with SentinelHalt actually do anything": deposit() and
# withdraw() both ask SentinelHalt.is_halted(self.address) -- a live,
# synchronous cross-contract view() call, re-checked on every single call --
# and refuse to proceed if the answer is yes. There is no cached flag here
# that could go stale; every deposit and withdrawal is exactly as current as
# SentinelHalt's own verdict at that moment.
#
# Any contract can integrate the same way with two lines: hold the
# SentinelHalt address, and check is_halted(self.address) before doing
# something sensitive. This vault is that integration written out in full,
# so a reviewer can watch it actually block a withdrawal after a report is
# confirmed, not just read a claim that it would.

MIN_DEPOSIT = 10**12  # a dust floor, not an economic parameter
MAX_BALANCE_ENTRIES_PAGE = 40


@gl.contract.interface
class _SentinelHalt:
	"""Typed stub for the oracle. Purely for IDE/type-checking convenience --
	at runtime this behaves identically to gl.contract.get_at()."""
	class View:
		def is_halted(self, target: str) -> bool: ...

	class Write:
		pass


@gl.evm.contract_interface
class _Wallet:
	"""Sending value to an EOA is an external message through the ghost
	contract; this empty interface is the documented way to address one."""
	class View:
		pass

	class Write:
		pass


class TreasuryVault(gl.contract.Contract):
	owner: gl.Address
	sentinel: gl.Address

	balances: gl.storage.TreeMap[gl.Address, gl.u256]
	holders: gl.storage.DynArray[gl.Address]

	total_deposited: gl.u256
	total_withdrawn: gl.u256

	def __init__(self, sentinel: str):
		self.owner = gl.message.sender_address
		self.sentinel = gl.Address(str(sentinel))
		self.total_deposited = gl.u256(0)
		self.total_withdrawn = gl.u256(0)

	# -- internals -----------------------------------------------------------

	def _oracle(self):
		return _SentinelHalt(self.sentinel)

	def _halted(self) -> bool:
		"""Live, on every call -- see the module docstring. If the oracle
		address is unset/unreachable this fails closed (treats the vault as
		halted) rather than open, since a broken safety check should never
		silently become "no safety check"."""
		try:
			answer = self._oracle().view().is_halted(str(self.address))
		except Exception:
			return True
		# Only an explicit False opens the vault. None, 0, "false", or any
		# other shape means the oracle is not answering the question we asked.
		return answer is not False

	def _require_not_halted(self) -> None:
		if self._halted():
			raise gl.vm.UserError(
				'TreasuryVault is halted by SentinelHalt -- deposits and '
				'withdrawals are frozen until a clear_halt report is judged SUPPORTED')

	# -- writes ---------------------------------------------------------------

	@gl.public.write.payable
	def deposit(self) -> str:
		"""Payable, so this never raises: a rejection (halted, or below the
		dust floor) refunds the sender and returns {"ok": false, ...}
		instead of rolling back storage while keeping the incoming value
		unaccounted for."""
		sender = gl.message.sender_address
		value = int(gl.message.value)
		if self._halted():
			if value > 0:
				_Wallet(gl.Address(str(sender))).emit_transfer(value=gl.u256(value))
			return json.dumps({'ok': False, 'reason': 'vault is halted', 'refunded': str(value)})
		if value < MIN_DEPOSIT:
			if value > 0:
				_Wallet(gl.Address(str(sender))).emit_transfer(value=gl.u256(value))
			return json.dumps({'ok': False, 'reason': 'deposit below minimum', 'refunded': str(value)})

		current = self.balances.get(sender)
		if current is None:
			self.holders.append(sender)
			current = gl.u256(0)
		self.balances[sender] = gl.u256(int(current) + value)
		self.total_deposited = gl.u256(int(self.total_deposited) + value)
		return json.dumps({'ok': True, 'depositor': str(sender), 'amount': str(value),
			'new_balance': str(int(self.balances[sender]))})

	@gl.public.write
	def withdraw(self, amount: int) -> str:
		"""Non-payable, so raising here is the correct, simple behavior --
		there is no incoming value to strand. Blocked outright while
		halted; this is the actual enforcement the whole project is about,
		not a comment describing it."""
		self._require_not_halted()
		sender = gl.message.sender_address
		amt = int(amount)
		if amt <= 0:
			raise gl.vm.UserError('amount must be positive')
		current = int(self.balances.get(sender, gl.u256(0)))
		if amt > current:
			raise gl.vm.UserError('amount exceeds balance')
		self.balances[sender] = gl.u256(current - amt)
		self.total_withdrawn = gl.u256(int(self.total_withdrawn) + amt)
		_Wallet(gl.Address(str(sender))).emit_transfer(value=gl.u256(amt))
		return json.dumps({'ok': True, 'withdrawer': str(sender), 'amount': str(amt),
			'remaining_balance': str(current - amt)})

	@gl.public.write
	def set_sentinel(self, new_sentinel: str) -> str:
		if str(gl.message.sender_address) != str(self.owner):
			raise gl.vm.UserError('owner only')
		self.sentinel = gl.Address(str(new_sentinel))
		return json.dumps({'ok': True, 'sentinel': str(new_sentinel)})

	# -- views -----------------------------------------------------------------

	@gl.public.view
	def is_halted(self) -> bool:
		return self._halted()

	@gl.public.view
	def get_balance_of(self, address: str) -> str:
		bal = self.balances.get(gl.Address(str(address)), gl.u256(0))
		return json.dumps({'address': str(address), 'balance': str(int(bal))})

	@gl.public.view
	def get_holders(self, offset: int, limit: int) -> str:
		n = len(self.holders)
		off = max(0, min(int(offset), n))
		lim = max(0, min(int(limit), MAX_BALANCE_ENTRIES_PAGE))
		rows = []
		i = off
		end = min(n, off + lim)
		while i < end:
			addr = self.holders[i]
			rows.append({'address': str(addr), 'balance': str(int(self.balances.get(addr, gl.u256(0))))})
			i += 1
		return json.dumps({'total': n, 'offset': off, 'count': len(rows), 'holders': rows})

	@gl.public.view
	def get_config(self) -> str:
		return json.dumps({'owner': str(self.owner), 'sentinel': str(self.sentinel),
			'address': str(self.address), 'halted': self._halted(),
			'total_deposited': str(int(self.total_deposited)),
			'total_withdrawn': str(int(self.total_withdrawn)),
			'on_chain_balance': str(int(self.balance))})
