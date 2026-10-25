import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { flushSync } from 'react-dom';
import { ArrowUp, ChevronDown, ChevronUp, Folder, Home03, Menu01, Plus, Settings01 } from '@untitledui/icons';
import { api, describeError } from './api';
import type { AppActions } from './appActions';
import { ConstraintsDialog } from './components/ConstraintsDialog';
import { FolderDialog } from './components/FolderDialog';
import { FundsDialog } from './components/FundsDialog';
import { NewWalletDialog } from './components/NewWalletDialog';
import { AddSiteDialog } from './components/AddSiteDialog';
import { SiteDetail } from './components/SiteDetail';
import { SitesSection } from './components/SitesSection';
import { SettingsDialog } from './components/SettingsDialog';
import { WalletActions } from './components/WalletActions';
import { WalletDetail } from './components/WalletDetail';
import { FormingWallet } from './components/FormingWallet';
import { WalletOrganism } from './components/WalletOrganism';
import { draftConstraints, draftMissing, parseDraft } from './lib/draftWallet';
import { CORE_ID, HOME_VIEW } from './lib/walletSpheres';
import { formatAmount } from './format';
import { isActive } from './live';
import { isLive } from './mode';
import { loadSession, saveSession, type Session } from './session';
import { useLiveData } from './store';
import { populateMockWallet, type Wallet } from './wallets';
import { useWorkspace } from './workspaceStore';

type Modal = 'wallet' | 'folder' | 'funds' | 'constraints' | 'settings' | 'site' | null;

