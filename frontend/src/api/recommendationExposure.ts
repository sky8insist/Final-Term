/** Delivery is not exposure: require at least half of a card inside a visible page. */
export function observeRecommendationImpressions(
  root: HTMLElement,
  report: (id: string) => Promise<unknown>,
  page: Pick<Document, 'visibilityState' | 'addEventListener' | 'removeEventListener'> = document,
  Observer: typeof IntersectionObserver | undefined = globalThis.IntersectionObserver,
) {
  if (!Observer) return () => {};
  const visible = new Map<Element, boolean>();
  const recorded = new Set<string>();
  const pending = new Set<string>();
  let stopped = false;
  const flush = () => {
    if (stopped || page.visibilityState !== 'visible') return;
    for (const [element, qualifies] of visible) {
      const id = element.getAttribute('data-recommendation-id');
      if (!qualifies || !id || recorded.has(id) || pending.has(id)) continue;
      pending.add(id);
      void report(id).then(() => recorded.add(id)).catch(() => {
        // A later visibility/observer notification may retry; SQL deduplicates network replays.
      }).finally(() => pending.delete(id));
    }
  };
  const observer = new Observer(entries => {
    for (const entry of entries) visible.set(entry.target, entry.isIntersecting && entry.intersectionRatio >= 0.5);
    flush();
  }, { threshold: [0, 0.5] });
  root.querySelectorAll('[data-recommendation-id]').forEach(element => observer.observe(element));
  page.addEventListener('visibilitychange', flush);
  return () => { stopped = true; observer.disconnect(); page.removeEventListener('visibilitychange', flush); };
}
