import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { ChevronRight } from '@untitledui/icons';
import {
  activityItems, activitySummary, durationLabel, isExpired, nameLookup, planSkipped, segmentWidth,
  settledByMerchant, shortHash, spending, statusLabel, uniquePayments, type PaymentItem, type RefusalItem,
} from '../activity';
import type { Vendor } from '../api';
import type { CardVendor } from '../api';
import { explorerAccount, formatAmount, shortAddress } from '../format';
import { ACTIVE_STATUSES } from '../live';
import type { DemoPayment } from '../researchDemo';
import { PaymentRequest, paymentLabel } from './PaymentRequest';
import type { Wallet } from '../wallets';
import { VIEW } from '../lib/walletSpheres';
import { WalletOrganism } from './WalletOrganism';

const money = (amount: number | string | null | undefined) => formatAmount(amount);
const time = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });
const date = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' });

interface Props {
  wallet: Wallet;
  payments?: DemoPayment[];
  onAddFunds: () => void;
  onEditConstraints: () => void;
  onRestore: () => void;
  /** Live only: wallet cleanup controls (WalletActions). */
  actions?: ReactNode;
  /** Live only: the vendor directory (GET /vendors), to name payees that are not on this wallet's list. */
  vendors?: Vendor[];
  /** The graphic: every active wallet as a sphere around the total, as an alternative to the sidebar. */
  map: MapProps;
}

interface MapProps { wallets: Wallet[]; totalBalance: number; onSelect: (id: string) => void; onHome: () => void }

export function WalletDetail(props: Props) {
  return props.wallet.live ? <LiveWalletDetail {...props} /> : <MockWalletDetail {...props} />;
}

function MockWalletDetail({ wallet, onAddFunds, onEditConstraints, onRestore, payments = [], map }: Props) {
  const transactions = [...(wallet.transactions ?? [])].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  const merchants = [...new Set(transactions.map(transaction => transaction.merchant))];
  const groups = merchants.map((merchant, index) => ({
    merchant, color: `var(--color-chart-${index % 3 + 1})`,
    amount: transactions.filter(transaction => transaction.merchant === merchant).reduce((sum, transaction) => sum + transaction.amount, 0),
  }));
  const spent = groups.reduce((sum, group) => sum + group.amount, 0);
  const scale = Math.max(spent, wallet.constraints.spend);
  const activity = [
    ...transactions.map(transaction => ({ id: transaction.id, at: transaction.timestamp, transaction, payment: payments.find(payment => payment.id === transaction.id) })),
    ...payments.filter(payment => payment.status !== 'paid').map(payment => ({ id: payment.id, at: payment.createdAt, transaction: undefined, payment })),
  ].sort((a, b) => Number(b.payment?.status === 'pending') - Number(a.payment?.status === 'pending') || Date.parse(b.at) - Date.parse(a.at));
  return <article className="wallet-detail" aria-label={`${wallet.name} wallet details`}>
    <section className="budget" aria-label="Spending breakdown">
      <div className="budget-label">
        <h1>{wallet.name}</h1>
        <div className="budget-actions"><span className="budget-used" title="Spending / spending limit">{money(spent)} / {money(wallet.constraints.spend)}</span>
          <button className="primary-button" disabled={wallet.archived || !!wallet.demoClosedAt} onClick={onAddFunds}>Add funds</button>
        </div>
      </div>
      <div className="budget-track" role="img" aria-label={`${money(spent)} spent out of a ${money(wallet.constraints.spend)} limit`}>
        {groups.map(group => <span key={group.merchant} className="budget-segment" style={{ width: `${group.amount / scale * 100}%`, background: group.color }} />)}
      </div>
      <div className="budget-legend">{groups.map(group => <span key={group.merchant}><i style={{ background: group.color }} />{group.merchant}</span>)}
        {!groups.length && <span>No spending yet</span>}
        {spent > wallet.constraints.spend && <span className="budget-over-limit">Over spending limit</span>}
      </div>
    </section>
    <section className="wallet-policy" aria-label="Spending rules">
      {wallet.archived && <h2>Archived wallet</h2>}
      <p className="constraints">
        Spend up to <button disabled={wallet.archived} onClick={onEditConstraints}>${wallet.constraints.spend}</button> over <button disabled={wallet.archived} onClick={onEditConstraints}>{wallet.constraints.days} {wallet.constraints.days === 1 ? 'day' : 'days'}</button>, only at{' '}
        {wallet.constraints.merchants.map((merchant, index, list) => <span key={`${merchant}-${index}`}>
          <button disabled={wallet.archived} onClick={onEditConstraints}>{merchant}</button>{index < list.length - 2 ? ', ' : index === list.length - 2 ? ' and ' : '. '}
        </span>)}
        {/* An approval threshold at or above the limit can never trigger, so it is not a rule worth stating. */}
        {wallet.constraints.approval < wallet.constraints.spend && <>Ask me <button disabled={wallet.archived} onClick={onEditConstraints}>above ${wallet.constraints.approval}</button>. </>}<button disabled={wallet.archived} onClick={onEditConstraints}>{wallet.constraints.sweep ? 'Sweep back' : 'Keep funds'}</button> when done.
      </p>
      {wallet.demoClosedAt && <p className="demo-note">${(wallet.demoReturnedBalance ?? 0).toFixed(2)} returned to the demo treasury. Wallet closed after research.</p>}
      {wallet.archived && <button className="text-button restore" onClick={onRestore}>Restore wallet</button>}
    </section>
    <Activity walletId={wallet.id} map={map} summary="Activity" attention={payments.some(payment => payment.status === 'pending')}>
      <div className="transaction-list" tabIndex={transactions.length || payments.length ? 0 : undefined} role="region" aria-label="Transactions">
        {activity.map(entry => {
          if (!entry.transaction) return <PaymentRequest key={entry.id} payment={entry.payment!} />;
          const transaction = entry.transaction;
          return <article className="transaction-card" key={entry.id}>
            <div className="transaction-main"><h3>{transaction.title}</h3>
              <span className="transaction-merchant" style={{ '--merchant-color': groups.find(group => group.merchant === transaction.merchant)?.color } as CSSProperties}><i />{transaction.merchant}</span>
              <span className="transaction-amount">{money(transaction.amount)}</span>
            </div>
            <div className="transaction-meta"><span>{transaction.durationSeconds}s</span><time dateTime={transaction.timestamp} title={`${date.format(new Date(transaction.timestamp))}, ${time.format(new Date(transaction.timestamp))} ET`}>{date.format(new Date(transaction.timestamp))} · {time.format(new Date(transaction.timestamp))} ET</time></div>
            {entry.payment && <p className="payment-reason"><span className="payment-badge paid">{paymentLabel(entry.payment)}</span></p>}
          </article>;
        })}
        {!transactions.length && !payments.length && <p className="transaction-empty">No transactions for this wallet yet.</p>}
      </div>
    </Activity>
  </article>;
}

