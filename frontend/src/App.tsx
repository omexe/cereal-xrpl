import { useEffect, useState, type DragEvent, type FormEvent } from 'react';
import { ArrowUp, ChevronDown, ChevronUp, Folder, Home03, Menu01, Plus, Settings01 } from '@untitledui/icons';
import { Dialog } from './components/Dialog';
import { WalletDetail } from './components/WalletDetail';
import { defaultConstraints, loadWorkspace, populateMockWallet, parseConstraints, STORAGE_KEY, type Constraints, type Wallet } from './wallets';

type Modal = 'wallet' | 'folder' | 'funds' | 'constraints' | 'settings' | null;
const money = (amount: number) => `$${amount.toFixed(2)}`;

export default function App() {
  const [workspace, setWorkspace] = useState(loadWorkspace);
  const [selectedId, setSelectedId] = useState(() => workspace.wallets.find(w => !w.archived)?.id);
  const [activeView, setActiveView] = useState<'home' | 'wallet'>('home');
  const [expandedFolders, setExpandedFolders] = useState<string[]>(['research-2']);
  const [modal, setModal] = useState<Modal>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [walletDescription, setWalletDescription] = useState('');
  const [showAllWallets, setShowAllWallets] = useState(false);
  const [message, setMessage] = useState('');
  const [promptError, setPromptError] = useState(false);
  const [draftConstraints, setDraftConstraints] = useState<Constraints>(defaultConstraints);
  const [draggingWalletId, setDraggingWalletId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const activeWallets = workspace.wallets.filter(w => !w.archived);
  const selected = workspace.wallets.find(w => w.id === selectedId);
  const total = activeWallets.reduce((sum, wallet) => sum + wallet.balance, 0);
  const isHome = activeView === 'home';
  const visibleWallets = isHome ? (showAllWallets ? activeWallets : activeWallets.slice(0, 4)) : activeWallets.filter(wallet => !wallet.folderId);
  const activeNavigation = modal === 'wallet' ? 'new-wallet' : modal === 'settings' ? 'settings' : activeView;

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace)); }
    catch { setMessage('Changes are available for this session. Browser storage is unavailable.'); }
  }, [workspace]);
  useEffect(() => {
    if (!message || promptError) return;
    const timer = window.setTimeout(() => setMessage(''), 5000);
    return () => clearTimeout(timer);
  }, [message, promptError]);

  function selectWallet(id: string) {
    setSelectedId(id); setActiveView('wallet'); setMobileNav(false);
    setPrompt(''); setPromptError(false); setMessage('');
    const folderId = workspace.wallets.find(wallet => wallet.id === id)?.folderId;
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
  }
  function goHome() {
    setSelectedId(activeWallets[0]?.id); setActiveView('home'); setMobileNav(false);
    setPrompt(''); setPromptError(false); setMessage('');
  }
  function updateSelected(update: Partial<Wallet>) {
    setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(w => w.id === selectedId ? { ...w, ...update } : w) }));
  }
  function openConstraints() { if (selected) { setDraftConstraints({ ...selected.constraints }); setModal('constraints'); } }
  function createWallet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name')).trim();
    if (!name) return;
    const id = crypto.randomUUID();
    const folderId = String(data.get('folder') || '');
    setWorkspace(previous => ({ ...previous, wallets: [...previous.wallets, populateMockWallet({
      id, name, description: String(data.get('description') || '').trim(), transactions: [], balance: 0, archived: false, folderId: folderId || undefined,
      constraints: { ...defaultConstraints, merchants: [...defaultConstraints.merchants] },
    })] }));
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
    setSelectedId(id); setActiveView('wallet'); setModal(null); setMobileNav(false); setPrompt(''); setWalletDescription(''); setMessage('Demo wallet created with mock funds and activity.');
  }
  function toggleArchive() {
    if (!selected) return;
    updateSelected({ archived: !selected.archived });
    if (!selected.archived) setSelectedId(activeWallets.find(w => w.id !== selected.id)?.id);
    setMessage(selected.archived ? 'Wallet restored.' : 'Wallet archived.'); setModal(null);
  }
  function moveWallet(id: string, folderId?: string) {
    const wallet = workspace.wallets.find(wallet => wallet.id === id && !wallet.archived);
    const folder = workspace.folders.find(folder => folder.id === folderId);
    if (!wallet || (folderId && !folder)) return;
    if (folderId) setExpandedFolders(previous => [...new Set([...previous, folderId])]);
    if (id === selectedId) setActiveView('wallet');
    if (wallet.folderId === folderId) return;
    setWorkspace(previous => ({ ...previous, wallets: previous.wallets.map(wallet => wallet.id === id ? { ...wallet, folderId } : wallet) }));
    setPromptError(false);
    setMessage(`Wallet moved to ${folder?.name ?? 'Disposable Wallets'}.`);
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
    if (!selected || selected.archived) return;
    const constraints = parseConstraints(prompt);
    if (!constraints) {
      setPromptError(true);
      setMessage('Try: Spend up to $20 over 2 days, only at HubSpot, Clearbit and Apollo. Ask me above $5. Sweep back when done.');
      return;
    }
    updateSelected({ constraints }); setPrompt(''); setPromptError(false); setMessage('Demo wallet constraints updated.');
  }
  function walletRow(wallet: Wallet, nested = false) {
    return <button key={wallet.id} data-wallet-id={wallet.id} className={`wallet-row ${nested ? 'nested' : ''} ${wallet.archived ? 'archived' : ''} ${draggingWalletId === wallet.id ? 'is-dragging' : ''}`}
      aria-label={`Open ${wallet.name}`} aria-current={activeNavigation === 'wallet' && selectedId === wallet.id ? 'true' : undefined}
      draggable={!wallet.archived} onDragStart={event => {
        if (wallet.archived) { event.preventDefault(); return; }
        event.dataTransfer.setData('application/x-cereal-wallet', wallet.id);
        event.dataTransfer.effectAllowed = 'move';
        setDraggingWalletId(wallet.id);
      }} onDragEnd={endDrag}
      onClick={() => selectWallet(wallet.id)}><span className="wallet-dot" /><span>{wallet.name}</span></button>;
  }

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
        {isHome && activeWallets.length > 4 && <button className="wallet-more" onClick={() => setShowAllWallets(!showAllWallets)}>{showAllWallets ? 'Show fewer' : `+ ${activeWallets.length - 4} more`}</button>}
        {!activeWallets.length && <button className="empty-wallets" onClick={() => setModal('wallet')}>Create your first wallet</button>}
      </section>
      <section className="sidebar-section"><h2 className="section-heading muted">Archived Wallets</h2>
        {workspace.wallets.filter(w => w.archived).map(w => walletRow(w))}
      </section>
    </aside>

    <main>
      <div className="workspace-content">
      {isHome ? <section className="home-stage" aria-label="Wallet home">
        <div className="home-summary">
          <h1>{money(total)}</h1>
          <p>Total demo balance · {activeWallets.length} active {activeWallets.length === 1 ? 'wallet' : 'wallets'}</p>
          <button className="primary-button" onClick={() => { if (activeWallets.length) setModal('funds'); else { setWalletDescription(''); setModal('wallet'); } }}>{activeWallets.length ? 'Add funds' : 'Create a wallet'}</button>
        </div>
        <div className="home-illustration"><img src="/assets/home-organism.svg" width="640" height="620" alt="" /></div>
      </section> : selected ? <WalletDetail wallet={selected} onAddFunds={() => setModal('funds')} onEditConstraints={openConstraints} onRestore={toggleArchive} />
        : <div className="empty-details"><h1>Create a wallet<br />for your next task.</h1><button className="primary-button" onClick={() => setModal('wallet')}>Create a wallet</button></div>}


      </div>
      <footer className="composer">
      <p id="status-message" role={promptError ? 'alert' : 'status'} className={`status-message ${promptError ? 'error' : ''}`}>{message}</p>
      <form className="prompt-form" onSubmit={applyPrompt}>
        <input aria-label={isHome ? 'Describe a new wallet in plain English' : 'Edit wallet spending rules'} aria-invalid={promptError} aria-describedby={promptError ? 'status-message' : undefined}
          placeholder={isHome ? 'Describe a new wallet in plain English' : selected?.archived ? 'Restore this wallet to edit its rules' : selected ? 'Edit wallet constraints in plain English' : 'Create a wallet to set spending rules'} value={prompt} disabled={!isHome && (!selected || selected.archived)}
          onChange={event => { setPrompt(event.target.value); setPromptError(false); }} />
        <button className="send-button" aria-label={isHome ? 'Create wallet from description' : 'Apply wallet constraints'} disabled={!prompt.trim() || (!isHome && (!selected || selected.archived))}><ArrowUp /></button>
      </form>
      </footer>
    </main>

    {modal === 'wallet' && <Dialog title="New wallet" onClose={() => setModal(null)}><form onSubmit={createWallet}>
      <p className="dialog-description">Create a wallet for an agent task. Mock funds, spending rules, and sample activity are included.</p>
      <label>Wallet name<input name="name" required maxLength={80} placeholder="e.g. Lead enrichment" autoFocus /></label>
      <label>Task description<textarea name="description" maxLength={1000} defaultValue={walletDescription} placeholder="What should this wallet be used for?" /></label>
      <label>Folder<select name="folder"><option value="">Disposable wallets</option>{workspace.folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
      <p className="demo-note">Demo wallet · stored in this browser · no on-chain account is created.</p>
      <button className="primary-button form-submit">Create wallet</button>
    </form></Dialog>}
    {modal === 'folder' && <Dialog title="New folder" onClose={() => setModal(null)}><form onSubmit={event => {
      event.preventDefault(); const name = String(new FormData(event.currentTarget).get('name')).trim(); if (!name) return;
      setWorkspace(previous => ({ ...previous, folders: [...previous.folders, { id: crypto.randomUUID(), name }] })); setModal(null);
    }}><label>Folder name<input name="name" required maxLength={60} autoFocus /></label><button className="primary-button form-submit">Create folder</button></form></Dialog>}
    {modal === 'funds' && selected && <Dialog title="Add demo funds" onClose={() => setModal(null)}><form onSubmit={event => {
      event.preventDefault(); const amount = Number(new FormData(event.currentTarget).get('amount'));
      if (!Number.isFinite(amount) || amount <= 0 || amount > 1000000) return;
      updateSelected({ balance: Math.round((selected.balance + amount) * 100) / 100 }); setModal(null); setMessage('Demo balance updated. No payment was made.');
    }}><p className="dialog-description">Available balance: {money(selected.balance)}. This changes the demo balance only.</p>{isHome && <label>Wallet to fund<select value={selectedId} onChange={event => setSelectedId(event.target.value)}>{activeWallets.map(wallet => <option key={wallet.id} value={wallet.id}>{wallet.name}</option>)}</select></label>}<label>Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" placeholder="100.00" required autoFocus /></label><button className="primary-button form-submit">Add demo funds</button></form></Dialog>}
    {modal === 'constraints' && selected && <Dialog title="Wallet constraints" onClose={() => setModal(null)}><form onSubmit={event => {
      event.preventDefault(); if (selected.archived) return;
      const data = new FormData(event.currentTarget);
      const merchants = String(data.get('merchants')).split(',').map(m => m.trim()).filter(Boolean);
      if (!merchants.length) return;
      updateSelected({ constraints: { ...draftConstraints, merchants } }); setModal(null); setMessage('Demo wallet constraints updated.');
    }}><p className="dialog-description">Set spending rules for {selected.name}. Rules are saved for this demo; no payments are executed.</p>
      <div className="form-grid"><label>Spend limit ($)<input type="number" min="0.01" step="0.01" required value={draftConstraints.spend} onChange={e => setDraftConstraints({ ...draftConstraints, spend: +e.target.value })} autoFocus /></label>
      <label>Duration (days)<input type="number" min="1" max="365" step="1" required value={draftConstraints.days} onChange={e => setDraftConstraints({ ...draftConstraints, days: +e.target.value })} /></label></div>
      <label>Allowed merchants<input name="merchants" required defaultValue={draftConstraints.merchants.join(', ')} /></label>
      <label>Ask for approval above ($)<input type="number" min="0" step="0.01" required value={draftConstraints.approval} onChange={e => setDraftConstraints({ ...draftConstraints, approval: +e.target.value })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={draftConstraints.sweep} onChange={e => setDraftConstraints({ ...draftConstraints, sweep: e.target.checked })} />Sweep back when done</label>
      <button className="primary-button form-submit" disabled={selected.archived}>Save constraints</button>
    </form></Dialog>}
    {modal === 'settings' && <Dialog title="Workspace settings" onClose={() => setModal(null)}>
      <div className="settings-summary"><span>Mode</span><strong>Local demo</strong><span>Active wallets</span><strong>{activeWallets.length}</strong><span>Archived wallets</span><strong>{workspace.wallets.filter(w => w.archived).length}</strong></div>
      <p className="dialog-description">Wallets, balances, and constraints are simulated and saved in this browser. No wallet service or Ledger device is connected.</p>
      {selected && <div className="settings-wallet"><p>Selected wallet</p><strong>{selected.name}</strong>
        {!selected.archived && <label>Wallet folder<select value={selected.folderId ?? ''} onChange={event => moveWallet(selected.id, event.target.value || undefined)}>
          <option value="">Disposable Wallets</option>{workspace.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
        </select></label>}
        <button className="secondary-button" onClick={toggleArchive}>{selected.archived ? 'Restore selected wallet' : 'Archive selected wallet'}</button></div>}
    </Dialog>}
  </div>;
}
