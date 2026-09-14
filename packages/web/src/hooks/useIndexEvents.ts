import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { IndexStatus } from "../api/types";

/**
 * Subscribe to the backend's SSE stream so the list reflects sessions as they
 * are indexed, and updates while an agent is still writing to its store.
 */
export function useIndexEvents(): IndexStatus | null {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<IndexStatus | null>(null);

  useEffect(() => {
    const source = new EventSource("/api/events");
    let pending = false;

    // Indexing emits one event per session; refetching on each would thrash.
    function scheduleRefresh() {
      if (pending) return;
      pending = true;
      setTimeout(() => {
        pending = false;
        queryClient.invalidateQueries({ queryKey: ["sessions"] });
        queryClient.invalidateQueries({ queryKey: ["providers"] });
        queryClient.invalidateQueries({ queryKey: ["projects"] });
      }, 600);
    }

    source.addEventListener("index", (event) => {
      try {
        const next = JSON.parse((event as MessageEvent).data) as IndexStatus;
        setStatus(next);
        if (!next.running) scheduleRefresh();
      } catch {
        // A malformed frame should not kill the stream.
      }
    });
    source.addEventListener("session", scheduleRefresh);

    return () => source.close();
  }, [queryClient]);

  return status;
}
