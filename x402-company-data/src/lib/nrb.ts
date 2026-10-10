// Polish bank account number (NRB): 26 digits, i.e. the national part of an
// IBAN "PL" + 26 digits. Validated with the IBAN mod-97 checksum so a typo gets
// a free 400 instead of a wasted (and quota-limited) upstream call.

/** Accepts "PL61 1090 1014 0000 0712 1981 2874", "61-1090-...", plain digits. Returns 26 digits or null. */
export function normalizeNrb(input: string): string | null {
  let s = input.replace(/[\s-]/g, "");
  if (/^PL/i.test(s)) s = s.slice(2);
  if (!/^\d{26}$/.test(s)) return null;
  // IBAN rule: move "PL" + check digits (country letters as 25 21) to the end.
  const rearranged = `${s.slice(2)}2521${s.slice(0, 2)}`;
  let rem = 0;
  for (const ch of rearranged) rem = (rem * 10 + Number(ch)) % 97;
  return rem === 1 ? s : null;
}
