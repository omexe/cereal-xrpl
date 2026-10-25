/** The chat is a client of Cereal. Wallets, rules, runs, and payment evidence come from the service. */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AlertCircle, ArrowUp, ArrowUpRight, CheckCircle, ChevronDown, Clock, Globe01, Menu01, MessageChatCircle, Plus, ShieldTick, Wallet03 } from '@untitledui/icons';
import { api, ApiError, describeError, type ApiRecord, type Refusal, type Run, type SiteProbe } from './api';
import { activityItems, isExpired, nameLookup, planReason } from './activity';
import { formatAmount } from './format';
import { toWorkspace } from './live';
import { resolveWalletFromPrompt } from './researchDemo';
import { chatRefusal } from './chatOutcome';
import { crawlPlan, siteInMessage, type CrawlPlan } from './siteCrawl';
import { useLiveData } from './store';

const SESSION = 'cereal-live-chat-v1';
const walletUrl = (id?: string) => id ? `/?wallet=${encodeURIComponent(id)}` : '/';
const usable = (r: ApiRecord) => r.status === 'active' && !r.archived && !!r.subwallet && !isExpired(r.expires_at);
const running = (run?: Run | null) => run?.status === 'starting' || run?.status === 'running';
const amount = (value: string | null | undefined) => value == null ? 'Balance unavailable' : formatAmount(value);
type Attempt = { wallet: string; task: string; request_id: string; runTask?: string };
type SentTurn = Attempt & { reply?: string; uncertain?: boolean; result?: Run; crawl?: CrawlPlan; walletName?: string } & CrawlFields;
type Saved = { wallet?: string; attempt?: Attempt; turns?: SentTurn[] };
function saved(): Saved { try { return JSON.parse(sessionStorage.getItem(SESSION) ?? '{}'); } catch { return {}; } }
type RunPlan = { lines?: { item: string; vendor: string; price: string; rejected?: { vendor: string; reason: string }[] }[] };

function closedWalletMessage(record: ApiRecord): string {
  const name = record.name || record.task;
  if (record.status === 'reclaimed' || record.status === 'recovered' || record.status === 'retired') {
    const returned = record.returned != null ? ` Cereal returned ${amount(record.returned)} to the main wallet.` : '';
    return `${name} is closed.${returned} It can’t pay for another request. Your results stay in this conversation. Choose or create an active wallet in Cereal, then name it in your next message. New chat requests keep active wallets open until you finish them in Cereal or they expire.`;
  }
  return `${name} is ${record.archived ? 'archived' : isExpired(record.expires_at) ? 'expired' : record.status}. It can’t pay for this request. Choose an active wallet in Cereal and name it in your next message.`;
}

function siteCheck(probe: SiteProbe): string {
  if (probe.blocked_by) return `${probe.host} answered with ${probe.blocked_by}'s bot check${probe.archive ? '; reading the Internet Archive copy' : ''}.`;
  if (probe.kind === 'payable' && probe.payment) return `${probe.host} has an x402 paywall: ${probe.payment.amount} RLUSD per request.`;
  if (probe.kind === 'free') return `${probe.host} is reachable (HTTP ${probe.status ?? 200})${probe.title ? `: “${probe.title}”` : ''}.`;
  return `${probe.host}: ${probe.reason ?? probe.kind}.`;
}

/** The crawl's one payment: triggered (spinner while the agent and Cereal sign and the ledger validates), complete
 * (validated, with its explorer link), or failed (the run ended without a validated payment). */
