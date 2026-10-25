import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowUp, ArrowUpRight, CheckCircle, ChevronDown, Clock, FileSearch02, Globe01, Menu01, MessageChatCircle, Plus, SearchLg, ShieldTick, Stop, Wallet03, XCircle } from '@untitledui/icons';
import { CHAT_PATH, isTestEnvironment } from './mode';
import { useWorkspace, mutateWorkspace } from './workspaceStore';
import { cancelResearch, money, RESEARCH_PROMPT, researchSources, spending, startResearch, resolveWalletFromPrompt, walletHref, type DemoPayment, type ResearchRun } from './researchDemo';

function SourceResult({ index, payment, active }: { index: number; payment?: DemoPayment; active: boolean }) {
  const source = researchSources[index];
  const status = payment?.status ?? (active ? 'reading' : 'free');
  return <article className={`source-result ${status}`}>
    <div className="source-icon">{status === 'blocked' || status === 'denied' || status === 'cancelled' ? <XCircle /> : status === 'pending' ? <Clock /> : source.amount === 0 ? <Globe01 /> : <FileSearch02 />}</div>
    <div className="source-body"><div className="source-topline"><span>{source.name}</span><span className={`source-state ${status}`}>{status === 'reading' ? 'Reading' : status === 'free' ? 'Public source' : status === 'paid' ? `Paid ${money(source.amount)}` : status === 'pending' ? 'Waiting for you' : status === 'denied' ? 'Payment denied' : status === 'cancelled' ? 'Cancelled' : 'Payment blocked'}</span></div>
      <h3>{source.title}</h3><p>{payment ? payment.reason : active ? 'Reviewing this public source. No wallet access needed.' : source.detail}</p>
      <span className="source-domain">{new URL(source.url).hostname}{source.amount > 0 ? ' · Fictional demo source' : ' · Simulated visit'}</span>
    </div>
  </article>;
}

function ResearchSummary({ run, payments }: { run: ResearchRun; payments: DemoPayment[] }) {
  const paid = payments.filter(payment => payment.status === 'paid');
  const total = paid.reduce((sum, payment) => sum + Math.round(payment.amount * 100), 0) / 100;
  const hasFunding = paid.some(payment => payment.sourceId === 'funding');
  const hasLandscape = paid.some(payment => payment.sourceId === 'landscape');
  const hasIndex = paid.some(payment => payment.sourceId === 'index');
  return <section className="research-summary" aria-label="Research summary">
    <span className="chat-eyebrow">{run.status === 'cancelled' ? 'RESEARCH STOPPED' : 'RESEARCH COMPLETE'}</span>
    <h2>{run.status === 'cancelled' ? 'Your progress is saved.' : 'Your XRPL research brief is ready.'}</h2>
    <p>{run.status === 'cancelled' ? 'Pending payment requests were cancelled. Completed demo payments remain in Cereal’s activity.' : 'I followed your Cereal wallet’s decisions and continued with the sources I could access.'}</p>
    {run.status === 'complete' && <div className="report-sections">
      <div><h3>Product & documentation</h3><p>The scripted research covers XRPL architecture, payment capabilities, tokenization, and developer documentation.{hasLandscape ? ' The Ledger Lens product landscape was unlocked.' : ' The paid product landscape was unavailable; coverage is limited to the public-source steps.'}</p></div>
      <div><h3>Founders & funding</h3><p>{hasFunding ? 'The Venture Atlas founders and funding report was unlocked with Cereal’s permission. Its demo coverage includes team profiles, fundraising timelines, and investor references.' : 'The premium founders and funding report was not purchased. I left that section incomplete rather than inventing funding details.'}</p></div>
      <div><h3>Source cross-check</h3><p>{hasIndex ? 'The Open Ledger Index directory was unlocked to cross-check project websites and company profiles.' : 'The paid directory was not purchased. A full source cross-check remains incomplete.'}</p></div>
    </div>}
    <div className="report-totals"><div><strong>{money(total)}</strong><span>Demo spend</span></div><div><strong>{paid.length}</strong><span>Paid sources</span></div><div><strong>{payments.filter(payment => payment.status !== 'paid').length}</strong><span>Skipped payments</span></div></div>
    <p className="chat-disclaimer">Scripted demonstration. Visits, source contents, risk signals, and payments are simulated. This is a coverage brief, not verified investment research.</p>
  </section>;
}

const RUN_STORAGE_KEY = isTestEnvironment ? 'cereal-test-chat-run' : 'cereal-chat-run';

