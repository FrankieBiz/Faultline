
/**
 * Browser-local shopping cart.
 *
 * The cart is an external store persisted to `localStorage`, read through
 * `useSyncExternalStore`. SpecV1 §2.1 requires the cart to live in browser
 * state so that every new browser context (and therefore every oracle case)
 * starts empty. The server snapshot is always the empty cart, which keeps
 * server-rendered HTML deterministic; the stored cart appears after
 * hydration. Updates from other tabs arrive through the `storage` event.
 */

import { useSyncExternalStore } from "react";

/** Smallest and largest quantity the checkout contract accepts per line. */
export const MIN_QUANTITY = 1;
export const MAX_QUANTITY = 10;

/** One product in the cart. Prices are never stored; they come from the catalog. */
export interface CartLine {
  product_id: string;
  quantity: number;
}

/** Immutable cart snapshot. A new object is produced on every change. */
export interface Cart {
  lines: readonly CartLine[];
  /**
   * Number of in-page mutations since load. Zero for a cart restored from
   * storage, so UI feedback can react to changes rather than to page loads.
   */
  revision: number;
}

/** Outcome of adding a product, so the UI can explain a capped quantity. */
export interface AddToCartResult {
  quantity: number;
  capped: boolean;
}

const STORAGE_KEY = "buggyshop.cart.v1";
const EMPTY_CART: Cart = Object.freeze({ lines: Object.freeze([]), revision: 0 });

type Listener = () => void;

const listeners = new Set<Listener>();
let snapshot: Cart | null = null;

/** Clamps any number to a whole quantity inside the accepted range. */
export function clampQuantity(value: number): number {
  if (!Number.isFinite(value)) return MIN_QUANTITY;
  return Math.min(MAX_QUANTITY, Math.max(MIN_QUANTITY, Math.trunc(value)));
}

/**
 * Parses stored JSON into a valid cart, discarding malformed lines and
 * merging duplicates so a corrupted entry can never break checkout.
 */
function parseStoredCart(raw: string | null): Cart {
  if (!raw) return EMPTY_CART;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return EMPTY_CART;
  }
  if (typeof parsed !== "object" || parsed === null || !Array.isArray((parsed as { lines?: unknown }).lines)) {
    return EMPTY_CART;
  }
  const merged = new Map<string, number>();
  for (const entry of (parsed as { lines: unknown[] }).lines) {
    if (typeof entry !== "object" || entry === null) continue;
    const { product_id: productId, quantity } = entry as Record<string, unknown>;
    if (typeof productId !== "string" || !productId || typeof quantity !== "number") continue;
    merged.set(productId, clampQuantity((merged.get(productId) ?? 0) + quantity));
  }
  return freezeCart(
    [...merged].map(([product_id, quantity]) => ({ product_id, quantity })),
    0,
  );
}

function freezeCart(lines: CartLine[], revision: number): Cart {
  return Object.freeze({
    lines: Object.freeze(lines.map((line) => Object.freeze({ ...line }))),
    revision,
  });
}

function readStorage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStorage(cart: Cart): void {
  try {
    if (cart.lines.length === 0) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ lines: cart.lines }));
    }
  } catch {
    // Storage can be unavailable (private mode, quota). The in-memory cart
    // still works for the current page; persistence is best effort.
  }
}

function getSnapshot(): Cart {
  if (snapshot === null) snapshot = parseStoredCart(readStorage());
  return snapshot;
}

function getServerSnapshot(): Cart {
  return EMPTY_CART;
}

function emit(): void {
  for (const listener of listeners) listener();
}

function onStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== STORAGE_KEY) return;
  snapshot = parseStoredCart(readStorage());
  emit();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

function commit(lines: CartLine[]): void {
  snapshot = freezeCart(lines, getSnapshot().revision + 1);
  writeStorage(snapshot);
  emit();
}

/**
 * Adds `quantity` units of a product, capping the line at `MAX_QUANTITY`.
 * Returns the resulting line quantity and whether the cap was applied.
 */
export function addToCart(productId: string, quantity: number): AddToCartResult {
  const lines = [...getSnapshot().lines];
  const index = lines.findIndex((line) => line.product_id === productId);
  const current = index >= 0 ? (lines[index]?.quantity ?? 0) : 0;
  const requested = current + Math.max(0, Math.trunc(quantity));
  const next = clampQuantity(requested);
  if (index >= 0) {
    lines[index] = { product_id: productId, quantity: next };
  } else {
    lines.push({ product_id: productId, quantity: next });
  }
  commit(lines);
  return { quantity: next, capped: requested > next };
}

/** Sets a line to an exact quantity (clamped to the accepted range). */
export function setCartQuantity(productId: string, quantity: number): void {
  commit(
    getSnapshot().lines.map((line) =>
      line.product_id === productId ? { product_id: productId, quantity: clampQuantity(quantity) } : line,
    ),
  );
}

/** Removes a product from the cart. */
export function removeFromCart(productId: string): void {
  commit(getSnapshot().lines.filter((line) => line.product_id !== productId));
}

/** Empties the cart, e.g. after an order is placed. */
export function clearCart(): void {
  commit([]);
}

/** Total number of units across all lines. */
export function countItems(cart: Cart): number {
  return cart.lines.reduce((sum, line) => sum + line.quantity, 0);
}

/** Subscribes a component to the current cart. */
export function useCart(): Cart {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

const noopSubscribe = (): (() => void) => () => undefined;

/**
 * True once the component is rendering on the client after hydration.
 * Interactive controls stay disabled until then so automated browsers never
 * act on server HTML before React has attached its event handlers.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}