/** Transactions sit left of the illustration, collapsed to their header; opening the list pushes the illustration right.
 * It stays mounted across wallets so the graphic can animate between them; the list closes for each new wallet. */
function Activity({ walletId, map, summary, attention = false, children }: { walletId: string; map: MapProps; summary: string;
  /** Something in the list needs the owner (a payment waiting for approval): open it, so the request is never hidden. */
  attention?: boolean; children: ReactNode }) {
  const [openFor, setOpenFor] = useState<string>();
  const open = openFor === walletId;
  useEffect(() => { if (attention) setOpenFor(walletId); }, [attention, walletId]);
  const setOpen = (next: boolean) => setOpenFor(next ? walletId : undefined);
  return <div className="wallet-activity" data-open={open}>
    <section className="transactions" aria-labelledby="transactions-heading">
      <header>
        <h2 id="transactions-heading"><button aria-expanded={open} aria-controls="transactions-body" onClick={() => setOpen(!open)}>
          Transactions<ChevronRight aria-hidden /></button></h2>
        <span className="activity-summary">{summary}</span>
      </header>
      <div id="transactions-body" className="transactions-body"><div>{children}</div></div>
    </section>
    <div className="activity-illustration organism-frame"><WalletOrganism {...map} selectedId={walletId} framed={VIEW} /></div>
  </div>;
}

/** "Oct 24 · 7:20 PM ET"; nothing when the record has no usable time. */
function When({ at }: { at?: string }) {
  const d = new Date(at ?? '');
  if (!at || !Number.isFinite(d.getTime())) return null;
  return <time dateTime={at} title={`${date.format(d)}, ${time.format(d)} ET`}>{date.format(d)} · {time.format(d)} ET</time>;
}

