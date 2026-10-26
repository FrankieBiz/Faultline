import { useCallback, useEffect, useState } from "react";

/** Lifecycle of a client-side request. */
export type ResourceState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; message: string };

interface Settled<T> {
  key: string;
  state: Exclude<ResourceState<T>, { status: "loading" }>;
}

/**
 * Loads data on the client and exposes loading, ready, and error states plus a
 * `retry` function. Results are tagged with the key they were requested for,
 * so a stale response can never be shown for a newer request; an in-flight
 * request is aborted when the key changes or the component unmounts.
 *
 * @param key Stable identity of the request (for example the URL path).
 * @param load Fetches the value; must honor the abort signal.
 */
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
): { state: ResourceState<T>; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const requestKey = `${key}#${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setSettled({ key: requestKey, state: { status: "ready", value } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "The request failed.";
        setSettled({ key: requestKey, state: { status: "error", message } });
      },
    );
    return () => controller.abort();
    // `load` is intentionally excluded: callers pass inline functions, and the
    // request identity is fully described by `requestKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const state: ResourceState<T> = settled?.key === requestKey ? settled.state : { status: "loading" };
  return { state, retry };
}
