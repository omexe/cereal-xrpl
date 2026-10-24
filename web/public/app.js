/**
 * Cereal Read-Only Projector Dashboard (Part 5)
 *
 * Polls GET /api/main, GET /api/subagents, GET /api/subagents/{id} (for active/presented),
 * and GET /api/vendors/{address} every 2 seconds.
 * Never sends a POST request; renders strictly what the API returns.
 */

const XRPL_EXPLORER = 'https://testnet.xrpl.org';
const KNOWN_VENDORS = [
  { label: 'Vendor A', address: 'rGrhEwizViewpp8b91RTdUV2MpdWUdaEay' },
  { label: 'Vendor B', address: 'rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3' },
];

const state = {
  initialRlusd: null,
  initialXrp: null,
  main: null,
  subagents: [],
  vendors: {},
  filter: 'all',
  lastRenderFingerprint: '',
  lastVendorFingerprint: '',
  pollCount: 0,
};

function escapeHtml(val) {
  if (val === null || val === undefined) return '';
  return String(val)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function shortHash(hash, lead = 8, tail = 6) {
  if (!hash || typeof hash !== 'string') return '—';
  if (hash.length <= lead + tail + 2) return hash;
  return `${hash.slice(0, lead)}…${hash.slice(-tail)}`;
}

function xrplAccountLink(address, full = false) {
  if (!address) return '<span class="mono-val">—</span>';
  const label = full ? address : shortHash(address, 10, 6);
  return `<a class="mono-val" href="${XRPL_EXPLORER}/accounts/${encodeURIComponent(address)}" target="_blank" rel="noopener" title="${escapeHtml(address)}">${escapeHtml(label)}</a>`;
}

function xrplTxLink(hash, labelPrefix = '') {
  if (!hash) return '';
  const text = labelPrefix ? `${labelPrefix} ${shortHash(hash, 8, 6)}` : shortHash(hash, 8, 6);
  return `<a class="tx-hash-link" href="${XRPL_EXPLORER}/transactions/${encodeURIComponent(hash)}" target="_blank" rel="noopener" title="${escapeHtml(hash)}">${escapeHtml(text)} ↗</a>`;
}

function formatNum(val, maxDecimals = 4) {
  if (val === null || val === undefined || val === '') return '—';
  const n = Number(val);
  if (!Number.isFinite(n)) return String(val);
  return n.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: maxDecimals,
  });
}

function toNum(val) {
  const n = Number(val);
  return Number.isFinite(n) ? n : 0;
}

function formatTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toISOString().slice(11, 19) + ' UTC';
  } catch {
    return String(iso);
  }
}

async function fetchJson(path) {
  const res = await fetch(path, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`GET ${path} -> HTTP ${res.status}`);
  }
  return res.json();
}

