"use client";
import { useCallback, useEffect, useState } from "react";
import { workspaceFetch } from "./pharmaApi";
import { ApiErrorState } from "./PharmaScopeShell";
export default function RecordHistory({ recordId }: { recordId: string }) {
  const [observations, setObservations] = useState<any[]>([]);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(
    () =>
      workspaceFetch<{ items: any[] }>(`/records/${recordId}/observations?limit=100`)
        .then((result) => {
          setObservations(result.items);
          setError(null);
        })
        .catch(setError),
    [recordId]
  );
  useEffect(() => {
    load();
  }, [load]);
  return (
    <details style={{ marginTop: 20 }}>
      <summary>观察记录与原始快照</summary>
      {error ? (
        <ApiErrorState error={error} onRetry={load} />
      ) : observations.length ? (
        <>
          <p>当前页最多 100 条观察，重复内容保留观察序号。</p>
          {observations.map((item) => (
            <div className="ps-source-row" key={item.id}>
              <span>
                #{item.observation_seq} · {item.outcome} · {item.fetched_at}
              </span>
              <button
                className="ps-btn tiny"
                onClick={() =>
                  workspaceFetch(`/snapshots/${item.snapshot_id}`).then(setSnapshot).catch(setError)
                }
              >
                查看快照
              </button>
            </div>
          ))}
          {snapshot && <pre className="ps-json">{JSON.stringify(snapshot, null, 2)}</pre>}
        </>
      ) : (
        <p>尚无观察记录。</p>
      )}
    </details>
  );
}
