import { isLive } from './mode';

/** Mock amounts are demo dollars; live amounts are RLUSD on XRPL testnet, kept as decimal strings end to end. */
export function formatAmount(amount: number | string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return isLive ? '— RLUSD' : '$—';
  if (!isLive) return `$${Number(amount).toFixed(2)}`;
  return `${trimDecimal(String(amount))} RLUSD`;
}

/** "0.5" → "0.50", "6.9977242779" → "6.997724", "12" → "12.00": at least 2 and at most 6 decimals, never rounded up. */
export function trimDecimal(value: string): string {
  const [whole, frac = ''] = value.split('.');
  const kept = frac.slice(0, 6).replace(/0+$/, '');
  return `${whole}.${kept.padEnd(2, '0')}`;
}

/** Adds decimal strings exactly (RLUSD has at most 15 significant digits; 1e-15 resolution is enough here). */
export function sumDecimals(values: (string | number | null | undefined)[]): string {
  const SCALE = 10n ** 15n;
  const total = values.reduce<bigint>((sum, v) => sum + toScaled(v, SCALE), 0n);
  const sign = total < 0n ? '-' : '';
  const abs = total < 0n ? -total : total;
  const frac = (abs % SCALE).toString().padStart(15, '0').replace(/0+$/, '');
  return `${sign}${abs / SCALE}${frac ? `.${frac}` : ''}`;
}

function toScaled(v: string | number | null | undefined, scale: bigint): bigint {
  if (v === null || v === undefined || v === '') return 0n;
  const s = String(v).trim();
  const negative = s.startsWith('-');
  const [whole, frac = ''] = s.replace(/^[-+]/, '').split('.');
  const scaled = BigInt(whole || '0') * scale + BigInt((frac + '0'.repeat(15)).slice(0, 15) || '0');
  return negative ? -scaled : scaled;
}

export const shortAddress = (address?: string | null) => address ? `${address.slice(0, 6)}…${address.slice(-4)}` : '';
export const explorerTx = (hash?: string | null) => hash ? `https://testnet.xrpl.org/transactions/${hash}` : undefined;
export const explorerAccount = (address?: string | null) => address ? `https://testnet.xrpl.org/accounts/${address}` : undefined;
