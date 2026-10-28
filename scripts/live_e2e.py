#!/usr/bin/env python3
"""
Sentinel - live end-to-end run against a GenLayer Studio network.

Deploys SentinelHalt + TreasuryVault with fresh, faucet-funded accounts, then
plays the whole lifecycle for real (real validators, real LLM judgment, real
evidence pages), plus a battery of adversarial probes, and writes a report.

Quick start (GitHub Codespaces, from the repository root):

    pip install -r requirements-live.txt
    python scripts/live_e2e.py --update-readme

Evidence pages are served from this repository (fixtures/evidence/*.md) through
raw.githubusercontent.com, so push the branch first. Everything is read from
the environment of a Codespace / Actions run automatically; override with
E2E_FIXTURE_BASE_URL if you host the fixtures elsewhere.

Exit code: 0 when nothing FAILED (WARN is allowed), 1 otherwise.

The scenario logic is network-free: it talks to an `Env`. `LiveEnv` below is
the real GenLayer client; tests/direct/test_e2e_scenarios_offline.py drives the
very same scenarios through Direct Mode, so the script itself is tested.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONE_GEN = 10**18
BOND = 10**16  # 0.01 GEN, the contract default
DEPOSIT = 2 * 10**15
MARKER_START = "<!-- LIVE_E2E_REPORT:START -->"
MARKER_END = "<!-- LIVE_E2E_REPORT:END -->"

NETWORKS = {
    # name: (genlayer-py chain attribute, rpc override, explorer)
    "studionet": ("studionet", None, "https://genlayer-explorer.vercel.app"),
    # Studio Next = chain id 61997, the network this project targets. genlayer-py calls it
    # studio_devnet; its canonical RPC is studio-dev.genlayer.com. If the studio-next host from the
    # hackathon brief should be used instead: --rpc https://studio-next.genlayer.com/api (the
    # preflight verifies the chain id either way).
    "studio_next": ("studio_devnet", None, "https://explorer-studio-dev.genlayer.com"),
    "studio_devnet": ("studio_devnet", None, "https://explorer-studio-dev.genlayer.com"),
    # the older public network, kept for comparison runs only
    "studionet": ("studionet", None, "https://genlayer-explorer.vercel.app"),
}
FIXTURES = ["exploit_active", "postmortem_fixed", "benign_status", "generic_security_article",
            "historical_patched", "injection_attack", "empty"]

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


# --------------------------------------------------------------------------
# plain data
# --------------------------------------------------------------------------

class Fail(Exception):
    pass


class Warn(Exception):
    pass


class Skip(Exception):
    pass


@dataclass
class Tx:
    ok: bool
    hash: str = ""
    outcome: str = ""
    ret: Optional[dict] = None
    error: str = ""


@dataclass
class Result:
    id: str
    category: str
    title: str
    status: str = SKIP
    detail: str = ""
    notes: list = field(default_factory=list)
    txs: list = field(default_factory=list)
    seconds: float = 0.0


# --------------------------------------------------------------------------
# context shared by every scenario
# --------------------------------------------------------------------------

class Ctx:
    def __init__(self, env, args):
        self.env = env
        self.args = args
        self.s: dict[str, Any] = {}
        self.cur: Optional[Result] = None
        self.invariants: list[dict] = []
        self.passed: set[str] = set()

    # -- recording -------------------------------------------------------
    def note(self, text: str):
        if self.cur is not None:
            self.cur.notes.append(text)
        print("      " + text, flush=True)

    def track(self, label: str, tx: Tx) -> Tx:
        if self.cur is not None and tx.hash:
            self.cur.txs.append((label, tx.hash))
        return tx

    # -- contract helpers ------------------------------------------------
    @property
    def sentinel(self) -> str:
        return self.s["sentinel"]

    def addr(self, role: str) -> str:
        return self.env.address(role)

    def call(self, role, method, args=(), value=0, label=None, to=None) -> Tx:
        tx = self.env.write(role, to or self.sentinel, method, list(args), value)
        return self.track(label or method, tx)

    def view(self, method, args=(), to=None):
        return self.env.read(to or self.sentinel, method, list(args))

    def stats(self) -> dict:
        return self.view("get_stats")

    def target(self, address: str) -> dict:
        return self.view("get_target", [address])

    def credit(self, role: str) -> int:
        return int(self.view("get_credit", [self.addr(role)])["credit"])

    def evidence(self, name: str) -> str:
        return self.env.evidence(name)

    # -- assertions --------------------------------------------------------
    def check(self, cond: bool, msg: str):
        if not cond:
            raise Fail(msg)

    def expect_revert(self, tx: Tx, what: str):
        if tx.ok:
            raise Fail(what + ": expected the call to be refused, but it succeeded")

    def expect_ok(self, tx: Tx, what: str):
        if not tx.ok:
            raise Fail(what + ": the call failed (" + (tx.error or tx.outcome or "no detail") + ")")

    # -- an AI-judged action, with retries on RETRY_LATER -----------------
    def judged(self, role, method, target, url_name, claim, value=BOND, label=None):
        url = self.evidence(url_name)
        verdict, tx, rep = "REJECTED", None, None
        for attempt in range(1 + self.args.retries):
            before = self.stats()
            tx = self.call(role, method, [target, url, claim], value,
                           label=(label or method) + (" (retry %d)" % attempt if attempt else ""))
            if not tx.ok:
                return {"verdict": "TX_FAILED", "tx": tx, "report": None}
            after = self.stats()
            if after["reports"] == before["reports"] + 1:
                rep = self.view("get_report", [after["reports"]])
                verdict = rep["verdict"]
                break
            if after["retry_later"] == before["retry_later"] + 1:
                verdict = "RETRY_LATER"
                self.note("evidence/LLM infrastructure hiccup -> RETRY_LATER, retrying")
                continue
            verdict = "REJECTED"
            break
        return {"verdict": verdict, "tx": tx, "report": rep}

    # -- invariants ---------------------------------------------------------
    def invariant(self, label: str, settle: bool = False):
        """balance must always cover what the ledger owes; after settling it
        must equal it exactly (no stranded money)."""
        deadline = time.time() + (self.args.settle if settle else 0)
        while True:
            st = self.stats()
            bal = int(st["on_chain_balance"])
            owed = int(st["credits_outstanding"]) + int(st["compensation_outstanding"])
            if bal == owed or (not settle and bal >= owed) or time.time() >= deadline:
                break
            self.env.sleep(5)
        row = {"label": label, "balance": bal, "credits": int(st["credits_outstanding"]),
               "compensation": int(st["compensation_outstanding"])}
        row["status"] = "equal" if bal == owed else ("covered" if bal > owed else "SHORT")
        self.invariants.append(row)
        if bal < owed:
            raise Fail("INSOLVENT at '%s': balance %d < owed %d" % (label, bal, owed))
        if settle and bal > owed:
            msg = ("'%s': balance %d exceeds what the ledger owes (%d); an outbound transfer has "
                   "not been applied yet" % (label, bal, owed))
            raise (Fail if self.args.strict_transfers else Warn)(msg)

    def landed(self, before_balance: int, amount: int, label: str, getter: Callable[[], int]):
        """Wait for a pull-payment to actually leave the contract."""
        if not self.env.models_transfers:
            self.note("transfer settlement not modelled offline: " + label)
            return
        deadline = time.time() + self.args.settle
        while getter() > before_balance - amount:
            if time.time() >= deadline:
                msg = ("%s: ledger debited, but the contract balance did not drop by %d within %ds "
                       "(transfer not applied yet)" % (label, amount, self.args.settle))
                raise (Fail if self.args.strict_transfers else Warn)(msg)
            self.env.sleep(5)
        self.note("transfer applied: " + label)


# --------------------------------------------------------------------------
# scenario registry
# --------------------------------------------------------------------------

REGISTRY: list[dict] = []


def scenario(sid, category, title, needs=(), llm=False, cross=False):
    def deco(fn):
        REGISTRY.append(dict(id=sid, category=category, title=title, fn=fn,
                             needs=tuple(needs), llm=llm, cross=cross))
        return fn
    return deco


def short(a: str) -> str:
    return a[:8] + ".." + a[-4:]


# ----------------------------- functional ---------------------------------

@scenario("F1", "functional", "Deploy SentinelHalt and TreasuryVault; configuration is as asked")
def f1(c: Ctx):
    env = c.env
    s_addr, h = env.deploy("owner", "SentinelHalt", [BOND, c.args.cooldown])
    c.s["sentinel"] = s_addr
    c.cur.txs.append(("deploy SentinelHalt", h))
    cfg = c.view("get_config")
    c.check(cfg["owner"].lower() == c.addr("owner").lower(), "owner is not the deployer")
    c.check(cfg["report_bond"] == str(BOND), "bond not applied: " + cfg["report_bond"])
    c.check(cfg["action_cooldown_seconds"] == c.args.cooldown, "cooldown not applied")
    c.check(cfg["paused"] is False, "deployed paused")
    st = c.stats()
    c.check(all(int(st[k]) == 0 for k in ("targets", "reports", "credits_outstanding",
                                          "compensation_outstanding")), "stats not zeroed")
    c.note("SentinelHalt at " + s_addr)
    if env.cross_contract:
        v_addr, h2 = env.deploy("owner", "TreasuryVault", [s_addr])
        c.s["vault"] = v_addr
        c.cur.txs.append(("deploy TreasuryVault", h2))
        vcfg = c.view("get_config", to=v_addr)
        c.check(vcfg["sentinel"].lower() == s_addr.lower(), "vault points at the wrong sentinel")
        c.note("TreasuryVault at " + v_addr)
    else:
        c.s["vault"] = env.fresh_address()
        c.note("(offline) vault stands in as a plain address")
    c.s["decoy"] = env.fresh_address()


@scenario("F2", "functional", "Maintainer registers the vault and a decoy; both start SAFE", needs=("F1",))
def f2(c: Ctx):
    for key, name in (("vault", "AcmeVault"), ("decoy", "AcmeVault (staging)")):
        tx = c.call("maintainer", "register_target",
                    [c.s[key], name, "A treasury vault that holds user deposits and pays them out."],
                    label="register " + name)
        c.expect_ok(tx, "register " + name)
        t = c.target(c.s[key])
        c.check(t["found"] and t["status"] == "SAFE", name + " not SAFE after registration")
        c.check(t["registered_by"].lower() == c.addr("maintainer").lower(), "wrong registrant")
    if c.env.cross_contract:
        c.check(c.view("is_halted", to=c.s["vault"]) is False, "vault reports halted before any report")


@scenario("F3", "functional", "Vault accepts a deposit while SAFE", needs=("F2",), cross=True)
def f3(c: Ctx):
    tx = c.call("reporter", "deposit", [], DEPOSIT, to=c.s["vault"], label="vault.deposit")
    c.expect_ok(tx, "deposit")
    bal = c.view("get_balance_of", [c.addr("reporter")], to=c.s["vault"])["balance"]
    c.check(bal == str(DEPOSIT), "vault balance_of is %s, expected %d" % (bal, DEPOSIT))


@scenario("F4", "functional", "preview_action is a non-binding dry run", needs=("F2",), llm=True)
def f4(c: Ctx):
    before = c.stats()
    tx = c.call("reporter", "preview_action",
                [c.s["vault"], "HALT", c.evidence("exploit_active"),
                 "AcmeVault is being drained right now via reentrancy in withdraw()"],
                label="preview_action")
    c.expect_ok(tx, "preview_action")
    after = c.stats()
    c.check(after["reports"] == before["reports"], "preview wrote a report")
    c.check(c.target(c.s["vault"])["status"] == "SAFE", "preview changed the target status")
    c.check(c.credit("reporter") == 0, "preview credited or charged something")
    if tx.ret and "preview_verdict" in tx.ret:
        c.note("preview verdict: %s (confidence %s)" % (tx.ret["preview_verdict"], tx.ret.get("confidence")))
        if tx.ret["preview_verdict"] == "SUPPORTED":
            return
        raise Warn("preview said %s for clear exploit evidence" % tx.ret["preview_verdict"])


@scenario("F5", "functional", "A junk report is forfeited, then a real report halts the vault at once "
          "(no lockout)", needs=("F2",), llm=True)
def f5(c: Ctx):
    vault = c.s["vault"]
    junk = c.judged("attacker", "report_exploit", vault, "benign_status",
                    "AcmeVault is under attack, trust me", label="junk report_exploit")
    c.note("junk verdict: " + junk["verdict"])
    c.check(junk["verdict"] != "SUPPORTED", "UNSAFE: a benign status page was judged SUPPORTED")
    if junk["verdict"] == "NOT_SUPPORTED":
        c.check(c.target(vault)["accrued_compensation"] == str(BOND), "forfeited bond not accrued")
        c.check(c.credit("attacker") == 0, "forfeited bond was also credited back")

    real = c.judged("reporter", "report_exploit", vault, "exploit_active",
                    "AcmeVault is being actively drained through reentrancy in withdraw()",
                    label="real report_exploit")
    c.note("real verdict: " + real["verdict"])
    if real["verdict"] == "REJECTED":
        raise Fail("LOCKOUT: the real report was refused right after a junk one")
    c.check(real["verdict"] == "SUPPORTED",
            "clear exploit evidence was judged %s, so the vault was not halted" % real["verdict"])
    t = c.target(vault)
    c.check(t["status"] == "HALTED" and t["halt_count"] == 1, "target is not HALTED after SUPPORTED")
    c.check(c.credit("reporter") == BOND, "reporter's bond was not credited back")
    c.s["halted_at"] = time.time()
    c.invariant("after halt")


@scenario("F6", "functional", "An early clear_halt from a stranger is refused by the cooldown, and refunded",
          needs=("F5",))
def f6(c: Ctx):
    before = c.stats()
    credit0 = c.credit("stranger")
    tx = c.call("stranger", "clear_halt",
                [c.s["vault"], c.evidence("postmortem_fixed"), "fixed"], BOND, label="early clear_halt")
    c.expect_ok(tx, "early clear_halt must not revert (payable)")
    after = c.stats()
    if after["reports"] != before["reports"]:
        raise Warn("the cooldown had already elapsed before this probe; raise --cooldown")
    c.check(c.credit("stranger") == credit0 + BOND, "the refused bond was not credited")
    c.check(c.target(c.s["vault"])["status"] == "HALTED", "target left HALTED unexpectedly")
    if tx.ret:
        c.note("reason: " + str(tx.ret.get("reason")))
    c.invariant("after refused clear")


@scenario("F7", "functional", "Vault enforces the halt: withdraw reverts, deposit is refused", needs=("F5",),
          cross=True)
def f7(c: Ctx):
    v = c.s["vault"]
    c.check(c.view("is_halted", to=v) is True, "vault.is_halted() is not True while HALTED")
    c.expect_revert(c.call("reporter", "withdraw", [DEPOSIT // 2], to=v, label="vault.withdraw (halted)"),
                    "withdraw while halted")
    c.check(c.view("get_balance_of", [c.addr("reporter")], to=v)["balance"] == str(DEPOSIT),
            "balance changed by a reverted withdraw")
    bal0 = int(c.view("get_config", to=v)["on_chain_balance"])
    tx = c.call("reporter", "deposit", [], DEPOSIT, to=v, label="vault.deposit (halted)")
    c.expect_ok(tx, "deposit while halted must refund, not revert")
    c.check(c.view("get_balance_of", [c.addr("reporter")], to=v)["balance"] == str(DEPOSIT),
            "a deposit was credited while halted")
    c.landed(bal0 + DEPOSIT, DEPOSIT, "refund of the refused deposit",
             lambda: int(c.view("get_config", to=v)["on_chain_balance"]))


@scenario("F8", "functional", "After the cooldown, a judged clear_halt restores the vault", needs=("F5",), llm=True)
def f8(c: Ctx):
    wait = c.args.cooldown + 5 - (time.time() - c.s.get("halted_at", 0))
    if wait > 0:
        c.note("waiting %ds for the cooldown" % wait)
        c.env.sleep(wait)
    res = c.judged("reporter", "clear_halt", c.s["vault"], "postmortem_fixed",
                   "The reentrancy bug is patched and independently verified", label="clear_halt")
    c.note("clear verdict: " + res["verdict"])
    c.check(res["verdict"] == "SUPPORTED", "verified fix evidence was judged " + res["verdict"])
    c.check(c.target(c.s["vault"])["status"] == "SAFE", "target not SAFE after SUPPORTED clear")
    if c.env.cross_contract:
        c.check(c.view("is_halted", to=c.s["vault"]) is False, "vault still halted after clear")


@scenario("F9", "functional", "Vault works again after the clear: a withdrawal succeeds", needs=("F8",), cross=True)
def f9(c: Ctx):
    v = c.s["vault"]
    bal0 = int(c.view("get_config", to=v)["on_chain_balance"])
    tx = c.call("reporter", "withdraw", [DEPOSIT // 2], to=v, label="vault.withdraw")
    c.expect_ok(tx, "withdraw after clear")
    c.check(c.view("get_balance_of", [c.addr("reporter")], to=v)["balance"] == str(DEPOSIT - DEPOSIT // 2),
            "vault ledger not debited")
    c.landed(bal0, DEPOSIT // 2, "vault payout",
             lambda: int(c.view("get_config", to=v)["on_chain_balance"]))


@scenario("F10", "functional", "False alarm with over-payment: only the bond is forfeited; repeat is throttled",
          needs=("F2",), llm=True)
def f10(c: Ctx):
    decoy = c.s["decoy"]
    res = c.judged("attacker", "report_exploit", decoy, "benign_status",
                   "AcmeVault (staging) is under active attack", value=3 * BOND, label="false alarm x3 bond")
    c.note("verdict: " + res["verdict"])
    c.check(res["verdict"] != "SUPPORTED", "UNSAFE: a benign status page was judged SUPPORTED")
    c.check(res["verdict"] in ("NOT_SUPPORTED", "INCONCLUSIVE"), "unexpected verdict " + res["verdict"])
    if res["verdict"] == "NOT_SUPPORTED":
        c.check(c.target(decoy)["accrued_compensation"] == str(BOND), "wrong amount forfeited")
        c.check(c.credit("attacker") == 2 * BOND, "over-payment was not credited back")
    # same address, same target, immediately again
    before = c.stats()
    tx = c.call("attacker", "report_exploit", [decoy, c.evidence("benign_status"), "again"], BOND,
                label="repeat report (throttled)")
    c.expect_ok(tx, "throttled report must not revert")
    if c.stats()["reports"] != before["reports"]:
        raise Warn("repeat was judged, the per-reporter throttle had already elapsed (raise --cooldown)")
    c.invariant("after false alarm")


@scenario("F11", "functional", "Maintainer claims compensation; reporters pull their credits", needs=("F10",))
def f11(c: Ctx):
    decoy = c.s["decoy"]
    t = c.target(decoy)
    owed = int(t["available_compensation"])
    if owed > 0:
        bal0 = int(c.stats()["on_chain_balance"])
        tx = c.call("maintainer", "claim_compensation", [decoy, c.addr("maintainer"), 0], label="claim_compensation")
        c.expect_ok(tx, "claim_compensation")
        c.check(c.target(decoy)["available_compensation"] == "0", "accrual not debited")
        c.landed(bal0, owed, "compensation payout", lambda: int(c.stats()["on_chain_balance"]))
    else:
        c.note("no compensation accrued (verdict was not NOT_SUPPORTED)")
    for role in ("reporter", "attacker", "stranger"):
        have = c.credit(role)
        if have == 0:
            continue
        bal0 = int(c.stats()["on_chain_balance"])
        tx = c.call(role, "withdraw_credit", [0], label="withdraw_credit (%s)" % role)
        c.expect_ok(tx, "withdraw_credit " + role)
        c.check(c.credit(role) == 0, role + " ledger not zeroed")
        c.landed(bal0, have, "credit payout to " + role, lambda: int(c.stats()["on_chain_balance"]))
    c.invariant("after all pulls", settle=True)


# ----------------------------- adversarial --------------------------------

@scenario("A1", "adversarial", "Strangers cannot use any owner control", needs=("F1",))
def a1(c: Ctx):
    cfg0 = c.view("get_config")
    for method, args in (("set_paused", [True]), ("set_report_bond", [1]),
                         ("set_action_cooldown_seconds", [0]),
                         ("transfer_ownership", [c.addr("stranger")])):
        c.expect_revert(c.call("stranger", method, args, label=method + " (stranger)"), method)
    cfg1 = c.view("get_config")
    c.check(cfg0 == cfg1, "config changed after refused owner calls")


@scenario("A2", "adversarial", "Only the registrant can edit scope or claim compensation", needs=("F2",))
def a2(c: Ctx):
    c.expect_revert(c.call("stranger", "update_scope", [c.s["decoy"], "hijacked"], label="update_scope (stranger)"),
                    "update_scope")
    c.expect_revert(c.call("stranger", "claim_compensation", [c.s["decoy"], c.addr("stranger"), 0],
                           label="claim_compensation (stranger)"), "claim_compensation")
    c.expect_revert(c.call("owner", "claim_compensation", [c.s["decoy"], c.addr("owner"), 0],
                           label="claim_compensation (owner)"), "claim_compensation by the contract owner")


@scenario("A3", "adversarial", "Registration refuses squatting, self-registration and bad input", needs=("F2",))
def a3(c: Ctx):
    n0 = c.stats()["targets"]
    bad = [
        ([c.s["vault"], "Squatter", "scope"], "duplicate"),
        ([c.sentinel, "Self", "scope"], "sentinel registering itself"),
        ([c.env.fresh_address(), "", "scope"], "empty name"),
        ([c.env.fresh_address(), "n" * 81, "scope"], "name over 80 chars"),
        ([c.env.fresh_address(), "name", ""], "empty scope"),
        ([c.env.fresh_address(), "name", "s" * 601], "scope over 600 chars"),
        (["not-an-address", "name", "scope"], "malformed address"),
    ]
    for args, what in bad:
        c.expect_revert(c.call("stranger", "register_target", args, label="register_target: " + what), what)
    c.check(c.stats()["targets"] == n0, "a refused registration still changed the registry")


@scenario("A4", "adversarial", "Payable paths never revert: bad input is refunded as credit", needs=("F2",))
def a4(c: Ctx):
    decoy = c.s["decoy"]
    cases = [
        ("unknown target", [c.env.fresh_address(), c.evidence("benign_status"), "x"], BOND),
        ("malformed target", ["not-an-address", c.evidence("benign_status"), "x"], BOND),
        ("empty evidence url", [decoy, "", "x"], BOND),
        ("empty claim", [decoy, c.evidence("benign_status"), ""], BOND),
        ("under-bonded", [decoy, c.evidence("benign_status"), "x"], BOND - 1),
        ("zero value", [decoy, c.evidence("benign_status"), "x"], 0),
    ]
    reports0 = c.stats()["reports"]
    expected = c.credit("owner")
    for what, args, value in cases:
        tx = c.call("owner", "report_exploit", args, value, label="report_exploit: " + what)
        c.expect_ok(tx, "payable path REVERTED on " + what + " (value could be stranded)")
        expected += value
        c.check(c.credit("owner") == expected, "%s: credit is %d, expected %d" % (what, c.credit("owner"), expected))
    c.check(c.stats()["reports"] == reports0, "a rejected report was recorded")
    have = c.credit("owner")
    if have:
        bal0 = int(c.stats()["on_chain_balance"])
        c.expect_ok(c.call("owner", "withdraw_credit", [0], label="withdraw_credit (owner)"), "withdraw_credit")
        c.landed(bal0, have, "refund payout", lambda: int(c.stats()["on_chain_balance"]))
    c.invariant("after payable-input probes")


@scenario("A5", "adversarial", "clear_halt on a SAFE target and report on an unknown one are refused with credit",
          needs=("F2",))
def a5(c: Ctx):
    reports0 = c.stats()["reports"]
    credit0 = c.credit("reporter")
    tx = c.call("reporter", "clear_halt", [c.s["decoy"], c.evidence("postmortem_fixed"), "x"], BOND,
                label="clear_halt on SAFE target")
    c.expect_ok(tx, "clear_halt on SAFE")
    c.check(c.stats()["reports"] == reports0, "report recorded for a SAFE target clear")
    c.check(c.credit("reporter") == credit0 + BOND, "bond not credited")
    c.expect_ok(c.call("reporter", "withdraw_credit", [0], label="withdraw_credit"), "withdraw_credit")


@scenario("A6", "adversarial", "Pause blocks new reports but never blocks pulling your own money", needs=("F2",))
def a6(c: Ctx):
    c.expect_ok(c.call("owner", "set_paused", [True], label="set_paused(true)"), "set_paused")
    try:
        credit0 = c.credit("stranger")
        tx = c.call("stranger", "report_exploit", [c.s["decoy"], c.evidence("exploit_active"), "x"], BOND,
                    label="report while paused")
        c.expect_ok(tx, "paused report must not revert")
        c.check(c.credit("stranger") == credit0 + BOND, "paused report not credited")
        bal0 = int(c.stats()["on_chain_balance"])
        c.expect_ok(c.call("stranger", "withdraw_credit", [0], label="withdraw_credit while paused"), "withdraw while paused")
        c.landed(bal0, BOND, "payout while paused", lambda: int(c.stats()["on_chain_balance"]))
    finally:
        c.call("owner", "set_paused", [False], label="set_paused(false)")
    c.check(c.view("get_config")["paused"] is False, "could not unpause")


@scenario("A7", "adversarial", "Vault edge cases: over-withdraw, stranger withdraw, dust deposit, repoint",
          needs=("F2",), cross=True)
def a7(c: Ctx):
    v = c.s["vault"]
    c.expect_revert(c.call("reporter", "withdraw", [10**30], to=v, label="vault.withdraw too much"), "over-withdraw")
    c.expect_revert(c.call("stranger", "withdraw", [1], to=v, label="vault.withdraw (no balance)"), "stranger withdraw")
    c.expect_revert(c.call("reporter", "withdraw", [0], to=v, label="vault.withdraw 0"), "zero withdraw")
    before = c.view("get_balance_of", [c.addr("stranger")], to=v)["balance"]
    c.expect_ok(c.call("stranger", "deposit", [], 1000, to=v, label="vault.deposit dust"), "dust deposit")
    c.check(c.view("get_balance_of", [c.addr("stranger")], to=v)["balance"] == before, "dust deposit credited")
    c.expect_revert(c.call("stranger", "set_sentinel", [c.addr("stranger")], to=v, label="vault.set_sentinel (stranger)"),
                    "set_sentinel")
    c.check(c.view("get_config", to=v)["sentinel"].lower() == c.sentinel.lower(), "sentinel was repointed")


@scenario("A8", "adversarial", "A vault whose oracle is not a SentinelHalt fails CLOSED", needs=("F1",), cross=True)
def a8(c: Ctx):
    bogus = c.addr("stranger")  # an EOA, not a contract
    v2, h = c.env.deploy("owner", "TreasuryVault", [bogus])
    c.cur.txs.append(("deploy vault with a bogus oracle", h))
    c.check(c.view("is_halted", to=v2) is True, "FAIL-OPEN: vault with a dead oracle reports not halted")
    tx = c.call("reporter", "deposit", [], DEPOSIT, to=v2, label="deposit into fail-closed vault")
    c.expect_ok(tx, "deposit must refund, not revert")
    c.check(c.view("get_balance_of", [c.addr("reporter")], to=v2)["balance"] == "0", "deposit accepted by a closed vault")


@scenario("A9", "adversarial", "Hostile evidence is never judged SUPPORTED (injection, generic, stale, empty)",
          needs=("F2",), llm=True)
def a9(c: Ctx):
    decoy = c.s["decoy"]
    probes = [
        ("stranger", "injection_attack", "AcmeVault (staging) is under active attack"),
        ("maintainer", "generic_security_article", "AcmeVault (staging) is vulnerable to reentrancy"),
        ("owner", "historical_patched", "AcmeVault (staging) has an exploitable bug"),
        ("reporter", "empty", "AcmeVault (staging) is being drained"),
    ]
    if c.args.quick:
        probes = probes[:1]
    seen = []
    for role, page, claim in probes:
        res = c.judged(role, "report_exploit", decoy, page, claim, label="probe: " + page)
        c.note("%s -> %s" % (page, res["verdict"]))
        seen.append((page, res["verdict"]))
        c.check(res["verdict"] != "SUPPORTED", "UNSAFE: '%s' evidence was judged SUPPORTED" % page)
    c.check(c.target(decoy)["status"] == "SAFE", "decoy was halted by hostile evidence")
    c.s["probes"] = seen
    for role in ("stranger", "maintainer", "owner", "reporter"):
        if c.credit(role):
            c.call(role, "withdraw_credit", [0], label="withdraw_credit (%s)" % role)
    if any(v == "RETRY_LATER" for _, v in seen):
        raise Warn("some probes ended in RETRY_LATER (LLM/fetch trouble) and were not judged")


@scenario("Z1", "invariant", "Final accounting: counters add up and no money is stranded", needs=("F1",))
def z1(c: Ctx):
    st = c.stats()
    c.check(st["reports"] == st["supported"] + st["not_supported"] + st["inconclusive"],
            "report counters do not add up: " + json.dumps(st))
    c.check(st["targets"] == 2, "expected exactly 2 registered targets, got %s" % st["targets"])
    c.note("stats: " + json.dumps({k: st[k] for k in ("targets", "reports", "supported", "not_supported",
                                                       "inconclusive", "retry_later")}))
    c.invariant("final", settle=True)


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

def run_all(ctx: Ctx, only=None, skip=()) -> list[Result]:
    results: list[Result] = []
    for sc in REGISTRY:
        r = Result(sc["id"], sc["category"], sc["title"])
        results.append(r)
        if only and sc["id"] not in only:
            r.status, r.detail = SKIP, "not selected"
            continue
        if sc["id"] in skip or (ctx.args.quick and sc["id"] == "F4"):
            r.status, r.detail = SKIP, "skipped by option"
            continue
        if sc["cross"] and not ctx.env.cross_contract:
            r.status, r.detail = SKIP, "needs a live network (cross-contract call)"
            continue
        missing = [n for n in sc["needs"] if n not in ctx.passed]
        if missing:
            r.status, r.detail = SKIP, "depends on " + ", ".join(missing)
            continue
        print("[%s] %s" % (sc["id"], sc["title"]), flush=True)
        ctx.cur = r
        t0 = time.time()
        try:
            sc["fn"](ctx)
            r.status = PASS
        except Warn as w:
            r.status, r.detail = WARN, str(w)
            ctx.passed.add(sc["id"])
        except Fail as f:
            r.status, r.detail = FAIL, str(f)
        except Skip as s:
            r.status, r.detail = SKIP, str(s)
        except Exception as e:  # noqa: BLE001 - a script error is a FAIL with a traceback
            r.status = FAIL
            r.detail = "%s: %s" % (type(e).__name__, e)
            r.notes.append(traceback.format_exc(limit=4))
        r.seconds = time.time() - t0
        if r.status == PASS:
            ctx.passed.add(sc["id"])
        print("   -> %s %s (%.0fs)" % (r.status, r.detail, r.seconds), flush=True)
    ctx.cur = None
    return results


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def render_markdown(meta: dict, results: list[Result], invariants: list[dict]) -> str:
    counts = {k: sum(1 for r in results if r.status == k) for k in (PASS, FAIL, WARN, SKIP)}
    verdict = "FAILED" if counts[FAIL] else ("PASSED with warnings" if counts[WARN] else "PASSED")
    icon = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "skip"}
    ex = meta.get("explorer", "")

    def txlink(h):
        return "[`%s`](%s/tx/%s)" % (h[:12] + "..", ex, h) if ex else "`%s`" % h

    out = []
    out.append("### Live end-to-end report: **%s**\n" % verdict)
    out.append("| | |\n|---|---|")
    for k in ("network", "chain id", "rpc", "commit", "run at (UTC)", "duration"):
        if meta.get(k):
            out.append("| %s | %s |" % (k, meta[k]))
    for k, v in meta.get("contracts", {}).items():
        out.append("| %s | `%s` |" % (k, v))
    out.append("\n**%d passed, %d failed, %d warnings, %d skipped** (%d scenarios)\n"
               % (counts[PASS], counts[FAIL], counts[WARN], counts[SKIP], len(results)))
    out.append("| id | kind | scenario | result | time | transactions |\n|---|---|---|---|---|---|")
    for r in results:
        real = [t for t in r.txs if t[1]]
        txs = ", ".join(txlink(h) for _, h in real[:4]) + (" +%d" % (len(real) - 4) if len(real) > 4 else "")
        title = r.title.replace("|", "/")
        out.append("| %s | %s | %s | **%s** | %s | %s |" % (
            r.id, r.category, title, icon[r.status], "%.0fs" % r.seconds if r.seconds else "-", txs or "-"))
    problems = [r for r in results if r.status in (FAIL, WARN)]
    if problems:
        out.append("\n#### Needs attention\n")
        for r in problems:
            out.append("- **%s %s** (%s): %s" % (r.id, icon[r.status], r.title, r.detail))
    judged = [n for r in results for n in r.notes if re.match(r"^(junk|real|clear|verdict|preview|\w+ -> )", n)]
    if judged:
        out.append("\n#### What the validators decided\n")
        out.extend("- " + n for n in judged)
    if invariants:
        out.append("\n#### Money accounting (balance vs. what the ledger owes)\n")
        out.append("| checkpoint | contract balance | credits owed | compensation owed | state |\n|---|---|---|---|---|")
        for i in invariants:
            out.append("| %s | %d | %d | %d | %s |" % (i["label"], i["balance"], i["credits"], i["compensation"], i["status"]))
    return "\n".join(out) + "\n"


def inject_readme(readme: pathlib.Path, block: str):
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    section = MARKER_START + "\n" + block + MARKER_END
    if MARKER_START in text and MARKER_END in text:
        pre = text.split(MARKER_START)[0]
        post = text.split(MARKER_END, 1)[1]
        text = pre + section + post
    else:
        text = text.rstrip() + "\n\n## Live end-to-end report\n\n" + section + "\n"
    readme.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# live environment (the only code that touches the network)
# --------------------------------------------------------------------------

ROLES = ["owner", "maintainer", "reporter", "attacker", "stranger"]


def _find_ret(obj, depth=0):
    """Best-effort: dig the contract's JSON return value out of a receipt."""
    if depth > 8:
        return None
    if isinstance(obj, str):
        s = obj.strip()
        for _ in range(2):
            try:
                v = json.loads(s)
            except Exception:
                return None
            if isinstance(v, dict) and ("ok" in v or "preview_verdict" in v):
                return v
            if isinstance(v, str):
                s = v
                continue
            return None
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            r = _find_ret(v, depth + 1)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _find_ret(v, depth + 1)
            if r:
                return r
    return None


