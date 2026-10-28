export function HowItWorks() {
  return (
    <section className="card" aria-labelledby="how-title">
      <h2 className="card-title" id="how-title">
        <span>How it works</span>
      </h2>

      <div className="steps3">
        <div className="how">
          <div className="num">1</div>
          <h4>Anyone files evidence</h4>
          <p>
            Point at a public page - a block-explorer transaction, a write-up, a proof of concept - and say
            what it shows. A small refundable bond rides with the claim so spam is not free.
          </p>
        </div>
        <div className="how">
          <div className="num">2</div>
          <h4>Validators read it themselves</h4>
          <p>
            Each GenLayer validator fetches the page and asks its own LLM whether it supports the claim for
            this specific contract, right now. Wording may differ; they only have to agree on the verdict.
          </p>
        </div>
        <div className="how">
          <div className="num">3</div>
          <h4>The contract enforces it</h4>
          <p>
            The vault asks SentinelHalt on every single call. No admin key, no multisig, no token vote - and
            clearing a halt needs the same consensus, so a compromised maintainer cannot wave it away.
          </p>
        </div>
      </div>

      <h3 style={{ margin: '24px 0 4px', fontSize: 15 }}>Why this needs decentralized judgment</h3>
      <p style={{ margin: 0, color: 'var(--muted)', fontSize: 14 }}>
        &quot;Is this evidence a real, active exploit against this contract?&quot; is not a number you can
        compare to a threshold. One centralized reporter can be fooled or bribed into freezing a healthy
        protocol; a maintainer deciding alone can wave away a real attack to keep draining funds. Independent
        validators reasoning over the same evidence sit between &quot;nobody arbitrates&quot; and &quot;one party
        arbitrates&quot;.
      </p>

      <h3 style={{ margin: '24px 0 0', fontSize: 15 }}>Verify it yourself</h3>
      <ol className="checklist">
        <li>
          <strong>Register</strong> the vault, then <strong>deposit</strong> a little GEN and note the
          balance.
        </li>
        <li>
          File a <strong>report</strong> with an evidence URL and a claim; watch the validators&apos; verdict
          land in the history.
        </li>
        <li>
          If it was supported, the banner turns red and a <strong>withdrawal now reverts on-chain</strong> -
          submit one to see it fail.
        </li>
        <li>
          Use <strong>Clear halt</strong> with evidence of a fix; once supported, withdrawals work again with
          nothing to reset.
        </li>
      </ol>
    </section>
  );
}