export default function App() {
  // Live mode never loads or seeds the mock workspace; every wallet comes from the cereal service.
  const { workspace: mockWorkspace, setWorkspace, error: storageError } = useWorkspace(!isLive);
  const query = new URLSearchParams(window.location.search);
  const [selectedId, setSelectedId] = useState(() => query.get('wallet') ?? mockWorkspace.wallets.find(w => !w.archived)?.id);
  const live = useLiveData(isLive, selectedId);
  const workspace = isLive ? live.workspace : mockWorkspace;
  const [activeView, setActiveView] = useState<'home' | 'wallet' | 'site'>(query.has('wallet') ? 'wallet' : 'home');
  const [session, setSessionState] = useState<Session | null>(() => isLive ? loadSession() : null);
  const [selectedSiteId, setSelectedSiteId] = useState<string>();
  const [siteUrl, setSiteUrl] = useState<string>();
  const [expandedFolders, setExpandedFolders] = useState<string[]>(['research-2']);
  const [modal, setModal] = useState<Modal>(query.get('setup') === 'research' || query.get('settings') === 'demo' ? 'settings' : null);
  const [mobileNav, setMobileNav] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [walletDescription, setWalletDescription] = useState('');
  const [rulesSentence, setRulesSentence] = useState('');
  const [showAllWallets, setShowAllWallets] = useState(false);
  const [message, setMessage] = useState('');
  const [promptError, setPromptError] = useState(false);
  const [messageError, setMessageError] = useState(false);
  const [draggingWalletId, setDraggingWalletId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const activeWallets = workspace.wallets.filter(w => !w.archived);
  const runningWallets = activeWallets.filter(isActive);
  const selected = workspace.wallets.find(w => w.id === selectedId);
  const total = activeWallets.reduce((sum, wallet) => sum + wallet.balance, 0);
  const isHome = activeView === 'home';
  // The composer describes a new wallet on Home and on a site's view (a site has no rules to edit); there, and only in
  // live mode, a web address opens Add a site instead.
  const composeNew = isHome || activeView === 'site';
  // Live home lists running wallets first; finished ones (reclaimed, retired, ...) stay one click away.
  const homeWallets = isLive ? runningWallets : activeWallets;
  const homeShown = Math.min(4, homeWallets.length);
  const visibleWallets = isHome ? (showAllWallets ? activeWallets : homeWallets.slice(0, 4)) : activeWallets.filter(wallet => !wallet.folderId);
  const activeNavigation = modal === 'settings' ? 'settings' : activeView;
  // Typing on Home writes a new wallet: the workspace turns blue and the wallet forms (FormingWallet). The input always
  // updates at once; only the switch into and out of the forming view waits for its transition, so no keystroke is lost.
  const [formingShown, setFormingShown] = useState(false);
  const forming = isHome && formingShown;
  const editable = !!selected && !selected.archived && isActive(selected);

  useEffect(() => {
    if (!message || promptError || messageError) return;
    const timer = window.setTimeout(() => setMessage(''), 5000);
    return () => clearTimeout(timer);
  }, [message, promptError, messageError]);

  function notify(text: string, error = false) { setMessage(text); setMessageError(error); }
  /** Page changes fade the old page out, then the new one in (view transitions; see Motion in styles.css). */
  function navigate(update: () => void) {
    if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) { update(); return; }
    document.startViewTransition(() => flushSync(update));
  }
  function selectWallet(id: string) { navigate(() => {
    setSelectedId(id); setActiveView('wallet'); setMobileNav(false);
    setPrompt(''); setPromptError(false); notify('');
    const folderId = workspace.wallets.find(wallet => wallet.id === id)?.folderId;
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
  }); }
  function showWallet(id: string, folderId?: string) { navigate(() => {
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
    setSelectedId(id); setActiveView('wallet'); setMobileNav(false); setPrompt(''); setPromptError(false); setWalletDescription('');
  }); }
  function setSession(next: Session | null) { saveSession(next); setSessionState(next); }
  // The status line is set inside the transition: View Transitions run the update after the caller returns, so a
  // message set before navigating would be cleared by it.
  function openSite(siteId: string, message = '') { navigate(() => {
    setSelectedSiteId(siteId); setActiveView('site'); setMobileNav(false); setPrompt(''); setPromptError(false); notify(message);
  }); }
  function openAddSite(url?: string) { setSiteUrl(url); setModal('site'); }
  function goHome() { navigate(() => {
    setSelectedId(activeWallets[0]?.id); setActiveView('home'); setMobileNav(false);
    setPrompt(''); setPromptError(false); notify('');
  }); }
  const formingTarget = useRef(false);
  useEffect(() => {
    const wanted = isHome && !!prompt.trim();
    // One transition per switch: keystrokes while it is pending must not restart it.
    if (wanted === formingTarget.current) return;
    formingTarget.current = wanted;
    if (isHome) navigate(() => setFormingShown(wanted)); else setFormingShown(false);
  }, [isHome, prompt]);
  function editPrompt(next: string) { setPrompt(next); setPromptError(false); }
  /** Mock: the demo wallet is exactly the draft on screen, funded with its budget. Live: cereal reads the sentence and
   * the owner approves on the Ledger, in the New wallet dialog. */
  async function createFromPrompt() {
    if (isLive) { setWalletDescription(prompt.trim()); setModal('wallet'); return; }
    const draft = parseDraft(prompt), constraints = draftConstraints(draft);
    if (!constraints) {
      setPromptError(true); notify(`Still needed: ${draftMissing(draft).join(', ')}. For example: a budget of $20 over 2 days, only at Apollo.`, true);
      return;
    }
    const id = crypto.randomUUID();
    // Same contract as the New wallet dialog: open the wallet only once the workspace store has saved it.
    const saved = await setWorkspace(previous => ({ ...previous, wallets: [...previous.wallets, populateMockWallet({
      id, name: draft.name ?? 'New wallet', description: prompt.trim(), transactions: [], balance: constraints.spend, archived: false, constraints,
    })] }));
    if (!saved) return;
    showWallet(id); notify('Demo wallet created with mock funds and activity.');
  }
  function updateWallet(id: string, update: Partial<Wallet>) {
    return setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(w => w.id === id ? { ...w, ...update } : w) }));
  }
  function openConstraints() { if (selected) { setRulesSentence(''); setModal('constraints'); } }
  function openFunds() {
    if (!selected || !isActive(selected) || selected.archived) setSelectedId(runningWallets[0]?.id);
    setModal('funds');
  }
  async function toggleArchive() {
    if (!selected) return;
    if (isLive) {
      try {
        const out = await api.updateMeta(selected.id, { archived: !selected.archived });
        live.upsert(out.wallet); void live.refresh(); // re-read: a poll already in flight must not put the old record back
        notify(selected.archived ? `Wallet restored. It is still ${out.wallet.status}.` : 'Wallet archived. Its funds and account are unchanged.'); setModal(null);
      } catch (e) { notify(describeError(e), true); }
      return;
    }
    if (!await updateWallet(selected.id, { archived: !selected.archived })) return;
    if (!selected.archived) setSelectedId(activeWallets.find(w => w.id !== selected.id)?.id);
    notify(selected.archived ? 'Wallet restored.' : 'Wallet archived.'); setModal(null);
  }
  async function moveWallet(id: string, folderId?: string) {
    const wallet = workspace.wallets.find(wallet => wallet.id === id && !wallet.archived);
    const folder = workspace.folders.find(folder => folder.id === folderId);
    if (!wallet || (folderId && !folder)) return;
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
    if (id === selectedId) setActiveView('wallet');
    if (wallet.folderId === folderId) return;
    if (isLive) {
      try {
        const out = await api.updateMeta(id, { folder: folder?.name ?? null });
        live.upsert(out.wallet); void live.refresh(); // re-read: a poll already in flight must not put the old record back
        notify(`Wallet moved to ${folder?.name ?? 'Disposable Wallets'}.`);
      } catch (e) { notify(describeError(e), true); }
      return;
    }
    if (!await setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(wallet => wallet.id === id ? { ...wallet, folderId } : wallet) }))) return;
    setPromptError(false);
    notify(`Wallet moved to ${folder?.name ?? 'Disposable Wallets'}.`);
  }
  function endDrag() { setDraggingWalletId(null); setDropTarget(null); }
  function dropHandlers(folderId?: string) {
    const target = folderId ? `folder:${folderId}` : 'disposable';
    return {
      onDragOver(event: DragEvent<HTMLElement>) {
        if (!draggingWalletId) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        setDropTarget(target);
      },
      onDragLeave(event: DragEvent<HTMLElement>) {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
          setDropTarget(previous => previous === target ? null : previous);
        }
      },
      onDrop(event: DragEvent<HTMLElement>) {
        if (!draggingWalletId) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer.getData('application/x-cereal-wallet') === draggingWalletId) moveWallet(draggingWalletId, folderId);
        endDrag();
      },
    };
  }
  async function applyPrompt(event: FormEvent) {
    event.preventDefault();
    if (composeNew) {
      if (!prompt.trim()) return;
      if (isLive && /^https?:\/\//i.test(prompt.trim())) { openAddSite(prompt.trim()); setPrompt(''); return; }
      void createFromPrompt();
      return;
    }
    if (!selected || !editable) return;
    setRulesSentence(prompt.trim()); setPrompt(''); setPromptError(false); setModal('constraints');
  }
  function walletRow(wallet: Wallet, nested = false) {
    const finished = !isActive(wallet);
    return <button key={wallet.id} data-wallet-id={wallet.id} data-status={wallet.live?.status} title={wallet.live ? `${wallet.name} · ${wallet.live.status}` : undefined}
      className={`wallet-row ${nested ? 'nested' : ''} ${wallet.archived ? 'archived' : ''} ${finished ? 'finished' : ''} ${draggingWalletId === wallet.id ? 'is-dragging' : ''}`}
      aria-label={`Open ${wallet.name}`} aria-current={activeNavigation === 'wallet' && selectedId === wallet.id ? 'true' : undefined}
      draggable={!wallet.archived} onDragStart={event => {
        if (wallet.archived) { event.preventDefault(); return; }
        event.dataTransfer.setData('application/x-cereal-wallet', wallet.id);
        event.dataTransfer.effectAllowed = 'move';
        setDraggingWalletId(wallet.id);
      }} onDragEnd={endDrag}
      onClick={() => selectWallet(wallet.id)}><span className="wallet-dot" /><span>{wallet.name}</span></button>;
  }

  const app: AppActions = {
    workspace, activeWallets, selected, selectedId, setSelectedId, isHome, live, setWorkspace, updateWallet, showWallet,
    moveWallet, toggleArchive, notify, close: () => { setModal(null); setWalletDescription(''); setRulesSentence(''); setSiteUrl(undefined); },
    session, setSession, selectedSiteId: activeView === 'site' ? selectedSiteId : undefined, openSite, openAddSite,
  };
  const liveBanner = isLive && (live.status === 'error'
    ? <p className="live-banner error" role="alert">{live.error ?? 'The cereal service is not reachable.'} Retrying every 5 seconds.</p>
    : live.status === 'loading' ? <p className="live-banner" role="status">Connecting to the cereal service…</p> : null);

  return <div className={`app-shell ${isHome ? 'home-view' : 'wallet-view'} ${forming ? 'is-forming' : ''}`}>
    <header className="mobile-header"><button className="icon-button" aria-label="Toggle navigation" aria-expanded={mobileNav} onClick={() => setMobileNav(!mobileNav)}><Menu01 /></button><span>Cereal</span><span className="mobile-count">{activeWallets.length} wallets</span></header>
    {mobileNav && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? 'is-open' : ''}`} aria-label="Wallet navigation">
      <a href="#" className="brand" onClick={event => { event.preventDefault(); goHome(); }}><img src="/assets/cereal.svg" alt="" width="20" height="20" /><span>Cereal</span></a>
      <nav className="primary-nav" aria-label="Main">
        <button aria-current={activeNavigation === 'home' ? 'page' : undefined} onClick={goHome}><Home03 /><span>Home</span></button>
        <button aria-current={activeNavigation === 'settings' ? 'true' : undefined} onClick={() => setModal('settings')}><Settings01 /><span>Settings</span></button>
      </nav>
      {(workspace.demoPayments ?? []).some(payment => payment.status === 'pending') && <button className="approval-nav" onClick={() => { const payment = workspace.demoPayments?.find(item => item.status === 'pending'); if (payment) selectWallet(payment.walletId); }}>Approval needed <span>{workspace.demoPayments?.filter(item => item.status === 'pending').length}</span></button>}
      <section className="sidebar-section">
        <div className="section-heading muted"><span>Folders</span><button className="icon-button small" aria-label="New folder" onClick={() => setModal('folder')}><Plus /></button></div>
        {workspace.folders.map(folder => {
          const expanded = expandedFolders.includes(folder.id);
          return <div key={folder.id} data-folder-id={folder.id} className={`wallet-drop-zone ${dropTarget === `folder:${folder.id}` ? 'is-drop-target' : ''}`} {...dropHandlers(folder.id)}>
            <button className="folder-row" aria-expanded={expanded} onClick={() => setExpandedFolders(previous => expanded ? previous.filter(id => id !== folder.id) : [...previous, folder.id])}>
              <Folder /><span>{folder.name}</span>{expanded ? <ChevronDown /> : <ChevronUp />}
            </button>
            {expanded && activeWallets.filter(w => w.folderId === folder.id).map(w => walletRow(w, true))}
          </div>;
        })}
      </section>
      <section className={`sidebar-section wallet-drop-zone ${dropTarget === 'disposable' ? 'is-drop-target' : ''}`} data-wallet-group="disposable" aria-labelledby="disposable-heading" {...dropHandlers()}><h2 id="disposable-heading" className="section-heading">Disposable Wallets</h2>
        {visibleWallets.map(w => walletRow(w))}
        {isHome && activeWallets.length > homeShown && <button className="wallet-more" onClick={() => setShowAllWallets(!showAllWallets)}>{showAllWallets ? 'Show fewer' : `+ ${activeWallets.length - homeShown} more`}</button>}
        {!activeWallets.length && (!isLive || live.status === 'ready') && <button className="empty-wallets" onClick={() => setModal('wallet')}>Create your first wallet</button>}
      </section>
      {isLive && <SitesSection app={app} />}
      <section className="sidebar-section"><h2 className="section-heading muted">Archived Wallets</h2>
        {workspace.wallets.filter(w => w.archived).map(w => walletRow(w))}
      </section>
    </aside>

    <main>
      <div className="workspace-content">
      {liveBanner}
      {activeView === 'site' && selectedSiteId ? <SiteDetail app={app} siteId={selectedSiteId} />
      : forming ? <section className="home-stage" aria-label="Wallet home">
        <FormingWallet text={prompt} wallets={activeWallets} totalBalance={total} caption={isLive ? 'New wallet, funded from your main wallet' : 'New demo wallet, funded with demo money'}
          canCreate={!isLive || live.status === 'ready'} onCreate={createFromPrompt} onCancel={() => editPrompt('')} onSelect={selectWallet} />
      </section> : isHome ? <section className="home-stage" aria-label="Wallet home">
        {isLive ? <div className="home-summary">
          <h1>{live.main ? formatAmount(live.main.rlusd) : '—'}</h1>
          <p>Main wallet on XRPL testnet · {runningWallets.length} active {runningWallets.length === 1 ? 'wallet' : 'wallets'}{live.main && Number(live.main.outstanding_budget) > 0 ? ` · ${formatAmount(live.main.outstanding_budget)} out in wallets` : ''}</p>
          <button className="primary-button" disabled={live.status !== 'ready'} onClick={() => { if (runningWallets.length) openFunds(); else { setWalletDescription(''); setModal('wallet'); } }}>{runningWallets.length ? 'Add funds' : 'Create a wallet'}</button>
        </div> : <div className="home-summary">
          <h1>{formatAmount(total)}</h1>
          <p>Total demo balance · {activeWallets.length} active {activeWallets.length === 1 ? 'wallet' : 'wallets'}</p>
          <button className="primary-button" onClick={() => { if (activeWallets.length) setModal('funds'); else { setWalletDescription(''); setModal('wallet'); } }}>{activeWallets.length ? 'Add funds' : 'Create a wallet'}</button>
        </div>}
        <div className="home-illustration organism-frame">
          <WalletOrganism wallets={activeWallets} totalBalance={total} selectedId={CORE_ID} onSelect={selectWallet} onHome={goHome} framed={HOME_VIEW} /></div>
      </section> : selected ? <WalletDetail wallet={selected} onAddFunds={openFunds} onEditConstraints={openConstraints} onRestore={toggleArchive}
          payments={(workspace.demoPayments ?? []).filter(payment => payment.walletId === selected.id)}
          vendors={live.vendors} map={{ wallets: activeWallets, totalBalance: total, onSelect: selectWallet, onHome: goHome }}
          actions={<WalletActions app={app} wallet={selected} />} />
        : <div className="empty-details"><h1>Create a wallet<br />for your next task.</h1><button className="primary-button" onClick={() => setModal('wallet')}>Create a wallet</button></div>}


      </div>
      <footer className="composer">
      <p id="status-message" role={promptError || messageError || storageError ? 'alert' : 'status'} className={`status-message ${promptError || messageError || storageError ? 'error' : ''}`}>{storageError || message}</p>
      <form className="prompt-form" onSubmit={applyPrompt}>
        <input aria-label={composeNew ? 'Describe a new wallet in plain English' : 'Edit wallet spending rules'} aria-invalid={promptError} aria-describedby={promptError ? 'status-message' : undefined}
          placeholder={composeNew ? 'Describe a new wallet in plain English' : selected?.archived ? 'Restore this wallet to edit its rules' : selected && !editable ? 'This wallet is finished; its rules no longer change' : selected ? 'Edit wallet constraints in plain English' : 'Create a wallet to set spending rules'} value={prompt} disabled={!composeNew && !editable}
          onChange={event => editPrompt(event.target.value)} onKeyDown={event => { if (event.key === 'Escape' && forming) editPrompt(''); }} />
        <button className="send-button" aria-label={composeNew ? 'Create wallet from description' : 'Apply wallet constraints'} disabled={!prompt.trim() || (!composeNew && !editable)}><ArrowUp /></button>
      </form>
      </footer>
    </main>

    {modal === 'wallet' && <NewWalletDialog app={app} description={walletDescription} />}
    {modal === 'folder' && <FolderDialog app={app} />}
    {modal === 'funds' && selected && <FundsDialog app={app} />}
    {modal === 'constraints' && selected && <ConstraintsDialog app={app} sentence={rulesSentence || undefined} />}
    {modal === 'settings' && <SettingsDialog app={app} />}
    {modal === 'site' && <AddSiteDialog app={app} url={siteUrl} />}
  </div>;
}