function updateMainHeader(main) {
  if (!main || !main.address) return;

  const rlusdNow = toNum(main.rlusd);
  const xrpNow = toNum(main.xrp);
  if (state.initialRlusd === null && main.rlusd !== undefined) {
    state.initialRlusd = rlusdNow;
  }
  if (state.initialXrp === null && main.xrp !== undefined) {
    state.initialXrp = xrpNow;
  }

  const addrEl = document.getElementById('main-address');
  addrEl.innerHTML = xrplAccountLink(main.address, true);

  document.getElementById('main-rlusd').textContent = formatNum(main.rlusd, 4);
  document.getElementById('main-xrp').textContent = formatNum(main.xrp, 4);
  document.getElementById('main-outstanding').textContent = formatNum(main.outstanding_budget, 2);
  document.getElementById('main-active-count').textContent = String(main.active_subagents ?? 0);

  // Delta badges when main wallet balance changes during `make rails`
  const rlusdDeltaEl = document.getElementById('main-rlusd-delta');
  if (state.initialRlusd !== null) {
    const diff = rlusdNow - state.initialRlusd;
    document.getElementById('main-rlusd-initial').textContent =
      `Session start: ${formatNum(state.initialRlusd, 4)} RLUSD (exact: ${main.rlusd})`;
    if (Math.abs(diff) >= 0.000001) {
      const sign = diff > 0 ? '+' : '';
      rlusdDeltaEl.textContent = `${sign}${diff.toFixed(4)} RLUSD`;
      rlusdDeltaEl.className = `metric-delta ${diff > 0 ? 'delta-pos' : 'delta-neg'}`;
    } else {
      rlusdDeltaEl.className = 'metric-delta hidden';
    }
  }

  const xrpDeltaEl = document.getElementById('main-xrp-delta');
  if (state.initialXrp !== null) {
    const diffXrp = xrpNow - state.initialXrp;
    document.getElementById('main-xrp-initial').textContent =
      `Session start: ${formatNum(state.initialXrp, 4)} XRP`;
    if (Math.abs(diffXrp) >= 0.0001) {
      const sign = diffXrp > 0 ? '+' : '';
      xrpDeltaEl.textContent = `${sign}${diffXrp.toFixed(4)} XRP`;
      xrpDeltaEl.className = `metric-delta ${diffXrp > 0 ? 'delta-pos' : 'delta-neg'}`;
    } else {
      xrpDeltaEl.className = 'metric-delta hidden';
    }
  }

  const caps = main.caps || {};
  document.getElementById('cap-outstanding').textContent =
    `Cap: ${caps.MAX_OUTSTANDING_BUDGET ?? '—'} RLUSD max outstanding`;
  document.getElementById('cap-active').textContent =
    `/ ${caps.MAX_ACTIVE_SUBAGENTS ?? '—'} max`;
  document.getElementById('cap-per-subagent').textContent =
    `Per-subagent cap: ${caps.MAX_SUBAGENT_BUDGET ?? '—'} RLUSD`;

  const policy = main.policy || {};
  setPolicyBadge('badge-vendor-cred', 'vendor credentials', Boolean(policy.vendor_credentials));
  setPolicyBadge('badge-device-funding', 'owner approval on Ledger', Boolean(policy.device_funding));
  setPolicyBadge('badge-ledger-recovery', 'Ledger recovery signer', Boolean(policy.ledger_recovery));
  const ap4mReady = Boolean(policy.ap4m && policy.ap4m.node_modules && policy.ap4m.env_file);
  setPolicyBadge('badge-ap4m', 'AP4M rail ready', ap4mReady);

  const issuerEl = document.getElementById('policy-issuer-link');
  if (policy.issuer) {
    issuerEl.innerHTML = `Credential Issuer: ${xrplAccountLink(policy.issuer, false)}`;
  }

  const deviceBox = document.getElementById('ledger-device-address');
  if (policy.device) {
    deviceBox.innerHTML = `<span class="field-label">Device:</span> ${xrplAccountLink(policy.device, true)}`;
  }
}

function setPolicyBadge(id, label, isOn) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `policy-badge ${isOn ? 'on' : 'off'}`;
  el.textContent = `${label}: ${isOn ? 'ON' : 'OFF'}`;
}

function renderDeviceScreenHtml(approval, depId, task, extraFooter = '') {
  if (!approval) return '';
  const isApproved = approval.result === 'approved';
  const resultLabel = isApproved
    ? 'APPROVED ON LEDGER'
    : approval.result === 'owner_rejected'
      ? 'REJECTED ON OWNER’S LEDGER'
      : String(approval.result || 'DEVICE');
  const screens = Array.isArray(approval.screens) ? approval.screens : [];

  const screenLinesHtml = screens
    .map((line) => {
      const s = String(line);
      const isHighlight =
        s.startsWith('Amount:') ||
        s.startsWith('Currency:') ||
        s.startsWith('Destination:') ||
        s.startsWith('Sign transaction?');
      return `<div class="device-screen-line ${isHighlight ? 'highlight' : ''}">${escapeHtml(s)}</div>`;
    })
    .join('');

  return `
    <div class="device-screen-card ${isApproved ? 'approved' : 'rejected'}">
      <div class="device-screen-header">
        <span class="device-screen-title">${escapeHtml(depId)} · ${escapeHtml(task || '')}</span>
        <span class="status-chip ${isApproved ? 'reclaimed' : 'rejected'}">${escapeHtml(resultLabel)}</span>
      </div>
      <div class="device-screen-lines">
        ${screenLinesHtml || '<div class="device-screen-line">(no screen lines recorded)</div>'}
      </div>
      ${extraFooter}
    </div>
  `;
}