export default function ResearchChat() {
  const { workspace, error: storageError } = useWorkspace();
  const query = new URLSearchParams(window.location.search);
  const wallets = workspace.wallets.filter(wallet => !wallet.archived);
  const [clarification, setClarification] = useState<{ message: string; candidates: string[] } | null>(null);
  const [runId, setRunId] = useState<string | null>(() => {
    try { return query.get('run') ?? sessionStorage.getItem(RUN_STORAGE_KEY); } catch { return query.get('run'); }
  });
  const [prompt, setPrompt] = useState(() => workspace.researchRuns?.some(item => item.id === runId) ? '' : RESEARCH_PROMPT);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const run = workspace.researchRuns?.find(item => item.id === runId);
  const resolution = resolveWalletFromPrompt(workspace, prompt);
  const wallet = workspace.wallets.find(item => item.id === (run?.walletId ?? resolution.walletId));
  const payments = (workspace.demoPayments ?? []).filter(payment => payment.runId === run?.id);
  const waiting = payments.find(payment => payment.status === 'pending');
  const active = run?.status === 'running' || run?.status === 'waiting';
  const history = [...(workspace.researchRuns ?? [])].reverse();

  useEffect(() => {
    if (runId && !workspace.researchRuns?.some(item => item.id === runId)) { setRunId(null); setPrompt(RESEARCH_PROMPT); }
  }, [runId, workspace.researchRuns]);
  useEffect(() => { document.title = 'Research chat · Cereal demo'; }, []);
  useEffect(() => {
    try {
      if (runId) sessionStorage.setItem(RUN_STORAGE_KEY, runId);
      else sessionStorage.removeItem(RUN_STORAGE_KEY);
    } catch { /* wallet storage reports persistence errors separately */ }
  }, [runId]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'auto' });
  }, [run?.cursor, run?.status, payments.length]);

  async function begin(walletChoice?: string) {
    if (busy || active) return;
    setBusy(true); setError('');
    try {
      const result = await mutateWorkspace(state => {
        const match = resolveWalletFromPrompt(state, prompt);
        const id = walletChoice && match.candidates.some(candidate => candidate.id === walletChoice) ? walletChoice : match.walletId;
        if (!id) return { clarification: { message: match.message, candidates: match.candidates.map(candidate => candidate.id) } };
        return { id: startResearch(state, id, prompt) };
      });
      if (result.id) { setRunId(result.id); setPrompt(''); setClarification(null); }
      else setClarification(result.clarification!);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to start research.'); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void begin(); }
  function newChat() { setRunId(null); setPrompt(RESEARCH_PROMPT); setError(''); setClarification(null); setMobileNav(false); }
  const displayedSources = run ? researchSources.filter((_, index) => index < run.cursor || (index === run.cursor && (active || payments.some(payment => payment.sourceId === researchSources[index].id)))) : [];

  return <div className="research-chat">
    {mobileNav && <button className="chat-nav-scrim" aria-label="Close chat navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`chat-sidebar ${mobileNav ? 'open' : ''}`} aria-label="Chat navigation">
      <a className="chat-brand" href={CHAT_PATH}><MessageChatCircle /><span>ChatGPT</span><span className="demo-label">Demo</span></a>
      <button className="chat-nav-action" onClick={newChat} disabled={active}><Plus />New research</button>
      <div className="chat-sidebar-section"><span className="chat-eyebrow">YOUR CHATS</span>
        {history.length ? history.map(item => <button key={item.id} aria-current={item.id === run?.id ? 'page' : undefined} onClick={() => { setRunId(item.id); setPrompt(''); setMobileNav(false); }}><MessageChatCircle /><span>{item.prompt}</span>{item.status === 'waiting' && <i className="waiting-dot" />}</button>) : <p>Your research will appear here.</p>}
      </div>
      <div className="chat-connection"><span className="chat-eyebrow">PAYMENTS VIA CEREAL</span><div><img src="/assets/cereal.svg" alt="" /><span>{wallet?.name ?? 'Name a wallet in your prompt'}</span></div><p>You set the rules in Cereal.<br />Your assistant follows them.</p>
        <a href={walletHref(wallet?.id)} target="cereal-wallet" rel="noopener">Open Cereal <ArrowUpRight /></a>
      </div>
      <div className="chat-profile"><span>YO</span><div>You<p>Local demo workspace</p></div></div>
    </aside>
    <main className="chat-main">
      <header className="chat-header"><div><button className="icon-button chat-mobile-menu" aria-label="Toggle chat navigation" onClick={() => setMobileNav(!mobileNav)}><Menu01 /></button><span>ChatGPT <ChevronDown /></span><span className="chat-model-label">Research demo</span></div><a href={walletHref(wallet?.id)} target="cereal-wallet" rel="noopener"><ShieldTick />Cereal protected</a></header>
      <div className="chat-scroll" ref={scrollRef}>
        {!run ? <section className="chat-welcome"><div className="chat-welcome-icon"><SearchLg /></div><span className="chat-eyebrow">DEEP RESEARCH</span><h1>Curiosity, with a budget.</h1><p>Explore the XRPL ecosystem.<br />Let Cereal take care of the payments.</p>
          <button className="research-suggestion" onClick={() => setPrompt(RESEARCH_PROMPT)}><Globe01 /><span>Research the XRPL ecosystem<small>Documentation, founders, products & funding</small></span><ArrowUpRight /></button>
          {wallet?.demoClosedAt && <div className="chat-setup"><Wallet03 /><div><h2>This wallet’s research is finished</h2><p>Cereal returned its remaining demo funds. Reset this session’s demo activity in Cereal Settings to run the presentation again.</p><a href={walletHref(wallet.id)} target="cereal-wallet" rel="noopener">Open Cereal <ArrowUpRight /></a></div></div>}
          {!wallets.length && <div className="chat-setup"><Wallet03 /><div><h2>Start with your wallet in Cereal</h2><p>Create a wallet in Cereal and name it in your research prompt.</p><a href={walletHref()} target="cereal-wallet" rel="noopener">Open Cereal <ArrowUpRight /></a></div></div>}
          {clarification && <div className="chat-wallet-clarification" role="status"><p>{clarification.message}</p><div className="chat-wallet-choices">{clarification.candidates.map(id => {
            const candidate = workspace.wallets.find(item => item.id === id); if (!candidate) return null;
            return <button key={id} disabled={busy} onClick={() => void begin(id)}>{candidate.name}<small>{workspace.folders.find(folder => folder.id === candidate.folderId)?.name ?? 'Disposable wallets'} · {money(candidate.balance)} available · {id.slice(-6)}</small></button>;
          })}</div></div>}
        </section> : <div className="chat-conversation">
          <div className="user-message">{run.prompt}</div>
          <section className="assistant-message"><div className="assistant-heading"><span className="assistant-avatar"><MessageChatCircle /></span><strong>ChatGPT</strong><span>Deep research</span></div>
            <p>I’ll explore the documentation, product landscape, founders, and funding. I’ll ask Cereal to pay only when a source requires it, using the rules already set on your {wallet?.name ?? 'research'} wallet.</p>
            <div className="research-progress"><span>{run.status === 'waiting' ? <Clock /> : run.status === 'complete' ? <CheckCircle /> : <SearchLg />}{run.status === 'waiting' ? 'Waiting for a payment decision' : run.status === 'complete' ? 'Research complete' : run.status === 'cancelled' ? 'Research stopped' : 'Researching sources'}</span><span>{run.cursor} / {researchSources.length} sources</span></div>
            <div className="source-results">{displayedSources.map(source => { const index = researchSources.indexOf(source); return <SourceResult key={source.id} index={index} payment={payments.find(payment => payment.sourceId === source.id)} active={index === run.cursor && active} />; })}</div>
            {waiting && <div className="chat-approval" role="status"><div><Clock /><strong>Cereal needs your permission</strong></div><p>{waiting.merchant} requires {money(waiting.amount)}. Your research will resume after you approve or deny this payment in Cereal.</p><a href={walletHref(run.walletId)} target="cereal-wallet" rel="noopener">Review payment in Cereal <ArrowUpRight /></a><span>This payment has not been made.</span></div>}
            {(run.status === 'complete' || run.status === 'cancelled') && <><ResearchSummary run={run} payments={payments} /><button className="chat-new-run" onClick={newChat}><Plus />Start another research session</button></>}
          </section>
        </div>}
      </div>
      <footer className="chat-composer">
        {(error || storageError) && <p className="chat-error" role="alert">{error || storageError}</p>}
        <form onSubmit={submit}><label className="sr-only" htmlFor="research-prompt">Research prompt</label><textarea id="research-prompt" value={prompt} maxLength={4000} disabled={!!run} placeholder={active ? 'Research is in progress…' : run ? 'Start another session to research again' : 'Ask anything about the XRPL ecosystem'} rows={3} onChange={event => { setPrompt(event.target.value); setClarification(null); setError(''); }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!run) void submit(event); } }} />
          <div className="chat-composer-controls"><span className="research-mode"><Globe01 />Deep research</span><span className="chat-wallet-select" aria-label="Payment wallet"><Wallet03 />{wallet?.name ?? 'Wallet named in prompt'}</span>
            {active ? <button type="button" className="chat-send" aria-label="Stop research" disabled={busy} onClick={async () => { setBusy(true); try { await mutateWorkspace(state => cancelResearch(state, run.id)); } catch (err) { setError(err instanceof Error ? err.message : 'Could not stop research.'); } finally { setBusy(false); } }}><Stop /></button> : <button className="chat-send" aria-label="Start research" disabled={busy || !!run || !prompt.trim() || !wallets.length}><ArrowUp /></button>}
          </div>
        </form>
        <div className="chat-composer-note"><span>{wallet ? `${money(Math.max(0, wallet.constraints.spend - spending(wallet)))} budget remaining · Rules managed in Cereal` : 'Name an existing Cereal wallet in your prompt.'}</span><span>Demo · No real browsing or payments</span></div>
      </footer>
    </main>
  </div>;
}