function CrawlTransaction({ state, host, pages, wallet, amount, hash, balance }: { state: 'waiting' | 'triggered' | 'complete' | 'failed';
  host: string; pages: number; wallet?: string; amount?: string; hash?: string; balance?: string }) {
  const title = state === 'complete' ? 'Transaction complete' : state === 'failed' ? 'Transaction not completed'
    : state === 'waiting' ? 'Transaction queued' : 'Transaction triggered';
  return <article className={`crawl-tx ${state}`} aria-live="polite">
    <div className="crawl-tx-status">{state === 'complete' ? <CheckCircle /> : state === 'failed' ? <AlertCircle /> : <span className="crawl-tx-spinner" role="img" aria-label="Processing" />}</div>
    <div className="crawl-tx-body">
      <div className="crawl-tx-top"><strong>{title}</strong><span className="crawl-tx-amount">{amount ? formatAmount(amount) : '0.02 RLUSD'}</span></div>
      <p>{wallet || 'Your wallet'} → Crawl gateway · {pages} pages of {host}</p>
      <div className="crawl-tx-meta">
        <span>{state === 'complete' ? 'Validated on XRPL testnet · signed by the agent and Cereal'
          : state === 'failed' ? 'No payment was validated'
          : state === 'waiting' ? `${wallet || 'This wallet'} is finishing its previous crawl; this one pays as soon as the wallet is free.`
          : 'Signing with the agent and Cereal, then validating on XRPL testnet…'}</span>
        {hash && <a href={`https://testnet.xrpl.org/transactions/${hash}`} target="_blank" rel="noopener noreferrer">{hash.slice(0, 8)}…{hash.slice(-6)} <ArrowUpRight /></a>}
      </div>
      {state === 'complete' && balance != null && <span className="crawl-tx-balance">{formatAmount(balance)} left in {wallet || 'the wallet'}</span>}
    </div>
  </article>;
}

type PaidPage = { url: string; hash?: string; amount?: string };
/** The run this turn started and shows: `run` is its id, `tag` the `crawl=` marker its gateway URLs carry. Saved on
 * the turn so a reload follows the same run and never starts (and pays for) a second crawl. */
type CrawlFollow = { run: string; tag: string };
type CrawlFields = { crawlCheck?: string; crawlPaid?: PaidPage[]; crawlDone?: boolean; crawlNote?: string; crawlBalance?: string; crawlFollow?: CrawlFollow };
const pageOf = (resource: string) => { try { return new URL(resource).searchParams.get('url') ?? resource; } catch { return resource; } };

/** Probe the site through Cereal, then crawl it: the wallet pays the crawl gateway per page on XRPL testnet and each
 * page shows its payment as it settles. A finished crawl renders from the saved turn. */