function renderLedgerPanel(subagents) {
  const container = document.getElementById('ledger-approvals-list');
  const withApprovals = [...subagents]
    .reverse()
    .filter((d) => d && d.approval && (d.approval.result || (d.approval.screens && d.approval.screens.length)));

  if (!withApprovals.length) {
    container.innerHTML = `<div class="empty-note">No Ledger device approvals recorded yet.</div>`;
    return;
  }

  container.innerHTML = withApprovals
    .map((d) => {
      const footer =
        d.status === 'rejected' || d.approval?.result === 'owner_rejected'
          ? `<div style="display:flex;justify-content:space-between;align-items:center;font-size:14px;padding-top:4px;border-top:1px solid #2e3d59;">
               <span style="color:var(--danger-fg);font-weight:700;">Rejected on the owner’s Ledger</span>
               <span class="zero-tx-badge">0 transactions sent</span>
             </div>`
          : `<div style="display:flex;justify-content:space-between;align-items:center;font-size:14px;color:var(--text-muted);padding-top:4px;border-top:1px solid #1e293b;">
               <span>Signer: ${xrplAccountLink(d.approval.by, false)}</span>
               ${d.hashes?.fund ? xrplTxLink(d.hashes.fund, 'Fund tx') : ''}
             </div>`;
      return renderDeviceScreenHtml(d.approval, d.id, d.task, footer);
    })
    .join('');
}