class LiveEnv:
    live = True
    cross_contract = True
    models_transfers = True

    def __init__(self, args):
        from genlayer_py import create_client, create_account, chains  # lazy: offline tests do not need it
        self.args = args
        chain_attr, rpc_default, self.explorer = NETWORKS[args.network]
        self.chain = getattr(chains, chain_attr)
        self.rpc = args.rpc or os.environ.get("GENLAYER_RPC_URL") or rpc_default
        self.client = create_client(chain=self.chain, endpoint=self.rpc)
        self.rpc = self.rpc or self.chain.rpc_urls["default"]["http"][0]
        self.accounts = {r: create_account() for r in ROLES}
        self.fixture_base = self._fixture_base()
        self.deployed: dict[str, str] = {}

    # -- plumbing --------------------------------------------------------
    def _fixture_base(self) -> str:
        if self.args.fixture_base:
            return self.args.fixture_base.rstrip("/")
        repo = os.environ.get("GITHUB_REPOSITORY")
        branch = os.environ.get("GITHUB_REF_NAME") or self._git("rev-parse", "--abbrev-ref", "HEAD")
        if not repo:
            url = self._git("config", "--get", "remote.origin.url")
            m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url or "")
            repo = m.group(1) if m else None
        if not repo or not branch:
            sys.exit("cannot work out where the fixtures are hosted; pass --fixture-base URL")
        return "https://raw.githubusercontent.com/%s/%s/fixtures/evidence" % (repo, branch)

    @staticmethod
    def _git(*a) -> str:
        try:
            return subprocess.check_output(["git", *a], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""

    def address(self, role):
        return self.accounts[role].address

    def fresh_address(self):
        from genlayer_py import create_account
        return create_account().address

    def evidence(self, name):
        return "%s/%s.md" % (self.fixture_base, name)

    def sleep(self, s):
        time.sleep(max(0, s))

    def _fees(self, kind, **kw):
        if self.args.fees == "none":
            return None
        try:
            est = (self.client.estimate_transaction_fees_for_write(**kw) if kind == "write"
                   else self.client.estimate_transaction_fees())
            if not est.get("feeValue"):
                return None
            return {"distribution": est["distribution"], "feeValue": est["feeValue"]}
        except Exception:
            return None

    def _wait(self, h):
        return self.client.wait_for_transaction_receipt(
            transaction_hash=h, interval=3000, retries=max(10, int(self.args.tx_timeout / 3)))

    # -- preflight --------------------------------------------------------
    def preflight(self):
        problems = []
        try:
            cid = int(self.client.provider.make_request("eth_chainId", [])["result"], 16)
            print("rpc %s  chain id %d" % (self.rpc, cid))
            if cid != self.chain.id:
                problems.append("chain id %d != expected %d for %s" % (cid, self.chain.id, self.args.network))
        except Exception as e:
            problems.append("RPC unreachable: %s" % e)
            return problems
        for name in FIXTURES:
            url = self.evidence(name)
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    if resp.status != 200:
                        problems.append("fixture %s -> HTTP %d" % (url, resp.status))
            except urllib.error.HTTPError as e:
                problems.append("fixture %s -> HTTP %d (push the branch and fixtures/ first; the repo must be public)" % (url, e.code))
            except Exception as e:
                problems.append("fixture %s unreachable: %s" % (url, e))
        for role in ROLES:
            try:
                self.client.fund_account(self.address(role), self.args.fund * ONE_GEN)
            except Exception as e:
                problems.append("could not fund %s via sim_fundAccount: %s" % (role, e))
                break
        return problems

    # -- Env interface -----------------------------------------------------
    def deploy(self, role, name, args):
        code = (ROOT / "contracts" / (name + ".py")).read_text(encoding="utf-8")
        acct = self.accounts[role]
        fees = self._fees("deploy")
        h = self.client.deploy_contract(code=code, account=acct, args=args, fees=fees)
        rcpt = self._wait(h)
        if not _succeeded(rcpt):
            raise Fail("deploy %s did not succeed: %s" % (name, json.dumps(rcpt.get("lifecycle"), default=str)))
        addr = (rcpt.get("data") or {}).get("contract_address") or rcpt.get("to_address") \
            or rcpt.get("recipient") or rcpt.get("contract_address")
        if not addr:
            raise Fail("deploy %s: contract address not found in the receipt" % name)
        return addr, h

    def write(self, role, addr, method, args, value=0) -> Tx:
        acct = self.accounts[role]
        try:
            fees = self._fees("write", address=addr, function_name=method, account=acct, args=args, value=value)
            h = self.client.write_contract(address=addr, function_name=method, account=acct,
                                           args=args, value=value, fees=fees)
        except Exception as e:
            return Tx(False, "", "send-failed", None, str(e)[:300])
        try:
            rcpt = self._wait(h)
        except Exception as e:
            return Tx(False, h, "timeout", None, str(e)[:300])
        life = rcpt.get("lifecycle") or {}
        outcome = "%s/%s" % (life.get("state"), life.get("outcome"))
        return Tx(_succeeded(rcpt), h, outcome, _find_ret(rcpt), "")

    def read(self, addr, method, args):
        v = self.client.read_contract(address=addr, function_name=method, args=args,
                                      account=self.accounts["owner"])
        if isinstance(v, str) and v[:1] in "{[":
            return json.loads(v)
        return v


def _succeeded(rcpt) -> bool:
    from genlayer_py.assertions import tx_execution_succeeded
    life = rcpt.get("lifecycle") or {}
    if life.get("state") not in ("decided", "finalized"):
        return False
    if life.get("outcome") not in (None, "accepted"):
        return False
    return tx_execution_succeeded(rcpt)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--network", choices=sorted(NETWORKS), default=os.environ.get("E2E_NETWORK", "studio_next"),
                   help="studio_next (default, chain 61997), studio_devnet (same chain), studionet (older, comparison only)")
    p.add_argument("--rpc", help="override the RPC URL")
    p.add_argument("--fixture-base", default=os.environ.get("E2E_FIXTURE_BASE_URL"),
                   help="base URL that serves fixtures/evidence/*.md")
    p.add_argument("--quick", action="store_true", help="skip the preview and 3 of the 4 hostile-evidence probes")
    p.add_argument("--only", help="comma separated scenario ids, e.g. F1,F2,A4 (dependencies must be included)")
    p.add_argument("--skip", default="", help="comma separated scenario ids to skip")
    p.add_argument("--cooldown", type=int, default=int(os.environ.get("E2E_COOLDOWN", "120")),
                   help="action cooldown (s) the contract is deployed with")
    p.add_argument("--tx-timeout", type=int, default=int(os.environ.get("E2E_TX_TIMEOUT", "900")))
    p.add_argument("--settle", type=int, default=int(os.environ.get("E2E_SETTLE_SECONDS", "120")),
                   help="seconds to wait for an outbound transfer to be applied")
    p.add_argument("--strict-transfers", action="store_true",
                   default=os.environ.get("E2E_STRICT_TRANSFERS") == "1",
                   help="make a transfer that never lands a FAIL instead of a WARN")
    p.add_argument("--retries", type=int, default=2, help="re-sends after a RETRY_LATER verdict")
    p.add_argument("--fund", type=int, default=20, help="GEN requested from the faucet per account")
    p.add_argument("--fees", choices=("auto", "none"), default="auto")
    p.add_argument("--out", default=str(ROOT / "reports"))
    p.add_argument("--update-readme", action="store_true", help="write the report into README.md between markers")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    t0 = time.time()
    env = LiveEnv(args)
    print("network %s, fixtures from %s" % (args.network, env.fixture_base))
    problems = env.preflight()
    if problems:
        print("\nPREFLIGHT FAILED:")
        for p in problems:
            print("  - " + p)
        return 2

    ctx = Ctx(env, args)
    only = set(args.only.split(",")) if args.only else None
    results = run_all(ctx, only, set(filter(None, args.skip.split(","))))

    meta = {
        "network": "%s (%s)" % (args.network, env.chain.name), "chain id": env.chain.id, "rpc": env.rpc,
        "commit": LiveEnv._git("rev-parse", "--short", "HEAD") or "n/a",
        "run at (UTC)": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "duration": "%d min %d s" % divmod(int(time.time() - t0), 60), "explorer": env.explorer,
        "contracts": {"SentinelHalt": ctx.s.get("sentinel", "n/a"), "TreasuryVault": ctx.s.get("vault", "n/a")},
    }
    md = render_markdown(meta, results, ctx.invariants)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live-e2e-latest.md").write_text(md, encoding="utf-8")
    (out / "live-e2e-latest.json").write_text(json.dumps(
        {"meta": meta, "results": [r.__dict__ for r in results], "invariants": ctx.invariants}, indent=2, default=str),
        encoding="utf-8")
    if args.update_readme:
        inject_readme(ROOT / "README.md", md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    print("\n" + md)
    print("report written to %s" % (out / "live-e2e-latest.md"))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
