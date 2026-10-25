import { useEffect, useState, type DragEvent, type FormEvent } from 'react';
import { ArrowUp, ChevronDown, ChevronUp, Folder, Home03, Menu01, Plus, Settings01 } from '@untitledui/icons';
import { api, describeError } from './api';
import type { AppActions } from './appActions';
import { ConstraintsDialog } from './components/ConstraintsDialog';
import { FolderDialog } from './components/FolderDialog';
import { FundsDialog } from './components/FundsDialog';
import { NewWalletDialog } from './components/NewWalletDialog';
import { SettingsDialog } from './components/SettingsDialog';
import { WalletActions } from './components/WalletActions';
import { WalletDetail } from './components/WalletDetail';
import { formatAmount } from './format';
import { isActive } from './live';
import { isLive } from './mode';
import { useLiveData } from './store';
import { loadWorkspace, parseConstraints, STORAGE_KEY, type Wallet, type Workspace } from './wallets';

type Modal = 'wallet' | 'folder' | 'funds' | 'constraints' | 'settings' | null;
const emptyWorkspace: Workspace = { wallets: [], folders: [] };

export default function App() {
  // Live mode never loads or seeds the mock workspace; every wallet comes from the cereal service.
  const [mockWorkspace, setWorkspace] = useState<Workspace>(() => isLive ? emptyWorkspace : loadWorkspace());
  const [selectedId, setSelectedId] = useState(() => mockWorkspace.wallets.find(w => !w.archived)?.id);
  const live = useLiveData(isLive, selectedId);
  const workspace = isLive ? live.workspace : mockWorkspace;
  const [activeView, setActiveView] = useState<'home' | 'wallet'>('home');
  const [expandedFolders, setExpandedFolders] = useState<string[]>(['research-2']);
  const [modal, setModal] = useState<Modal>(null);
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
  // Live home lists running wallets first; finished ones (reclaimed, retired, ...) stay one click away.
  const homeWallets = isLive ? runningWallets : activeWallets;
  const homeShown = Math.min(4, homeWallets.length);
  const visibleWallets = isHome ? (showAllWallets ? activeWallets : homeWallets.slice(0, 4)) : activeWallets.filter(wallet => !wallet.folderId);
  const activeNavigation = modal === 'wallet' ? 'new-wallet' : modal === 'settings' ? 'settings' : activeView;
  const editable = !!selected && !selected.archived && isActive(selected);

  useEffect(() => {
    if (isLive) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(mockWorkspace)); }
    catch { setMessage('Changes are available for this session. Browser storage is unavailable.'); }
  }, [mockWorkspace]);
  useEffect(() => {
    if (!message || promptError || messageError) return;
    const timer = window.setTimeout(() => setMessage(''), 5000);
    return () => clearTimeout(timer);
  }, [message, promptError, messageError]);

  function notify(text: string, error = false) { setMessage(text); setMessageError(error); }
  function selectWallet(id: string) {
    setSelectedId(id); setActiveView('wallet'); setMobileNav(false);
    setPrompt(''); setPromptError(false); notify('');
    const folderId = workspace.wallets.find(wallet => wallet.id === id)?.folderId;
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
  }
  function showWallet(id: string, folderId?: string) {
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
    setSelectedId(id); setActiveView('wallet'); setMobileNav(false); setPrompt(''); setPromptError(false); setWalletDescription('');
  }
  function goHome() {
    setSelectedId(activeWallets[0]?.id); setActiveView('home'); setMobileNav(false);
    setPrompt(''); setPromptError(false); notify('');
  }
  function updateWallet(id: string, update: Partial<Wallet>) {
    setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(w => w.id === id ? { ...w, ...update } : w) }));
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
    updateWallet(selected.id, { archived: !selected.archived });
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
    setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(wallet => wallet.id === id ? { ...wallet, folderId } : wallet) }));
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
  function applyPrompt(event: FormEvent) {
    event.preventDefault();
    if (isHome) {
      if (!prompt.trim()) return;
      setWalletDescription(prompt.trim()); setModal('wallet');
      return;
    }
    if (!selected || !editable) return;
    if (isLive) { setRulesSentence(prompt.trim()); setPrompt(''); setModal('constraints'); return; }
    const constraints = parseConstraints(prompt);
    if (!constraints) {
      setPromptError(true);
      notify('Try: Spend up to $20 over 2 days, only at HubSpot, Clearbit and Apollo. Ask me above $5. Sweep back when done.');
      return;
    }
    updateWallet(selected.id, { constraints }); setPrompt(''); setPromptError(false); notify('Demo wallet constraints updated.');
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
    moveWallet, toggleArchive, notify, close: () => { setModal(null); setWalletDescription(''); setRulesSentence(''); },
  };
  const liveBanner = isLive && (live.status === 'error'
    ? <p className="live-banner error" role="alert">{live.error ?? 'The cereal service is not reachable.'} Retrying every 5 seconds.</p>
    : live.status === 'loading' ? <p className="live-banner" role="status">Connecting to the cereal service…</p> : null);

  return <div className={`app-shell ${isHome ? 'home-view' : 'wallet-view'}`}>
    <header className="mobile-header"><button className="icon-button" aria-label="Toggle navigation" aria-expanded={mobileNav} onClick={() => setMobileNav(!mobileNav)}><Menu01 /></button><span>Cereal</span><span className="mobile-count">{activeWallets.length} wallets</span></header>
    {mobileNav && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? 'is-open' : ''}`} aria-label="Wallet navigation">
      <a href="#" className="brand" onClick={event => { event.preventDefault(); goHome(); }}><img src="/assets/cereal.svg" alt="" width="20" height="20" /><span>Cereal</span></a>
      <nav className="primary-nav" aria-label="Main">
        <button aria-current={activeNavigation === 'home' ? 'page' : undefined} onClick={goHome}><Home03 /><span>Home</span></button>
        <button aria-current={activeNavigation === 'settings' ? 'true' : undefined} onClick={() => setModal('settings')}><Settings01 /><span>Settings</span></button>
        <button aria-current={activeNavigation === 'new-wallet' ? 'true' : undefined} onClick={() => { setWalletDescription(''); setModal('wallet'); }}><Plus /><span>New Wallet</span></button>
      </nav>
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
      <section className={`sidebar-section wallet-drop-zone ${dropTarget === 'disposable' ? 'is-drop-target' : ''}`} data-wallet-group="disposable" aria-labelledby="disposable-heading" {...dropHandlers()}><h2 id="disposable-heading" className="section-heading">{isHome ? 'Active Wallets' : 'Disposable Wallets'}</h2>
        {visibleWallets.map(w => walletRow(w))}
        {isHome && activeWallets.length > homeShown && <button className="wallet-more" onClick={() => setShowAllWallets(!showAllWallets)}>{showAllWallets ? 'Show fewer' : `+ ${activeWallets.length - homeShown} more`}</button>}
        {!activeWallets.length && (!isLive || live.status === 'ready') && <button className="empty-wallets" onClick={() => setModal('wallet')}>Create your first wallet</button>}
      </section>
      <section className="sidebar-section"><h2 className="section-heading muted">Archived Wallets</h2>
        {workspace.wallets.filter(w => w.archived).map(w => walletRow(w))}
      </section>
    </aside>

    <main>
      <div className="workspace-content">
      {liveBanner}
      {isHome ? <section className="home-stage" aria-label="Wallet home">
        {isLive ? <div className="home-summary">
          <h1>{live.main ? formatAmount(live.main.rlusd) : '—'}</h1>
          <p>Main wallet on XRPL testnet · {runningWallets.length} active {runningWallets.length === 1 ? 'wallet' : 'wallets'}{live.main && Number(live.main.outstanding_budget) > 0 ? ` · ${formatAmount(live.main.outstanding_budget)} out in wallets` : ''}</p>
          <button className="primary-button" disabled={live.status !== 'ready'} onClick={() => { if (runningWallets.length) openFunds(); else { setWalletDescription(''); setModal('wallet'); } }}>{runningWallets.length ? 'Add funds' : 'Create a wallet'}</button>
        </div> : <div className="home-summary">
          <h1>{formatAmount(total)}</h1>
          <p>Total demo balance · {activeWallets.length} active {activeWallets.length === 1 ? 'wallet' : 'wallets'}</p>
          <button className="primary-button" onClick={() => { if (activeWallets.length) setModal('funds'); else { setWalletDescription(''); setModal('wallet'); } }}>{activeWallets.length ? 'Add funds' : 'Create a wallet'}</button>
        </div>}
        <div className="home-illustration"><img src="/assets/home-organism.svg" width="640" height="620" alt="" /></div>
      </section> : selected ? <WalletDetail wallet={selected} onAddFunds={openFunds} onEditConstraints={openConstraints} onRestore={toggleArchive}
          actions={<WalletActions app={app} wallet={selected} />} />
        : <div className="empty-details"><h1>Create a wallet<br />for your next task.</h1><button className="primary-button" onClick={() => setModal('wallet')}>Create a wallet</button></div>}


      </div>
      <footer className="composer">
      <p id="status-message" role={promptError || messageError ? 'alert' : 'status'} className={`status-message ${promptError || messageError ? 'error' : ''}`}>{message}</p>
      <form className="prompt-form" onSubmit={applyPrompt}>
        <input aria-label={isHome ? 'Describe a new wallet in plain English' : 'Edit wallet spending rules'} aria-invalid={promptError} aria-describedby={promptError ? 'status-message' : undefined}
          placeholder={isHome ? 'Describe a new wallet in plain English' : selected?.archived ? 'Restore this wallet to edit its rules' : selected && !editable ? 'This wallet is finished; its rules no longer change' : selected ? 'Edit wallet constraints in plain English' : 'Create a wallet to set spending rules'} value={prompt} disabled={!isHome && !editable}
          onChange={event => { setPrompt(event.target.value); setPromptError(false); }} />
        <button className="send-button" aria-label={isHome ? 'Create wallet from description' : 'Apply wallet constraints'} disabled={!prompt.trim() || (!isHome && !editable)}><ArrowUp /></button>
      </form>
      </footer>
    </main>

    {modal === 'wallet' && <NewWalletDialog app={app} description={walletDescription} />}
    {modal === 'folder' && <FolderDialog app={app} />}
    {modal === 'funds' && selected && <FundsDialog app={app} />}
    {modal === 'constraints' && selected && <ConstraintsDialog app={app} sentence={rulesSentence || undefined} />}
    {modal === 'settings' && <SettingsDialog app={app} />}
  </div>;
}
