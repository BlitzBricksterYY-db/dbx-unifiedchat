/**
 * Identity selector for use with Suspense hooks.
 * Usage: const { data } = useListCatalogsSuspense(selector());
 */
export const selector = <T extends unknown>() => (data: T) => data;
