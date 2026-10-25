/** Reads a half-typed wallet request ("Create a wallet called Breakfast Customer Discovery with a budget of $20 over
 * 2 days") into a draft, so Home can show the wallet forming as the user types. It is a preview only: in live mode
 * cereal's compiler reads the final sentence, and the mock wallet is created from exactly what this shows. Nothing
 * untyped is filled in. */
import { defaultConstraints, type Constraints } from '../wallets';

export interface Draft {
  name?: string;
  spend?: number;
  days?: number;
  merchants: string[];
  /** undefined: never ask (the approval threshold is the whole budget). */
  approval?: number;
  /** undefined until typed; a wallet that does not say sweeps back, cereal's default. */
  sweep?: boolean;
  /** 0..1, how much of the wallet the sentence has pinned down; the forming sphere gets denser with it. */
  progress: number;
}

const money = String.raw`\$\s?(\d+(?:\.\d{1,2})?)`;
const list = (items: string[]) => items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`;
/** A vendor list: names starting with `first`, joined by commas, "and" or "&". */
const vendorPattern = (first: string) => String.raw`${first}[\w&.-]*(?:\s*(?:,|and|&)\s*${first}[\w&.-]*)*`;
const STOP = /^(?:keep|sweep|ask|approve|check|the|a|an|most|least|any|all|over|for|when|then|but|with|budget|spend|up|to)$/i;
const titleCase = (text: string) => text.replace(/\b\w/g, c => c.toUpperCase());
// Known vendors keep their own spelling however they are typed ("hubspot" → HubSpot).
const vendorName = (typed: string) => defaultConstraints.merchants.find(v => v.toLowerCase() === typed.toLowerCase()) ?? titleCase(typed);

export function parseDraft(text: string): Draft {
  const name = text.match(/\b(?:called|named)\s+["“]?(.+?)["”]?(?=\s+(?:with|for|to|that|which|and|budget|spend|over|at|on)\b|[,.;]|$)/i)?.[1]?.trim();
  const approvalMatch = text.match(new RegExp(String.raw`\b(?:ask(?: me)?|approv\w*|check with me)\b[^$]*?(?:above|over|more than|>)\s*${money}`, 'i'));
  // The budget is the first amount outside the approval phrase.
  const budget = (approvalMatch ? text.replace(approvalMatch[0], ' ') : text).match(new RegExp(money, 'i'))?.[1];
  const spend = budget ? Number(budget) : undefined;
  const period = text.match(/\b(\d+)\s*(day|week)s?\b/i);
  const days = period ? Number(period[1]) * (/week/i.test(period[2]) ? 7 : 1) : undefined;
  // After "only at", "using" or "vendors" a vendor may be any case ("only at apollo"); after a bare "at/on/from" only a
  // capitalized name counts, so "at most $30" or "on the span of" never reads as one.
  const vendors = text.match(new RegExp(String.raw`\b(?:only (?:at|on|from|with|using)|using|vendors?:?)\s+(${vendorPattern('[A-Za-z]')})`, 'i'))?.[1]
    ?? text.match(new RegExp(String.raw`\b(?:at|on|from)\s+(${vendorPattern('[A-Z]')})`))?.[1];
  const merchants: string[] = [];
  for (const word of vendors?.split(/\s*(?:,|\band\b|&)\s*/i) ?? []) {
    const vendor = word.trim().replace(/\.+$/, '');
    if (STOP.test(vendor)) break; // "only at apollo and keep funds": the list ends where the next rule starts
    if (vendor) merchants.push(vendorName(vendor));
  }
  const sweep = /\b(?:keep (?:the )?funds|don'?t sweep|no sweep)\b/i.test(text) ? false : /\bsweep\b/i.test(text) ? true : undefined;
  const known = [name, spend, days, merchants.length || undefined].filter(v => v !== undefined).length;
  return {
    name: name || undefined, spend: spend && spend > 0 ? spend : undefined, days: days && days > 0 && days <= 365 ? days : undefined,
    merchants, approval: approvalMatch ? Number(approvalMatch[1]) : undefined, sweep, progress: Math.min(1, (text.trim() ? .15 : 0) + known * .21),
  };
}

/** The wallet's rules once the sentence states a budget, a time limit and vendors; nothing is filled in for it. */
export function draftConstraints(draft: Draft): Constraints | null {
  if (!draft.spend || !draft.days || !draft.merchants.length) return null;
  return { spend: draft.spend, days: draft.days, merchants: draft.merchants, approval: draft.approval ?? draft.spend, sweep: draft.sweep ?? true };
}

/** What the sentence still has to say before the wallet can be created. */
export function draftMissing(draft: Draft): string[] {
  return [!draft.spend && 'a budget', !draft.days && 'a time limit', !draft.merchants.length && 'vendors'].filter((x): x is string => !!x);
}

/** The rules exactly as typed so far, clause by clause: "Spend up to $20 over 2 days, only at Notion and Apollo." */
export function draftSentence(draft: Draft): string | null {
  const limit = [draft.spend && `spend up to $${draft.spend}`, draft.days && `over ${draft.days} ${draft.days === 1 ? 'day' : 'days'}`].filter(Boolean).join(' ');
  const vendors = draft.merchants.length ? `only at ${list(draft.merchants)}` : '';
  const first = [limit, vendors].filter(Boolean).join(', ');
  const clauses = [
    first && `${first[0].toUpperCase()}${first.slice(1)}.`,
    draft.approval !== undefined && (!draft.spend || draft.approval < draft.spend) && `Ask me above $${draft.approval}.`,
    draft.sweep !== undefined && `${draft.sweep ? 'Sweep back' : 'Keep funds'} when done.`,
  ].filter(Boolean);
  return clauses.length ? clauses.join(' ') : null;
}