function renderVendorsPanel() {
  const container = document.getElementById('vendor-registry-list');
  const rows = KNOWN_VENDORS.map(({ label, address }) => {
    const v = state.vendors[address];
    if (!v) {
      return `
        <div class="vendor-item">
          <div class="vendor-top-row">
            <span class="vendor-name">${escapeHtml(label)} · ${xrplAccountLink(address, true)}</span>
            <span class="status-chip">loading…</span>
          </div>
        </div>
      `;
    }
    const status = String(v.status || 'none').toLowerCase();
    const isValid = status === 'valid';
    const isRevoked = status === 'revoked';
    const chipClass = isValid ? 'reclaimed' : isRevoked ? 'rejected' : 'failed';
    const statusText = isValid ? 'CREDENTIALED (VALID)' : status.toUpperCase();

    let revocationHtml = '';
    if (v.revocation) {
      const rev = v.revocation;
      const revLink = rev.explorer
        ? `<a class="tx-hash-link" href="${escapeHtml(rev.explorer)}" target="_blank" rel="noopener">Revocation tx ${escapeHtml(shortHash(rev.hash, 8, 6))} ↗</a>`
        : rev.hash
          ? xrplTxLink(rev.hash, 'Revocation tx')
          : '';
      revocationHtml = `
        <div class="vendor-revocation-box">
          <strong>Revoked on-ledger:</strong>
          <span>reason: <code>${escapeHtml(rev.reason || '—')}</code></span>
          ${rev.report ? `<span>report: <code>${escapeHtml(rev.report)}</code></span>` : ''}
          ${rev.ledger_index ? `<span>ledger: <code>#${escapeHtml(rev.ledger_index)}</code></span>` : ''}
          ${revLink}
        </div>
      `;
    }

    return `
      <div class="vendor-item ${isValid ? 'vendor-valid' : isRevoked ? 'vendor-revoked' : ''}">
        <div class="vendor-top-row">
          <span class="vendor-name">${escapeHtml(label)} · ${xrplAccountLink(address, true)}</span>
          <span class="status-chip ${chipClass}">${escapeHtml(statusText)}</span>
        </div>
        <div class="vendor-meta">
          <span>Class: <code>${escapeHtml(v.class || 'data')}</code></span>
          ${v.issuer ? `<span>Issuer: ${xrplAccountLink(v.issuer, false)}</span>` : ''}
          ${v.index ? `<span>Credential ID: <code>${escapeHtml(shortHash(v.index, 10, 6))}</code></span>` : ''}
        </div>
        ${revocationHtml}
      </div>
    `;
  });

  container.innerHTML = rows.join('');
}

function computeBudgetBreakdown(dep) {
  const budget = toNum(dep.budget);
  const payments = Array.isArray(dep.payments) ? dep.payments : [];

  let xrplSpent = 0;
  let ap4mSpent = 0;

  for (const p of payments) {
    const amt = toNum(p.amount);
    const rail = p.rail || 'direct';
    const isOk = p.ok === true || p.result === 'tesSUCCESS' || p.result === 'redeemed' || p.result === 'presented';
    if (!isOk) continue;
    if (rail === 'ap4m') {
      ap4mSpent += amt;
    } else {
      xrplSpent += amt;
    }
  }

  let returned = dep.returned !== undefined && dep.returned !== null ? toNum(dep.returned) : 0;
  if (dep.status === 'recovered' && returned === 0 && budget > xrplSpent) {
    // Recovered subwallet swept its remaining XRPL balance back to main wallet
    returned = Math.max(0, budget - xrplSpent);
  }

  let remaining = 0;
  if (dep.status === 'active' || dep.status === 'deploying') {
    if (dep.balance !== undefined && dep.balance !== null) {
      remaining = Math.max(0, toNum(dep.balance) - ap4mSpent);
    } else {
      remaining = Math.max(0, budget - xrplSpent - ap4mSpent);
    }
  }

  const denom = Math.max(budget, xrplSpent + ap4mSpent + returned + remaining, 0.0001);
  return {
    budget,
    xrplSpent,
    ap4mSpent,
    returned,
    remaining,
    pctXrpl: Math.min(100, (xrplSpent / denom) * 100),
    pctAp4m: Math.min(100, (ap4mSpent / denom) * 100),
    pctReturned: Math.min(100, (returned / denom) * 100),
    pctRemaining: Math.min(100, (remaining / denom) * 100),
  };
}

function renderTimeline(dep) {
  const rows = [];
  const hashes = dep.hashes || {};
  const hasApproval = Boolean(dep.approval && dep.approval.result);

  // 1. Activate
  if (hashes.activate) {
    rows.push(`
      <div class="timeline-row">
        <div class="timeline-left">
          <span class="step-badge">1 · activate</span>
          <span>Burner subwallet created on XRPL (${xrplAccountLink(dep.subwallet, false)})</span>
        </div>
        <div class="timeline-right">
          ${xrplTxLink(hashes.activate)}
        </div>
      </div>
    `);
  }

  // 2. Lock
  if (Array.isArray(hashes.lock) && hashes.lock.length > 0) {
    const lockLinks = hashes.lock
      .filter(Boolean)
      .map((h, idx) => {
        const labels = ['TrustSet', 'SignerListSet (quorum 2)', 'SetRegularKey (master disabled)'];
        return xrplTxLink(h, labels[idx] || `Lock #${idx + 1}`);
      })
      .join(' ');
    rows.push(`
      <div class="timeline-row">
        <div class="timeline-left">
          <span class="step-badge">2 · lock</span>
          <span>RLUSD trustline + 2-of-2 multisig (subagent w=1, co-signer w=1, owner’s Ledger w=2) + master key disabled</span>
        </div>
        <div class="timeline-right">
          ${lockLinks}
        </div>
      </div>
    `);
  }

  // 3. Fund
  if (hashes.fund) {
    const ledgerSignedBadge = hasApproval
      ? `<span class="ledger-note-badge">signed by the Ledger (${escapeHtml(shortHash(dep.approval.by, 8, 5))})</span>`
      : '';
    rows.push(`
      <div class="timeline-row ${hasApproval ? 'row-ledger' : ''}">
        <div class="timeline-left">
          <span class="step-badge">3 · fund</span>
          <span>Funded <strong>${escapeHtml(dep.budget)} RLUSD</strong> from main wallet</span>
          ${ledgerSignedBadge}
        </div>
        <div class="timeline-right">
          ${xrplTxLink(hashes.fund)}
        </div>
      </div>
    `);
  }

  // 4. Interleave payments & refusals chronologically by `at`
  const events = [];
  for (const p of dep.payments || []) {
    events.push({ kind: 'payment', at: p.at || '', data: p });
  }
  for (const r of dep.refusals || []) {
    events.push({ kind: 'refusal', at: r.at || '', data: r });
  }
  events.sort((a, b) => String(a.at).localeCompare(String(b.at)));

  for (const ev of events) {
    if (ev.kind === 'payment') {
      const p = ev.data;
      const rail = (p.rail || 'direct').toLowerCase();
      const isAp4m = rail === 'ap4m';
      const railLabel = isAp4m ? 'AP4M (XRPL EVM)' : rail === 'x402' ? 'x402 (XRPL)' : 'DIRECT (XRPL)';
      const explorerUrl = p.explorer || (p.hash && !isAp4m ? `${XRPL_EXPLORER}/transactions/${p.hash}` : null);
      const txLinkHtml = explorerUrl && p.hash
        ? `<a class="tx-hash-link" href="${escapeHtml(explorerUrl)}" target="_blank" rel="noopener" title="${escapeHtml(p.hash)}">${escapeHtml(shortHash(p.hash, 8, 6))} ↗</a>`
        : '';

      const receiptLinkHtml = isAp4m && p.receipt
        ? `<a class="tx-hash-link" href="${escapeHtml(
            String(p.receipt).startsWith('http')
              ? p.receipt
              : `https://hackathon.ap4m.build/public/evidence/claims/${p.receipt}`
          )}" target="_blank" rel="noopener">Receipt ↗</a>`
        : '';

      const channelHtml = isAp4m && p.channel_id
        ? `<span class="mono-val" title="AP4M Channel ID: ${escapeHtml(p.channel_id)}">ch: ${escapeHtml(shortHash(p.channel_id, 8, 5))}</span>`
        : '';

      const payeeHtml = isAp4m
        ? `<code title="${escapeHtml(p.to || '')}">${escapeHtml(shortHash(p.to || 'merchant', 8, 5))}</code>`
        : xrplAccountLink(p.to, false);

      rows.push(`
        <div class="timeline-row ${isAp4m ? 'row-payment-ap4m' : 'row-payment-xrpl'}">
          <div class="timeline-left">
            <span class="rail-badge ${isAp4m ? 'ap4m' : 'xrpl'}">${escapeHtml(railLabel)}</span>
            <span>Paid <strong>${escapeHtml(p.amount)} RLUSD</strong> → ${payeeHtml}</span>
            ${p.resource ? `<code>${escapeHtml(p.resource)}</code>` : ''}
            <span class="status-chip ${p.ok ? 'reclaimed' : 'active'}">${escapeHtml(p.result || (p.ok ? 'ok' : 'pending'))}</span>
          </div>
          <div class="timeline-right">
            ${channelHtml}
            ${receiptLinkHtml}
            ${txLinkHtml}
            ${p.at ? `<span style="color:var(--text-muted)">${escapeHtml(formatTime(p.at))}</span>` : ''}
          </div>
        </div>
      `);
    } else {
      const r = ev.data;
      const reason = r.refused || r.result || 'refused';
      const payee = r.payee || r.resource || r.to || '—';
      const rev = r.vendor && r.vendor.revocation ? r.vendor.revocation : null;
      const revExplorer = rev ? rev.explorer || (rev.hash ? `${XRPL_EXPLORER}/transactions/${rev.hash}` : null) : null;
      const evidenceHtml = rev
        ? `<span>vendor status: <strong>${escapeHtml(r.vendor.status || 'revoked')}</strong> · reason: <code>${escapeHtml(rev.reason || '—')}</code>${rev.report ? ` (${escapeHtml(rev.report)})` : ''}</span>
           ${revExplorer ? `<a class="tx-hash-link" href="${escapeHtml(revExplorer)}" target="_blank" rel="noopener">Revocation tx ${escapeHtml(shortHash(rev.hash, 8, 6))} ↗</a>` : ''}`
        : r.error
          ? `<span class="mono-val">${escapeHtml(String(r.error).slice(0, 140))}</span>`
          : r.remaining !== undefined
            ? `<span>remaining budget: <code>${escapeHtml(r.remaining)} RLUSD</code></span>`
            : '';

      rows.push(`
        <div class="timeline-row row-refusal">
          <div class="timeline-left">
            <span class="refusal-badge">REFUSED · ${escapeHtml(reason)}</span>
            ${r.rail ? `<span class="rail-badge ${r.rail === 'ap4m' ? 'ap4m' : 'xrpl'}">${escapeHtml(r.rail)}</span>` : ''}
            ${r.amount ? `<span>Attempted <strong>${escapeHtml(r.amount)} RLUSD</strong></span>` : ''}
            <span>→ <code>${escapeHtml(payee)}</code></span>
            ${evidenceHtml}
          </div>
          <div class="timeline-right">
            ${r.at ? `<span>${escapeHtml(formatTime(r.at))}</span>` : ''}
          </div>
        </div>
      `);
    }
  }

  // 5. Reclaim
  if (Array.isArray(hashes.reclaim) && hashes.reclaim.length > 0) {
    const reclaimLinks = hashes.reclaim
      .filter(Boolean)
      .map((h, i) => xrplTxLink(h, i === 0 ? 'Sweep RLUSD' : 'Claw TrustSet 0'))
      .join(' ');
    rows.push(`
      <div class="timeline-row">
        <div class="timeline-left">
          <span class="step-badge">reclaim</span>
          <span>Swept <strong>${escapeHtml(dep.returned ?? '0')} RLUSD</strong> back to main wallet &amp; zeroed trustline</span>
        </div>
        <div class="timeline-right">
          ${reclaimLinks}
        </div>
      </div>
    `);
  }

  // 6. Recover (owner's Ledger alone)
  if (Array.isArray(hashes.recover) && hashes.recover.length > 0) {
    const recoverLinks = hashes.recover
      .filter(Boolean)
      .map((h, i) => xrplTxLink(h, i === 0 ? 'Recover RLUSD' : 'Zero TrustSet'))
      .join(' ');
    rows.push(`
      <div class="timeline-row row-ledger">
        <div class="timeline-left">
          <span class="step-badge">recover</span>
          <span>Emergency sweep back to main wallet</span>
          <span class="ledger-note-badge">owner’s Ledger alone (weight 2 meets quorum 2)</span>
        </div>
        <div class="timeline-right">
          ${recoverLinks}
        </div>
      </div>
    `);
  }

  // 7. Retire
  if (hashes.retire) {
    rows.push(`
      <div class="timeline-row">
        <div class="timeline-left">
          <span class="step-badge">retire</span>
          <span>Subwallet deleted on-ledger (<code>AccountDelete</code>) — XRP reserve returned to main wallet</span>
        </div>
        <div class="timeline-right">
          ${xrplTxLink(hashes.retire, 'AccountDelete')}
        </div>
      </div>
    `);
  }

  if (!rows.length) {
    return `<div class="empty-note">No on-ledger transactions sent for this deployment.</div>`;
  }

  return `<div class="timeline-list">${rows.join('')}</div>`;
}

