"use client";
import { FormEvent, useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import {
  Drug,
  getDrugs,
  getSubscriptions,
  Subscription,
  workspaceFetch,
  jsonBody,
  mutationKey,
} from "@/components/pharma/pharmaApi";
export default function SubscriptionsPage() {
  const [items, setItems] = useState<Subscription[]>([]);
  const [drugs, setDrugs] = useState<Drug[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [drug, setDrug] = useState("");
  const [frequency, setFrequency] = useState("weekly");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [localTime, setLocalTime] = useState("09:00");
  const [weekday, setWeekday] = useState(1);
  const [message, setMessage] = useState("");
  const [deliveries, setDeliveries] = useState<any[]>([]);
  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      getSubscriptions(),
      getDrugs(),
      workspaceFetch<{ items: any[] }>("/deliveries?limit=100"),
    ])
      .then(([rows, objects, history]) => {
        setItems(rows);
        setDrugs(objects);
        setDrug((current) => current || objects[0]?.id || "");
        setDeliveries(history.items);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(load, []);
  const schedule = {
    frequency,
    timezone,
    local_time: localTime,
    weekday: frequency === "weekly" ? weekday : null,
  };
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workspaceFetch(
        "/subscriptions",
        jsonBody({
          name,
          drug_ids: [drug],
          source_allowlist: ["ctgov", "pubmed"],
          schedule,
          channels: ["in_app"],
          enabled: true,
        })
      );
      setShowForm(false);
      setName("");
      load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function preview() {
    setBusy(true);
    try {
      const result: any = await workspaceFetch("/subscriptions/preview", jsonBody({ schedule }));
      setMessage(
        `下次执行时间：${result.occurrences.map((item: any) => `${item.local} (${item.utc})`).join("；")}`
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function change(item: Subscription, trigger: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (trigger) {
        const result: any = await workspaceFetch(`/subscriptions/${item.id}/trigger`, {
          method: "POST",
          headers: { "Idempotency-Key": mutationKey() },
        });
        setMessage(`已创建调度任务 ${result.id} · ${result.state}。审核发布后才投递。`);
      } else {
        await workspaceFetch(
          `/subscriptions/${item.id}`,
          jsonBody({ enabled: !item.enabled }, "PATCH", { "If-Match": String(item.revision) })
        );
        load();
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PharmaScopeShell
      title="我的订阅"
      description="按 IANA 时区调度研究；审核发布后发送站内通知。"
      actions={
        <button className="ps-btn primary" data-guest-mutation onClick={() => setShowForm(!showForm)}>
          ＋ 新建订阅
        </button>
      }
    >
      {!!error && <ApiErrorState error={error} onRetry={load} />}
      {message && (
        <div className="ps-callout" role="status">
          {message}
        </div>
      )}
      {showForm && (
        <form className="ps-card ps-card-body" data-guest-mutation onSubmit={create}>
          <h2>新建订阅</h2>
          <div className="ps-form-grid">
            <label>
              订阅名称
              <input
                aria-label="订阅名称"
                className="ps-input"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              研究对象
              <select
                aria-label="订阅研究对象"
                className="ps-input"
                required
                value={drug}
                onChange={(e) => setDrug(e.target.value)}
              >
                {drugs.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              频率
              <select
                aria-label="频率"
                className="ps-input"
                value={frequency}
                onChange={(e) => setFrequency(e.target.value)}
              >
                <option value="daily">每日</option>
                <option value="weekly">每周</option>
              </select>
            </label>
            <label>
              IANA 时区
              <input
                aria-label="IANA 时区"
                className="ps-input"
                required
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
            </label>
            <label>
              当地时间
              <input
                aria-label="当地时间"
                className="ps-input"
                type="time"
                required
                value={localTime}
                onChange={(e) => setLocalTime(e.target.value)}
              />
            </label>
            {frequency === "weekly" && (
              <label>
                星期
                <select
                  aria-label="星期"
                  className="ps-input"
                  value={weekday}
                  onChange={(e) => setWeekday(Number(e.target.value))}
                >
                  {[1, 2, 3, 4, 5, 6, 7].map((day) => (
                    <option key={day} value={day}>
                      星期 {day}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="ps-form-actions">
            <button type="button" className="ps-btn" disabled={busy} onClick={preview}>
              预览时间
            </button>
            <button className="ps-btn primary" disabled={busy || !drug}>
              保存订阅
            </button>
          </div>
        </form>
      )}
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>订阅列表</h2>
          <span>{items.filter((item) => item.enabled).length} 个启用</span>
        </div>
        <div className="ps-card-body">
          {loading ? (
            <p>加载中…</p>
          ) : items.length === 0 ? (
            <p>尚未建立订阅。</p>
          ) : (
            items.map((item) => (
              <div className="ps-subscription" key={item.id}>
                <div>
                  <h3>{item.name}</h3>
                  <small>
                    {item.schedule.frequency === "weekly" ? "每周" : "每日"} ·{" "}
                    {item.schedule.timezone} · {item.schedule.local_time}
                  </small>
                  <p>下次：{item.next_run_at || "暂停"}</p>
                </div>
                <StatusBadge
                  status={item.enabled ? "已启用" : "已暂停"}
                  tone={item.enabled ? "success" : "warning"}
                />
                <button className="ps-btn tiny" data-guest-mutation disabled={busy} onClick={() => change(item, false)}>
                  {item.enabled ? "暂停" : "启用"}
                </button>
                <button className="ps-btn tiny" data-guest-mutation disabled={busy} onClick={() => change(item, true)}>
                  立即生成
                </button>
              </div>
            ))
          )}
        </div>
      </section>
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>投递记录</h2>
          <button className="ps-btn tiny" onClick={load}>
            刷新
          </button>
        </div>
        <div className="ps-card-body">
          {deliveries.length ? (
            deliveries.map((delivery) => (
              <p key={delivery.id}>
                {delivery.id} · {delivery.channel} · {delivery.state} {delivery.error_code || ""}
              </p>
            ))
          ) : (
            <p>暂无投递记录。邮件需管理员配置 SMTP 并显式启用发送，默认 dry-run。</p>
          )}
        </div>
      </section>
    </PharmaScopeShell>
  );
}
