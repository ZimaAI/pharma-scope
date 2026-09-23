"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import PharmaScopeShell, { ApiErrorState } from "@/components/pharma/PharmaScopeShell";
import {
  createResearchRun,
  Drug,
  getDrugs,
  IS_REPLAY_MODE,
  formatApiError,
  mutationKey,
} from "@/components/pharma/pharmaApi";
export default function NewResearchPage() {
  const router = useRouter();
  const [question, setQuestion] = useState("整理临床试验登记变化，列出前后证据，并说明资料缺口。");
  const [drugs, setDrugs] = useState<Drug[]>([]);
  const [drug, setDrug] = useState("");
  const [days, setDays] = useState(30);
  const [sources, setSources] = useState(["ctgov", "pubmed"]);
  const [budget, setBudget] = useState({
    max_tool_calls: 20,
    max_model_calls: 4,
    max_records: 100,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState<unknown>(null);
  const submission = useRef<{ signature: string; key: string }>();
  const load = () => {
    setLoadError(null);
    getDrugs()
      .then((items) => {
        setDrugs(items);
        const selected = new URLSearchParams(window.location.search).get("drug_id");
        setDrug(items.find((item) => item.id === selected)?.id || items[0]?.id || "");
      })
      .catch(setLoadError);
  };
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("question");
    if (initial) setQuestion(initial);
    load();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim().length < 10) {
      setError("研究问题至少需要 10 个字符。");
      return;
    }
    if (!drug || !sources.length) {
      setError("请选择研究对象和至少一个来源。");
      return;
    }
    setSubmitting(true);
    setError("");
    const signature = JSON.stringify({ question, drug, days, sources, budget });
    if (submission.current?.signature !== signature)
      submission.current = { signature, key: mutationKey() };
    try {
      const run = await createResearchRun(question.trim(), [drug], {
        timeRangeDays: days,
        idempotencyKey: submission.current.key,
        sources,
        budget,
      });
      router.push(`/research/detail/?id=${encodeURIComponent(run.id)}`);
    } catch (failure) {
      setError(formatApiError(failure));
      setSubmitting(false);
    }
  }
  return (
    <PharmaScopeShell
      title="新建研究"
      description="定义问题、来源和调用预算，提交可恢复的研究任务。"
    >
      <form className="ps-grid-2" onSubmit={submit}>
        <section className="ps-card">
          <div className="ps-card-head">
            <h2>研究问题</h2>
          </div>
          <div className="ps-card-body">
            <label className="ps-form-label" htmlFor="question">
              你想了解什么？
            </label>
            <textarea
              id="question"
              className="ps-input ps-textarea"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              maxLength={4000}
              required
              minLength={10}
            />
            <small className="ps-form-help">聚焦登记变化、资料覆盖或证据核对。</small>
            {error && (
              <p className="ps-form-error" role="alert">
                {error}
              </p>
            )}
            <div className="ps-form-actions">
              <Link href="/" className="ps-btn">
                取消
              </Link>
              <button
                className="ps-btn primary"
                disabled={submitting || !!loadError || !drug || !sources.length}
              >
                {submitting ? "创建中…" : "开始研究 →"}
              </button>
            </div>
          </div>
        </section>
        <div className="ps-stack">
          <section className="ps-card">
            <div className="ps-card-head">
              <h2>研究范围与预算</h2>
            </div>
            <div className="ps-card-body">
              {loadError ? (
                <ApiErrorState error={loadError} onRetry={load} />
              ) : (
                <>
                  <label className="ps-form-label" htmlFor="drug">
                    研究对象
                  </label>
                  <select
                    id="drug"
                    className="ps-input"
                    value={drug}
                    onChange={(event) => setDrug(event.target.value)}
                  >
                    {drugs.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.development_code || item.display_name}
                      </option>
                    ))}
                  </select>
                  {!drugs.length && <Link href="/drugs">先建立药物档案</Link>}
                  <label className="ps-form-label" htmlFor="range">
                    时间窗口
                  </label>
                  <select
                    id="range"
                    className="ps-input"
                    value={days}
                    onChange={(event) => setDays(Number(event.target.value))}
                  >
                    <option value={7}>过去 7 天</option>
                    <option value={30}>过去 30 天</option>
                    <option value={90}>过去 90 天</option>
                    <option value={365}>过去 365 天</option>
                  </select>
                  <div className="ps-divider" />
                  {[
                    ["ctgov", "ClinicalTrials.gov"],
                    ["pubmed", "PubMed"],
                  ].map(([value, label]) => (
                    <label className="ps-check" key={value}>
                      <input
                        type="checkbox"
                        checked={sources.includes(value)}
                        onChange={(event) =>
                          setSources(
                            event.target.checked
                              ? [...sources, value]
                              : sources.filter((item) => item !== value)
                          )
                        }
                      />{" "}
                      {label}
                    </label>
                  ))}
                  <div className="ps-form-grid">
                    {(
                      [
                        ["max_tool_calls", "工具调用预算", 40],
                        ["max_model_calls", "模型调用预算", 10],
                        ["max_records", "记录数预算", 200],
                      ] as const
                    ).map(([key, label, max]) => (
                      <label key={key}>
                        {label}
                        <input
                          className="ps-input"
                          aria-label={label}
                          type="number"
                          min={1}
                          max={max}
                          required
                          value={budget[key]}
                          onChange={(event) =>
                            setBudget({ ...budget, [key]: Number(event.target.value) })
                          }
                        />
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>
          <section className="ps-card">
            <div className="ps-card-body">
              <div className="ps-callout">
                {IS_REPLAY_MODE
                  ? "REPLAY 模式通过演示 API 使用离线 fixtures，不调用真实来源或模型。"
                  : "LIVE 使用真实来源和模型；失败原因、已完成步骤和资料缺口将保留在运行记录。"}
              </div>
            </div>
          </section>
        </div>
      </form>
    </PharmaScopeShell>
  );
}
