import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

interface QueryStateProps<T> {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
}

export function QueryState<T>({ query, children }: QueryStateProps<T>) {
  if (query.isLoading) return <div className="state-message">Loading...</div>;
  if (query.isError) {
    return <div className="state-message state-message--error">Failed to load: {(query.error as Error).message}</div>;
  }
  if (query.data === undefined) return null;
  return <>{children(query.data)}</>;
}
