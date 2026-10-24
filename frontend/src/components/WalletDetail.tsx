import type { CSSProperties } from 'react';
import type { Wallet } from '../wallets';

const money = (amount: number) => `$${amount.toFixed(2)}`;
const time = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });
const date = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' });

interface Props {
  wallet: Wallet;
  onAddFunds: () => void;
  onEditConstraints: () => void;
  onRestore: () => void;
}

export function WalletDetail({ wallet, onAddFunds, onEditConstraints, onRestore }: Props) {
  const transactions = [...(wallet.transactions ?? [])].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  const merchants = [...new Set(transactions.map(transaction => transaction.merchant))];
  const groups = merchants.map((merchant, index) => ({
    merchant, color: `var(--color-chart-${index % 3 + 1})`,
    amount: transactions.filter(transaction => transaction.merchant === merchant).reduce((sum, transaction) => sum + transaction.amount, 0),
  }));
  const spent = groups.reduce((sum, group) => sum + group.amount, 0);
  const scale = Math.max(spent, wallet.constraints.spend);
  return <article className="wallet-detail" aria-label={`${wallet.name} wallet details`}>
    <section className="budget" aria-label="Demo spending breakdown">
      <div className="budget-label">
        <h1>{wallet.name}</h1>
        <div className="budget-actions"><span className="budget-used" title="Demo spending / spending limit">{money(spent)} / {money(wallet.constraints.spend)}</span>
          <button className="primary-button" disabled={wallet.archived} onClick={onAddFunds}>Add funds</button>
        </div>
      </div>
      <div className="budget-track" role="img" aria-label={`${money(spent)} in demo spending out of a ${money(wallet.constraints.spend)} limit`}>
        {groups.map(group => <span key={group.merchant} className="budget-segment" style={{ width: `${group.amount / scale * 100}%`, background: group.color }} />)}
      </div>
      <div className="budget-legend">{groups.map(group => <span key={group.merchant}><i style={{ background: group.color }} />{group.merchant}</span>)}
        {!groups.length && <span>No demo spending yet</span>}
        {spent > wallet.constraints.spend && <span className="budget-over-limit">Over spending limit</span>}
      </div>
    </section>
    <section className="wallet-policy" aria-labelledby="constraint-heading">
      <h2 id="constraint-heading">{wallet.archived ? 'Archived wallet · Spending rules' : 'Spending rules'}</h2>
      {wallet.description && <p className="wallet-description">{wallet.description}</p>}
      <p className="constraints">
        Spend up to <button disabled={wallet.archived} onClick={onEditConstraints}>${wallet.constraints.spend}</button> over <button disabled={wallet.archived} onClick={onEditConstraints}>{wallet.constraints.days} {wallet.constraints.days === 1 ? 'day' : 'days'}</button>, only at{' '}
        {wallet.constraints.merchants.map((merchant, index, list) => <span key={`${merchant}-${index}`}>
          <button disabled={wallet.archived} onClick={onEditConstraints}>{merchant}</button>{index < list.length - 2 ? ', ' : index === list.length - 2 ? ' and ' : '. '}
        </span>)}
        Ask me <button disabled={wallet.archived} onClick={onEditConstraints}>above ${wallet.constraints.approval}</button>. <button disabled={wallet.archived} onClick={onEditConstraints}>{wallet.constraints.sweep ? 'Sweep back' : 'Keep funds'}</button> when done.
      </p>
      {wallet.archived && <button className="text-button restore" onClick={onRestore}>Restore wallet</button>}
    </section>
    <div className="wallet-activity">
      <div className="activity-illustration"><img src="/assets/wallet-activity-organism.svg" width="356" height="406" alt="" /></div>
      <section className="transactions" aria-labelledby="transactions-heading">
        <header><span>Demo activity</span><h2 id="transactions-heading">Transactions</h2></header>
        <div className="transaction-list" tabIndex={transactions.length ? 0 : undefined} role="region" aria-label="Demo transactions">
          {transactions.map(transaction => <article className="transaction-card" key={transaction.id}>
            <div className="transaction-main"><h3>{transaction.title}</h3>
              <span className="transaction-merchant" style={{ '--merchant-color': groups.find(group => group.merchant === transaction.merchant)?.color } as CSSProperties}><i />{transaction.merchant}</span>
              <span className="transaction-amount">{money(transaction.amount)}</span>
            </div>
            <div className="transaction-meta"><span>{transaction.durationSeconds}s</span><time dateTime={transaction.timestamp} title={`${date.format(new Date(transaction.timestamp))}, ${time.format(new Date(transaction.timestamp))} ET`}>{date.format(new Date(transaction.timestamp))} · {time.format(new Date(transaction.timestamp))} ET</time></div>
          </article>)}
          {!transactions.length && <p className="transaction-empty">No transactions for this wallet yet.</p>}
        </div>
      </section>
    </div>
  </article>;
}