function renderDeploymentCard(dep) {
  const status = String(dep.status || 'unknown').toLowerCase();
  const isRejected = status === 'rejected' || dep.approval?.result === 'owner_rejected';
  const b = computeBudgetBreakdown(dep);

  const subwalletHtml = dep.subwallet
    ? xrplAccountLink(dep.subwallet, true)
    : isRejected
      ? '<span class="mono-val" style="color:var(--danger-fg)">Not created on-ledger (0 transactions sent)</span>'
      : '<span class="mono-val">—</span>';

  const subagentHtml = dep.subagent ? xrplAccountLink(dep.subagent, true) : '<span class="mono-val">—</span>';

  const rejectedBannerHtml = isRejected
    ? `
      <div class="rejected-callout">
        <div class="rejected-callout-header">
          <span class="rejected-title">Rejected on the owner’s Ledger — subwallet never created or funded</span>
          <span class="zero-tx-badge">0 transactions sent</span>
        </div>
        ${renderDeviceScreenHtml(dep.approval, dep.id, dep.task)}
      </div>
    `
    : '';

  const approvalInlineHtml =
    !isRejected && dep.approval && Array.isArray(dep.approval.screens) && dep.approval.screens.length
      ? `
        <details style="background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:8px;padding:8px 12px;">
          <summary style="cursor:pointer;font-size:14px;font-weight:700;color:var(--accent-ledger);">
            Ledger Hardware Approval Screen (${escapeHtml(dep.approval.result || 'approved')} by ${escapeHtml(shortHash(dep.approval.by, 10, 6))} · ${dep.approval.screens.length} screen lines)
          </summary>
          <div style="margin-top:10px;">
            ${renderDeviceScreenHtml(dep.approval, dep.id, dep.task)}
          </div>
        </details>
      `
      : '';

  return `
    <article class="deployment-card status-${escapeHtml(status)}" data-id="${escapeHtml(dep.id)}">
      <div class="card-header-row">
        <div class="card-title-block">
          <div class="card-id-task">
            <span class="dep-id-badge">${escapeHtml(dep.id)}</span>
            <span class="dep-task">${escapeHtml(dep.task || 'Untitled subagent task')}</span>
          </div>
          <div class="card-addresses-row">
            <span class="addr-item"><span class="field-label">Subwallet:</span> ${subwalletHtml}</span>
            <span class="addr-item"><span class="field-label">Subagent Signer:</span> ${subagentHtml}</span>
            ${dep.tag ? `<span class="addr-item"><span class="field-label">Job Tag:</span> <code>${escapeHtml(shortHash(dep.tag, 10, 6))}</code></span>` : ''}
            ${dep.expires_at ? `<span class="addr-item"><span class="field-label">Expires:</span> <code>${escapeHtml(formatTime(dep.expires_at))}</code></span>` : ''}
          </div>
        </div>
        <span class="status-chip ${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>

      ${rejectedBannerHtml}

      <!-- Budget Bar across XRPL and AP4M rails -->
      <div class="budget-box">
        <div class="budget-header-row">
          <span class="budget-total-label">Scoped Budget Cap: <code>${escapeHtml(dep.budget)} RLUSD</code></span>
          <div class="budget-legend">
            <span class="legend-item"><span class="legend-dot xrpl"></span>Spent on XRPL: <strong>${formatNum(b.xrplSpent, 4)} RLUSD</strong></span>
            <span class="legend-item"><span class="legend-dot ap4m"></span>Spent on AP4M: <strong>${formatNum(b.ap4mSpent, 4)} RLUSD</strong></span>
            <span class="legend-item"><span class="legend-dot remaining"></span>Remaining: <strong>${formatNum(b.remaining, 4)} RLUSD</strong></span>
            <span class="legend-item"><span class="legend-dot returned"></span>Returned: <strong>${formatNum(b.returned, 4)} RLUSD</strong></span>
          </div>
        </div>
        <div class="budget-bar-track">
          <div class="budget-segment xrpl" style="width:${b.pctXrpl.toFixed(2)}%" title="Spent on XRPL: ${b.xrplSpent} RLUSD"></div>
          <div class="budget-segment ap4m" style="width:${b.pctAp4m.toFixed(2)}%" title="Spent on AP4M: ${b.ap4mSpent} RLUSD"></div>
          <div class="budget-segment returned" style="width:${b.pctReturned.toFixed(2)}%" title="Returned to Main Wallet: ${b.returned} RLUSD"></div>
          <div class="budget-segment remaining" style="width:${b.pctRemaining.toFixed(2)}%" title="Remaining: ${b.remaining} RLUSD"></div>
        </div>
      </div>

      ${approvalInlineHtml}

      ${renderTimeline(dep)}

      ${dep.summary ? `<div style="font-size:14px;color:var(--text-secondary);padding-top:4px;border-top:1px solid var(--border-subtle);"><strong>Subagent Summary:</strong> ${escapeHtml(dep.summary)}</div>` : ''}
    </article>
  `;
}

