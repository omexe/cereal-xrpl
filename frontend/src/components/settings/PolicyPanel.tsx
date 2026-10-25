import type { MainWallet } from '../../api';
import { explorerAccount, formatAmount } from '../../format';
import { ExternalLink, plural, Section } from './parts';

const onOff = (value: boolean) => value ? 'On' : 'Off';

/** The rules the service enforces, as GET /main reports them: credentials, the owner's device, AP4M, and the caps. */
export function PolicyPanel({ main }: { main?: MainWallet }) {
  if (!main) return <Section name="policy" title="Policy"><p className="settings-note">The policy loads with the main wallet.</p></Section>;
  const { policy, caps } = main;
  const ap4m = !!policy.ap4m?.enabled;
  return <Section name="policy" title="Policy">
    <dl className="settings-rows">
      <dt>Vendor credentials</dt><dd data-field="credentials">{policy.vendor_credentials ? 'Required' : 'Not required'}
        <span className="settings-sub">XLS-70 credential on the ledger</span></dd>
      <dt>Credential issuer</dt><dd data-field="issuer"><ExternalLink href={explorerAccount(policy.issuer)}>{policy.issuer}</ExternalLink></dd>
      <dt>Owner device funding</dt><dd data-field="device-funding">{onOff(policy.device_funding)}</dd>
      <dt>Owner device</dt><dd data-field="device">{policy.device
        ? <ExternalLink href={explorerAccount(policy.device)}>{policy.device}</ExternalLink> : 'Not configured'}
        <span className="settings-sub">Speculos, the emulator of a Ledger device</span></dd>
      <dt>Ledger recovery</dt><dd data-field="recovery">{onOff(policy.ledger_recovery)}</dd>
      <dt>AP4M</dt><dd data-field="ap4m">{ap4m ? 'Enabled' : 'Disabled'}
        <span className="settings-sub">{ap4m ? 'Runs on XRPL EVM, not native XRPL' : 'Sidelined. It runs on XRPL EVM, not native XRPL'}</span></dd>
    </dl>
    <h4>Caps</h4>
    <dl className="settings-rows">
      <dt>Budget per wallet<span className="settings-sub">MAX_SUBAGENT_BUDGET</span></dt>
      <dd data-cap="MAX_SUBAGENT_BUDGET">{formatAmount(caps.MAX_SUBAGENT_BUDGET)}</dd>
      <dt>Outstanding budget<span className="settings-sub">MAX_OUTSTANDING_BUDGET</span></dt>
      <dd data-cap="MAX_OUTSTANDING_BUDGET">{formatAmount(caps.MAX_OUTSTANDING_BUDGET)}</dd>
      <dt>Active wallets<span className="settings-sub">MAX_ACTIVE_SUBAGENTS</span></dt>
      <dd data-cap="MAX_ACTIVE_SUBAGENTS">{plural(caps.MAX_ACTIVE_SUBAGENTS, 'wallet')}</dd>
    </dl>
  </Section>;
}