function Explorer({ href, title, children }: { href: string; title: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" title={title}>{children}</a>;
}

const INACTIVE_MERCHANT = 'var(--color-marker-inactive)';

function PaymentCard({ item, color }: { item: PaymentItem; color?: string }) {
  return <article className="transaction-card" data-state={item.state} data-hash={item.hash}>
    <div className="transaction-main"><h3>{item.title}</h3>
      <span className="transaction-merchant" style={{ '--merchant-color': color ?? INACTIVE_MERCHANT } as CSSProperties}><i />{item.merchant}</span>
      <span className="transaction-amount">{money(item.amount)}</span>
    </div>
    <div className="transaction-meta">
      <div className="transaction-facts">
        <span className="transaction-state" data-state={item.state}>{item.stateLabel}</span>
        {item.rail && <span className="transaction-rail">{item.rail}</span>}
        {item.ledger && <span className="transaction-approval">Approved on your Ledger{item.ledger.threshold ? ` above ${money(item.ledger.threshold)}` : ''}</span>}
        {item.hash && item.link && <Explorer href={item.link} title={`${item.hash} on the testnet explorer`}>{shortHash(item.hash)}</Explorer>}
      </div>
      <When at={item.at} />
    </div>
  </article>;
}

/** A refused attempt: cereal would not co-sign (kind refusal) or the ledger rejected it (kind ledger). Never spending. */
function RefusalCard({ item }: { item: RefusalItem }) {
  return <article className="refusal-card" data-kind={item.kind} data-code={item.code}>
    <div className="transaction-main"><h3>{item.reason}</h3>
      {item.payee && <span className="transaction-merchant" style={{ '--merchant-color': INACTIVE_MERCHANT } as CSSProperties}><i />{item.payee}</span>}
      {item.amount && <span className="transaction-amount" title="Requested; nothing was sent">{money(item.amount)}</span>}
    </div>
    <div className="transaction-meta">
      <div className="transaction-facts">
        <span className="transaction-state" data-state="refused">{item.stateLabel}</span>
        {item.rail && <span className="transaction-rail">{item.rail}</span>}
        {item.detail && <span className="refusal-detail">{item.detail}</span>}
        {item.link && item.linkLabel && <Explorer href={item.link} title="The rejected transaction on the testnet explorer">{item.linkLabel}</Explorer>}
        {item.revocation?.link && <Explorer href={item.revocation.link} title="The public credential revocation on the testnet explorer">
          Revocation{item.revocation.hash ? ` ${shortHash(item.revocation.hash)}` : ''}</Explorer>}
        {item.revocation?.reason && <span>Reason: {item.revocation.reason}</span>}
      </div>
      <When at={item.at} />
    </div>
  </article>;
}

/** I04/V04: the live wallet, straight from GET /subagents/{id}. Spending is validated payments only; pending and
 * failed payments and refused attempts are shown as what they are, each with its ledger evidence. */
function LiveWalletDetail({ wallet, vendors, onAddFunds, onEditConstraints, onRestore, actions, map }: Props) {
  const live = wallet.live!;
  const rec = live.record;
  const nameOf = nameLookup(vendors);
  // Spent and pending come from unique, validated payments (see activity.ts), so the header, figures and bar agree.
  const payments = uniquePayments(rec.payments);
  const { spent, pending } = spending(payments);
  const merchants = settledByMerchant(payments, nameOf);
  const colorOf = new Map(merchants.map(m => [m.address, m.color]));
  const items = activityItems(rec, nameOf);
  const summary = activitySummary(items);
  const skipped = planSkipped(rec.plan);
  // Sites named in the wallet's sentence (docs/SITES.md): a paid site is named by its site name, a free one is read
  // for free, and a wallet that named its vendors pays exactly them, never "any credentialed vendor".
  const siteVendors = ((rec.card as { vendors?: CardVendor[] } | undefined)?.vendors ?? []).filter(v => v.site);
  const siteName = new Map(siteVendors.filter(v => v.address).map(v => [v.address as string, v.name ?? v.named]));
  const freeSites = siteVendors.filter(v => v.site?.trust === 'free').map(v => v.name ?? v.named);
  const payeesLocked = rec.payees_locked === true;
  const payees = (rec.allowed_payees ?? []).map(address => siteName.get(address) ?? nameOf(address));
  const active = live.status === 'active';
  const editable = active && !wallet.archived;
  const finished = !ACTIVE_STATUSES.includes(live.status);
  const expired = isExpired(live.expiresAt);
  // Money added after expiry could not be spent: cereal refuses every payment once the window has passed.
  const fundable = active && !wallet.archived && !expired;
  const days = wallet.constraints.days;
  const duration = durationLabel(live.createdAt, live.expiresAt) ?? `${days} ${days === 1 ? 'day' : 'days'}`;
  const rule = { disabled: !editable, onClick: onEditConstraints };
  return <article className="wallet-detail is-live" aria-label={`${wallet.name} wallet details`} data-status={live.status}>
    <section className="budget" aria-label="Spending breakdown">
      <div className="budget-label">
        <div className="wallet-heading"><h1>{wallet.name}</h1>
          <span className="wallet-status" data-status={live.status} title="Lifecycle state on the cereal service">{statusLabel(live.status)}</span></div>
        <div className="budget-actions"><span className="budget-used" title="Validated spending / budget">{`${money(spent)} / ${money(live.budget)}`}</span>
          <button className="primary-button" disabled={!fundable} onClick={onAddFunds}
            title={active && expired ? 'This wallet has expired; cereal refuses its payments. Extend its rules first.' : undefined}>Add funds</button>
        </div>
      </div>
      <div className="budget-track" role="img" aria-label={`${money(spent)} settled out of a ${money(live.budget)} budget`}>
        {merchants.map(m => <span key={m.address} className="budget-segment" data-merchant={m.merchant}
          style={{ width: `${segmentWidth(m.amount, spent, live.budget)}%`, background: m.color }} />)}
      </div>
      <div className="budget-legend">{merchants.map(m => <span key={m.address}><i style={{ background: m.color }} />{m.merchant} · {money(m.amount)}</span>)}
        {!merchants.length && <span>No settled spending yet</span>}
        {Number(spent) > Number(live.budget) && <span className="budget-over-limit">Over budget</span>}
        <p className={`wallet-rule-note ${expired ? 'is-expired' : ''}`}>
          {expired ? <>Expired <When at={live.expiresAt} />. cereal refuses every payment after that.</> : <>Expires <When at={live.expiresAt} />.</>}
          {finished && ` This wallet is ${statusLabel(live.status).toLowerCase()}; its rules no longer change.`}
        </p>
      </div>
      <div className="wallet-summary-row">
      <dl className="wallet-figures">
        <div data-figure="available" title={live.available === null ? 'The ledger could not be read' : 'RLUSD the subwallet holds on the ledger now'}><dt>Available</dt><dd>{money(live.available)}</dd></div>
        <div data-figure="spent" title="Payments the ledger validated"><dt>Spent</dt><dd>{money(spent)}</dd></div>
        <div data-figure="pending" title="Handed to a vendor or submitted, not validated yet"><dt>Pending</dt><dd>{money(pending)}</dd></div>
        <div data-figure="returned" title="Swept back to the main wallet"><dt>Returned</dt><dd>{money(live.returned)}</dd></div>
        {live.address && <div data-figure="address"><dt>Subwallet</dt><dd>
          <Explorer href={explorerAccount(live.address)!} title={`${live.address} on the testnet explorer`}>{shortAddress(live.address)}</Explorer></dd></div>}
      </dl>
      {actions}
      </div>
    </section>
    <section className="wallet-policy" aria-label="Spending rules">
      {wallet.archived && <h2>Archived wallet</h2>}
      <p className="constraints">
        Spend up to <button {...rule}>{money(live.budget)}</button> over <button {...rule}>{duration}</button>,{' '}
        {payees.length ? <>only at{' '}{payees.map((payee, index, list) => <span key={`${payee}-${index}`}>
          <button {...rule}>{payee}</button>{index < list.length - 2 ? ', ' : index === list.length - 2 ? ' and ' : '. '}
        </span>)}</> : payeesLocked ? <><button {...rule}>pays no vendor</button>. </> : <>at <button {...rule}>any credentialed vendor</button>. </>}
        {freeSites.length > 0 && <>Reads {freeSites.map((site, index, list) => <span key={site}>
          <button {...rule}>{site}</button>{index < list.length - 2 ? ', ' : index === list.length - 2 ? ' and ' : ''}
        </span>)} for free. </>}
        {live.approval !== null && live.approval !== ''
          ? <>Ask me <button {...rule}>above {money(live.approval)}</button>. </>
          : <><button {...rule}>cereal co-signs every payment</button>. </>}
        <button {...rule}>{wallet.constraints.sweep ? 'Sweep back' : 'Keep funds'}</button> when done.
      </p>
      {skipped.length > 0 && <p className="wallet-plan-note">Skipped while planning:{' '}
        {skipped.map((s, i) => <span key={`${s.vendor}-${s.reason}`}>{i ? '; ' : ''}{s.vendor}{s.price ? ` (${money(s.price)})` : ''}, {s.reason}
          {s.link && <> · <Explorer href={s.link} title="Evidence on the testnet explorer">evidence</Explorer></>}</span>)}.
      </p>}
      {wallet.archived && <button className="text-button restore" onClick={onRestore}>Restore wallet</button>}
    </section>
    <Activity walletId={wallet.id} map={map} summary={summary || 'No activity yet'}>
      <div className="transaction-list" tabIndex={items.length ? 0 : undefined} role="region" aria-label="Wallet activity">
        {items.map(item => item.kind === 'payment'
          ? <PaymentCard key={item.key} item={item} color={item.state === 'settled' ? colorOf.get(item.address) : undefined} />
          : <RefusalCard key={item.key} item={item} />)}
        {!items.length && <p className="transaction-empty">No payments or refused attempts for this wallet yet.</p>}
      </div>
    </Activity>
  </article>;
}
