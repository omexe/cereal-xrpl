import { ArrowUpRight } from '@untitledui/icons';

export function TestEnvironmentLinks() {
  return <section className="demo-settings" aria-labelledby="test-tools-title">
    <h3 id="test-tools-title">Developer tools</h3>
    <p className="dialog-description">Open the research chat and name any active Cereal wallet in your prompt. It reads your live wallets and sends payment tasks through Cereal with their existing rules.</p>
    <div className="approval-actions"><a className="research-launch" href="/test-chat" target="cereal-test-chat" rel="noopener">Open test chat <ArrowUpRight /></a></div>
    <p className="demo-note">The chat interface is simulated. Submitting a task can spend testnet RLUSD through connected vendors.</p>
    <details><summary>Offline fixtures</summary><p className="demo-note">Four wallets from deployment.json. Simulated payments, saved separately in this browser.</p><div className="approval-actions">
      <a className="research-launch" href="/test-wallets" target="cereal-test-wallets" rel="noopener">Open test wallets <ArrowUpRight /></a>
      <a className="research-launch" href="/fixture-chat" target="cereal-fixture-chat" rel="noopener">Open fixture chat <ArrowUpRight /></a>
    </div></details>
  </section>;
}