function renderDeploymentsList() {
  const container = document.getElementById('deployments-container');
  const newestFirst = [...state.subagents].reverse();

  document.getElementById('deployments-count').textContent = String(newestFirst.length);

  let filtered = newestFirst;
  if (state.filter === 'rejected') {
    filtered = newestFirst.filter((d) => d.status === 'rejected' || d.approval?.result === 'owner_rejected');
  } else if (state.filter === 'latest') {
    filtered = newestFirst.slice(0, 4);
  }

  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state">No matching subagent deployments found.</div>`;
    return;
  }

  container.innerHTML = filtered.map(renderDeploymentCard).join('');
}

async function pollOnce() {
  const dotEl = document.getElementById('live-dot');
  const statusEl = document.getElementById('poll-status-text');

  try {
    const [mainData, subagentsData] = await Promise.all([
      fetchJson('/api/main'),
      fetchJson('/api/subagents'),
    ]);

    const list = Array.isArray(subagentsData) ? subagentsData : [];

    // For active/deploying subagents or any with unresolved "presented" x402 payments,
    // also fetch GET /api/subagents/{id} to trigger _resolve_presented and live balance.
    const needsDetailIds = list
      .filter(
        (d) =>
          d &&
          d.id &&
          (d.status === 'active' ||
            d.status === 'deploying' ||
            (Array.isArray(d.payments) && d.payments.some((p) => p.result === 'presented')))
      )
      .map((d) => d.id);

    if (needsDetailIds.length > 0) {
      const detailed = await Promise.all(
        needsDetailIds.map((id) => fetchJson(`/api/subagents/${encodeURIComponent(id)}`).catch(() => null))
      );
      const byId = new Map(detailed.filter(Boolean).map((d) => [d.id, d]));
      for (let i = 0; i < list.length; i++) {
        if (byId.has(list[i].id)) {
          list[i] = byId.get(list[i].id);
        }
      }
    }

    state.main = mainData;
    state.subagents = list;
    updateMainHeader(mainData);

    const fp = JSON.stringify({ subagents: list, filter: state.filter });
    if (fp !== state.lastRenderFingerprint) {
      state.lastRenderFingerprint = fp;
      renderLedgerPanel(list);
      renderDeploymentsList();
    }

    // Fetch Vendor A and Vendor B status (every poll or every other poll)
    if (state.pollCount % 2 === 0 || Object.keys(state.vendors).length < KNOWN_VENDORS.length) {
      const vendorResults = await Promise.all(
        KNOWN_VENDORS.map(({ address }) =>
          fetchJson(`/api/vendors/${encodeURIComponent(address)}`).catch(() => null)
        )
      );
      KNOWN_VENDORS.forEach(({ address }, idx) => {
        if (vendorResults[idx]) {
          state.vendors[address] = vendorResults[idx];
        }
      });
      const vfp = JSON.stringify(state.vendors);
      if (vfp !== state.lastVendorFingerprint) {
        state.lastVendorFingerprint = vfp;
        renderVendorsPanel();
      }
    }

    state.pollCount += 1;
    dotEl.className = 'live-dot';
    statusEl.textContent = `Live · updated ${new Date().toLocaleTimeString()} (2s poll)`;
  } catch (err) {
    dotEl.className = 'live-dot error';
    statusEl.textContent = `Service unreachable (:8001) — retrying in 2s…`;
  }
}

function setupFilters() {
  const buttons = document.querySelectorAll('.filter-btn');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.filter = btn.getAttribute('data-filter') || 'all';
      state.lastRenderFingerprint = '';
      renderDeploymentsList();
    });
  });
}

setupFilters();
pollOnce();
setInterval(pollOnce, 2000);