function SiteCrawl({ turn, onUpdate }: { turn: SentTurn; onUpdate: (fields: CrawlFields) => void }) {
  const plan = turn.crawl!;
  const [check, setCheck] = useState(turn.crawlCheck);
  const [paid, setPaid] = useState<PaidPage[]>(turn.crawlPaid ?? []);
  const [done, setDone] = useState(!!turn.crawlDone);
  const [note, setNote] = useState(turn.crawlNote);
  const [balance, setBalance] = useState(turn.crawlBalance);
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    if (turn.crawlDone) return;
    let stopped = false, timer = 0;
    const finish = (fields: CrawlFields) => { setDone(true); setNote(fields.crawlNote); onUpdate({ ...fields, crawlDone: true }); };
    void (async () => {
      const result = await api.probeSite(plan.url).then(siteCheck, () => `Couldn’t reach Cereal’s site check for ${plan.host}.`);
      if (stopped) return;
      setCheck(result);
      // A reloaded turn keeps following the run it already started: it never starts (and pays for) a second crawl.
      let follow = turn.crawlFollow;
      // A wallet runs one task at a time: while its previous crawl is still finishing, this one queues (up to
      // 3 minutes) and then pays on its own, so every message gets its own transaction.
      for (let attempt = 0; !follow; attempt++) {
        try {
          const { run } = await api.crawl(turn.wallet, { pages: plan.pages.map(p => p.url), request_id: turn.request_id });
          follow = { run: run.id, tag: `crawl=${encodeURIComponent(turn.request_id)}` };  // each crawl's gateway URLs carry its request id
        } catch (err) {
          const refusal = err instanceof ApiError && err.kind === 'refused' ? err.body as Refusal : null;
          if (refusal?.refused === 'already_running' && attempt < 60 && !stopped) { setWaiting(true); await new Promise(r => setTimeout(r, 3000)); continue; }
          if (!stopped) finish({ crawlCheck: result, crawlNote: refusal ? chatRefusal(refusal) : describeError(err) });
          return;
        }
      }
      if (stopped || !follow) return;
      setWaiting(false);
      const followed = follow;
      onUpdate({ crawlCheck: result, crawlFollow: followed });
      const poll = async () => {
        if (stopped) return;
        try {
          const [{ run }, record] = await Promise.all([api.run(turn.wallet), api.wallet(turn.wallet)]);
          const mine = run?.id === followed.run ? run : null;
          const got = (record.payments ?? []).filter(p => p.ok === true && p.resource?.includes(followed.tag))
            .map(p => ({ url: pageOf(p.resource!), hash: p.hash, amount: p.amount }));
          setPaid(got); setBalance(record.balance ?? undefined);
          // Over once the followed run has ended, or once the wallet has moved on to another run.
          if (mine ? !running(mine) : !!run) { finish({ crawlCheck: result, crawlPaid: got, crawlBalance: record.balance ?? undefined, crawlNote: mine?.error ?? undefined }); return; }
        } catch { /* a missed poll retries */ }
        timer = window.setTimeout(poll, 2000);
      };
      void poll();
    })();
    return () => { stopped = true; clearTimeout(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const payment = paid[0];  // one gateway payment covers the whole crawl
  return <>
    <p>Using <strong>{turn.walletName || 'your wallet'}</strong> to crawl <strong>{plan.host}</strong> for “{plan.topic}”. The crawl is one RLUSD payment to Cereal’s crawl gateway on XRPL testnet, co-signed by Cereal.</p>
    <p className="crawl-check">{check ?? `Querying ${plan.host}…`}</p>
    {check && <CrawlTransaction state={payment ? 'complete' : done ? 'failed' : waiting ? 'waiting' : 'triggered'} host={plan.host} pages={plan.pages.length}
      wallet={turn.walletName} amount={payment?.amount} hash={payment?.hash} balance={balance} />}
    {note && <p className="chat-error" role="alert">{note}</p>}
    {payment && <section className="research-summary" aria-label="Research"><h2>{plan.heading}</h2>{plan.summary?.map((text, i) => <p key={i}>{text}</p>)}<ul>{plan.results.map(r => <li key={r.name}><strong>{r.name}</strong>{r.price ? ` · ${r.price}` : ''}: {r.detail}</li>)}</ul><p className="chat-disclaimer">Sample research text. The page reads and the payment above are real.</p></section>}
  </>;
}

function PastResult({ run }: { run: Run }) {
  const plan = run.plan as RunPlan | undefined;
  return <>
    <p>Task {run.status.replace(/_/g, ' ')}</p>
    {run.summary && <p>{run.summary}</p>}
    {run.error && <p>{run.error}</p>}
    {!!run.resources?.length && <section className="research-summary" aria-label="Retrieved data"><h2>Retrieved data</h2>{run.resources.map(resource => <div key={resource.resource}><h3>{resource.title}</h3>{resource.sample && <p className="chat-disclaimer">Sample research data</p>}<p>{resource.summary}</p><ul>{resource.findings?.map((finding, i) => <li key={i}>{finding}</li>)}</ul></div>)}</section>}
    {!!plan?.lines?.length && <section className="research-summary"><h2>Purchase plan</h2>{plan.lines.map(line => <p key={line.item}>{line.item} · {line.vendor} · {amount(line.price)}</p>)}</section>}
  </>;
}

export default function LiveResearchChat() {
  const [initial] = useState(saved);
  const [selected, setSelected] = useState<string | undefined>(initial.wallet);
  const [attempt, setAttempt] = useState<Attempt | undefined>(initial.attempt);
  const [prompt, setPrompt] = useState(initial.turns?.length ? '' : initial.attempt?.task ?? '');
  const [turns, setTurns] = useState<SentTurn[]>(() => (initial.turns ?? []).map(turn => turn.reply || turn.result || turn.crawl ? turn : { ...turn, uncertain: true, reply: 'The response was interrupted. Check Cereal for the current outcome, or retry this request to check it safely.' }));
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState('');
  const [runError, setRunError] = useState('');
  const [busy, setBusy] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [clarification, setClarification] = useState<{ message: string; ids: string[] }>();
  const inFlight = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const live = useLiveData(true, selected);
  const wallets = live.records.filter(usable);
  const record = live.records.find(r => r.id === selected);
  const matching = resolveWalletFromPrompt(toWorkspace(wallets, live.vendors, live.folders), prompt);
  const hinted = record ?? wallets.find(r => r.id === matching.walletId);
  const history = live.records.filter(r => r.run);
  const items = record ? activityItems(record, nameLookup(live.vendors)) : [];
  const plan = run?.plan as RunPlan | undefined;
  const active = running(run) && (!attempt || run?.request_id === attempt.request_id);
  // Keep completed responses when the backend replaces its latest run with a follow-up.
  useEffect(() => {
    if (!run) return;
    setTurns(previous => {
      let changed = false;
      const updated = previous.map(turn => {
        if (turn.request_id !== run.request_id || (!turn.reply && !turn.uncertain && JSON.stringify(turn.result) === JSON.stringify(run))) return turn;
        changed = true;
        return { ...turn, result: run, reply: undefined, uncertain: false };
      });
      return changed ? updated : previous;
    });
  }, [run]);

  useEffect(() => { document.title = 'Research chat · Cereal'; }, []);
  useEffect(() => {
    try { sessionStorage.setItem(SESSION, JSON.stringify({ wallet: selected, attempt, turns })); } catch { /* read-only browsing still works */ }
  }, [selected, attempt, turns]);
  useEffect(() => {
    setRun(null); setRunError('');
    if (!selected) return;
    let stopped = false, polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const result = await api.run(selected);
        if (!stopped) { setRun(result.run); setRunError(''); }
      } catch (err) { if (!stopped) setRunError(describeError(err)); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(poll, 2500);
    return () => { stopped = true; clearInterval(timer); };
  }, [selected]);

  async function begin(choice?: string, retry?: Attempt) {
    const task = retry?.task ?? prompt.trim();
    if (inFlight.current || !task) return;
    let sent: Attempt = retry ?? { wallet: choice ?? selected ?? '', task, request_id: crypto.randomUUID() };
    let paymentStarted = false;
    inFlight.current = true; setBusy(true); setError('');
    const update = (fields: Partial<SentTurn>) => setTurns(previous => previous.map(t => t.request_id === sent.request_id ? { ...t, ...fields } : t));
    try {
      let retained = turns;
      if (run && record && (!attempt || run.request_id === attempt.request_id)) {
        const priorId = run.request_id ?? run.id;
        const existing = retained.find(t => t.request_id === priorId);
        const prior = { ...existing, wallet: record.id, task: existing?.task ?? run.task ?? record.task, request_id: priorId, result: run };
        retained = [...retained.filter(t => t.request_id !== priorId), prior];
      }
      setTurns([...retained.filter(t => t.request_id !== sent.request_id), sent]);
      setPrompt(''); setAttempt(sent); setClarification(undefined);
      const site = !retry && siteInMessage(task);
      if (site) {  // a web address runs the crawl directly: no AI call
        const pick = (list: ApiRecord[]) => {
          const named = resolveWalletFromPrompt(toWorkspace(list, live.vendors, live.folders), task);
          return { named, wallet: list.find(r => r.id === (named.walletId ?? (named.explicit ? undefined : choice ?? selected))) };
        };
        let { named, wallet } = pick(wallets);
        if (!wallet) ({ named, wallet } = pick((await api.wallets()).filter(usable)));  // the list may not have loaded yet
        if (!wallet) { update({ reply: named.message, uncertain: false }); return; }
        update({ wallet: wallet.id, walletName: wallet.name || wallet.task, crawl: crawlPlan(task, site, sent.request_id) });
        return;
      }
      if (!retry?.runTask) {
        const history = retained.flatMap(t => [
          { role: 'user' as const, content: t.task },
          { role: 'assistant' as const, content: (t.reply ?? JSON.stringify({ summary: t.result?.summary, resources: t.result?.resources }) ?? '').slice(0, 8000) },
        ]).slice(-20);
        const answer = await api.chat({ message: task, selected_wallet: choice ?? selected, history });
        if (answer.action === 'reply' || !answer.wallet_id || !answer.task) {
          update({ reply: answer.reply, uncertain: false }); return;
        }
        sent = { ...sent, wallet: answer.wallet_id, runTask: answer.task };
      }
      const all = await api.wallets();
      const currentWallet = all.find(r => r.id === sent.wallet);
      if (!currentWallet) { update({ reply: 'That wallet is no longer available. Choose an existing wallet in Cereal.' }); return; }
      update(sent); setAttempt(sent); setSelected(sent.wallet); live.upsert(currentWallet);
      if (!usable(currentWallet)) { update({ reply: closedWalletMessage(currentWallet), uncertain: false }); return; }
      // Persist the interpreted purchase and ID before POST. A retry never reinterprets it or pays twice.
      sessionStorage.setItem(SESSION, JSON.stringify({ wallet: sent.wallet, attempt: sent,
        turns: [...retained.filter(t => t.request_id !== sent.request_id), sent] }));
      paymentStarted = true;
      const result = await api.startRun(sent.wallet, { task: sent.runTask!, request_id: sent.request_id, keep_open: true });
      setRun(result.run); await live.refresh();
    } catch (err) {
      const refused = err instanceof ApiError && err.kind === 'refused';
      const reply = refused ? chatRefusal(err.body as Refusal) : paymentStarted
        ? 'I couldn’t confirm the result because the connection to Cereal was interrupted. A payment may still be in progress. Check Cereal, or retry this request to check the same task safely.'
        : 'I couldn’t reach the AI service. No payment was started. Please try your message again.';
      update({ reply, uncertain: paymentStarted && !refused });
    } finally { setBusy(false); inFlight.current = false; }
  }
  function newChat() {
    setSelected(undefined); setAttempt(undefined); setTurns([]); setRun(null); setPrompt(''); setError(''); setClarification(undefined); setMobileNav(false);
  }
  function submit(event: FormEvent) { event.preventDefault(); void begin(); }
  const showRun = run && record && (!attempt || run.request_id === attempt.request_id);
  const transcript = turns.filter(t => !showRun || t.request_id !== run?.request_id);
  useEffect(() => { if (turns.length) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }); }, [turns, run?.status]);

  return <div className="research-chat">
    {mobileNav && <button className="chat-nav-scrim" aria-label="Close chat navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`chat-sidebar ${mobileNav ? 'open' : ''}`} aria-label="Chat navigation">
      <a className="chat-brand" href="/test-chat"><MessageChatCircle /><span>ChatGPT</span><span className="demo-label">Demo</span></a>
      <button className="chat-nav-action" onClick={newChat} disabled={busy}><Plus />New research</button>
      <div className="chat-sidebar-section"><span className="chat-eyebrow">WALLET SESSIONS</span>
        {history.map(r => <button key={r.id} disabled={busy} aria-current={selected === r.id ? 'page' : undefined} onClick={() => { setSelected(r.id); setAttempt(undefined); setTurns([]); setPrompt(''); setError(''); setMobileNav(false); }}><MessageChatCircle /><span>{r.name || r.task}</span>{running(r.run) && <i className="waiting-dot" />}</button>)}
        {!history.length && <p>Your research will appear here.</p>}
      </div>
      <div className="chat-connection"><span className="chat-eyebrow">PAYMENTS VIA CEREAL</span><div><img src="/assets/cereal.svg" alt="" /><span>{hinted?.name || 'Name a wallet in your prompt'}</span></div>
        <p>{hinted ? `${amount(hinted.balance)} available` : `${wallets.length} active wallets connected`}<br />You set the rules in Cereal.</p>
        <a href={walletUrl(hinted?.id)} target="cereal-wallet" rel="noopener">Open Cereal <ArrowUpRight /></a>
      </div>
      <div className="chat-profile"><span>YO</span><div>You<p>Live XRPL testnet</p></div></div>
    </aside>
    <main className="chat-main">
      <header className="chat-header"><div><button className="icon-button chat-mobile-menu" aria-label="Toggle chat navigation" onClick={() => setMobileNav(!mobileNav)}><Menu01 /></button><span>ChatGPT <ChevronDown /></span><span className="chat-model-label">Research chat</span></div><a href={walletUrl(hinted?.id)} target="cereal-wallet" rel="noopener"><ShieldTick />{live.status === 'ready' ? 'Cereal connected' : live.status === 'loading' ? 'Connecting…' : 'Cereal unavailable'}</a></header>
      <div className="chat-scroll" ref={scrollRef}>
        {!!transcript.length && <div className="chat-conversation" aria-label="Conversation">{transcript.map(turn => <div key={turn.request_id}>
          <div className="user-message">{turn.task}</div>
          <section className="assistant-message" aria-label="Assistant response">
            <div className="assistant-heading"><span className="assistant-avatar"><MessageChatCircle /></span><strong>ChatGPT</strong></div>
            {turn.crawl ? <SiteCrawl turn={turn} onUpdate={fields => setTurns(previous => previous.map(t => t.request_id === turn.request_id ? { ...t, ...fields } : t))} /> : turn.result ? <PastResult run={turn.result} /> : <p role="status">{turn.reply ?? 'I’m checking the available sources and your wallet’s payment rules with Cereal…'}</p>}
            {turn.wallet && (turn.reply || turn.result || turn.crawlDone) && <a className="chat-new-run" href={walletUrl(turn.wallet)} target="cereal-wallet" rel="noopener">Review wallet in Cereal <ArrowUpRight /></a>}
            {turn.uncertain && !turn.crawl && <button className="chat-new-run" disabled={busy} onClick={() => void begin(undefined, turn)}>Retry request</button>}
          </section>
        </div>)}</div>}
        {!showRun && !turns.length ? <section className="chat-welcome"><span className="chat-eyebrow">RESEARCH WITH CEREAL</span><h1>Curiosity, with a budget.</h1><p>Name any active Cereal wallet in your prompt.<br />Its existing payment rules apply.</p>
          <div className="chat-wallet-clarification" role="status"><p>{live.status === 'loading' ? 'Connecting to your wallets…' : live.status === 'error' ? 'Wallet connection unavailable.' : clarification?.message ?? (wallets.length ? 'Your live wallets' : 'Create an active wallet in Cereal to begin.')}</p>
            <div className="chat-wallet-choices">{wallets.filter(r => !clarification || clarification.ids.includes(r.id)).map(r => <button key={r.id} disabled={busy || live.status !== 'ready'} onClick={() => {
              if (clarification) void begin(r.id);
              else setPrompt(`Research the XRPL ecosystem. Use my "${r.name || r.task}" wallet for payments.`);
            }}>{r.name || r.task}<small>{amount(r.balance)} available · {r.id.slice(-6)}</small></button>)}</div>
            <button className="chat-new-run" onClick={() => void live.refresh()} disabled={busy}>Refresh wallets</button>
          </div>
          <div className="chat-wallet-clarification"><p>Connected vendor catalog</p><p>{live.vendors.flatMap(v => (v.items ?? []).map(i => `${v.name}: ${i.item} (${amount(i.price)})`)).join(' · ') || 'No catalog loaded yet.'}</p><p className="chat-disclaimer">AI understands your messages and follow-ups. Paid data comes from Cereal’s connected vendors. Reports contain sample data; live web browsing is not connected.</p></div>
        </section> : showRun ? <div className="chat-conversation"><div className="user-message">{turns.find(t => t.request_id === run.request_id)?.task || run!.task || record.task}</div>
          <section className="assistant-message"><div className="assistant-heading"><span className="assistant-avatar"><MessageChatCircle /></span><strong>ChatGPT</strong><span>Cereal task</span></div>
            <p>Using <strong>{record.name || record.task}</strong>. Cereal enforces this wallet’s budget, vendor permissions, expiry, and approval threshold.</p>
            <div className="research-progress"><span><Clock />{active ? 'Cereal is running your task' : `Task ${run.status.replace(/_/g, ' ')}`}</span><span>{amount(record.balance)} available</span></div>
            {active && <p>Payments above the wallet’s threshold require its configured Ledger approval. The wallet stays open for follow-ups. Finish it in Cereal when you’re done; expiry and spending rules still apply.</p>}
            {runError && <p className="chat-error" role="alert">Status unavailable: {runError} Last known status shown.</p>}
            {run.error && <p className="chat-error" role="alert">{run.error}</p>}
            {run.summary && <section className="research-summary"><h2>Cereal’s result</h2><p>{run.summary}</p></section>}
            {!!run.resources?.length && <section className="research-summary" aria-label="Retrieved data"><h2>Retrieved data</h2>{run.resources.map(resource => <div key={resource.resource}><h3>{resource.title}</h3>{resource.sample && <p className="chat-disclaimer">Sample research data</p>}<p>{resource.summary}</p><ul>{resource.findings?.map((finding, i) => <li key={i}>{finding}</li>)}</ul></div>)}</section>}
            {!!plan?.lines?.length && <section className="research-summary"><h2>Purchase plan</h2>{plan.lines.map(line => <div key={line.item}><p>{line.item} · {line.vendor} · {amount(line.price)}</p>{line.rejected?.map((r, i) => <p key={i}>{r.vendor}: skipped because {planReason(r.reason)}.</p>)}</div>)}</section>}
            <section className="source-results" aria-label="Wallet activity"><h2>Wallet activity</h2>{!items.length && <p>No payment activity recorded yet.</p>}{items.map(item => <article className={`source-result ${item.kind === 'payment' ? item.state === 'settled' ? 'paid' : item.state : 'blocked'}`} key={item.key}><div className="source-icon"><Wallet03 /></div><div className="source-body"><div className="source-topline"><strong>{item.kind === 'payment' ? item.merchant : item.payee || 'Cereal'}</strong><span>{item.stateLabel}</span></div><p>{item.kind === 'payment' ? item.title : item.reason}{item.amount ? ` · ${amount(item.amount)}` : ''}</p>{item.link && <a href={item.link} target="_blank" rel="noopener noreferrer">View transaction <ArrowUpRight /></a>}</div></article>)}</section>
            <a className="chat-new-run" href={walletUrl(record.id)} target="cereal-wallet" rel="noopener">View wallet and rules in Cereal <ArrowUpRight /></a>
          </section>
            {!usable(record) && <section className="research-summary" aria-label="Wallet availability"><p>{closedWalletMessage(record)}</p><a className="chat-new-run" href="/" target="cereal-wallet" rel="noopener">Open Cereal to choose or create a wallet <ArrowUpRight /></a></section>}
        </div> : null}
        {(!!turns.length || showRun) && clarification && <div className="chat-conversation"><div className="chat-wallet-clarification" role="status"><p>{clarification.message}</p><div className="chat-wallet-choices">{wallets.filter(r => clarification.ids.includes(r.id)).map(r => <button key={r.id} disabled={busy} onClick={() => void begin(r.id)}>{r.name || r.task}<small>{amount(r.balance)} available · {r.id.slice(-6)}</small></button>)}</div></div></div>}
      </div>
      <footer className="chat-composer">
        {(error || live.error || (!showRun && runError)) && <p className="chat-error" role="alert">{error || live.error || runError}</p>}
        <form onSubmit={submit}><label className="sr-only" htmlFor="live-research-prompt">Research prompt</label><textarea id="live-research-prompt" value={prompt} maxLength={4000} disabled={busy} placeholder={selected ? 'Ask a follow-up, or name another wallet…' : 'Research a topic. Use my “wallet name” wallet for payments.'} rows={3} onChange={e => { setPrompt(e.target.value); setClarification(undefined); setError(''); }} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void begin(); } }} />
          <div className="chat-composer-controls"><span className="research-mode"><Globe01 />Research</span><span className="chat-wallet-select"><Wallet03 />{hinted?.name || 'Wallet named in prompt'}</span><button className="chat-send" aria-label="Start research" disabled={busy || !prompt.trim() || live.status !== 'ready'}><ArrowUp /></button></div>
        </form>
        <div className="chat-composer-note"><span>{active ? 'Task running · You can ask questions while it finishes' : 'Follow-ups use the selected wallet unless you name another'}</span><span>Sending can spend testnet RLUSD through Cereal.</span></div>
      </footer>
    </main>
  </div>;
}
