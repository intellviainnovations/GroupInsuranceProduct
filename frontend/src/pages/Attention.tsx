import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/endpoints";
import type { AttentionReason, EnrolmentPage, EnrolmentSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { strings } from "../strings";
import { Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, useAsync } from "../ui/components";
import { formatDateTime, formatInr } from "../ui/format";
import { useAction } from "../ui/useAction";
import { Pagination } from "./EnrolmentList";

const s = strings.attention;
const REASONS: AttentionReason[] = ["POSTING_UNKNOWN", "ISSUE_RETRIES_EXHAUSTED", "ISSUE_UNKNOWN", "PROPOSAL_UNKNOWN", "CANCEL_UNKNOWN"];

function ConfirmDialog({ item, onClose, onDone }: { item: EnrolmentSummary; onClose: () => void; onDone: () => void }) {
  const [target, setTarget] = useState<"PAID" | "PAYMENT_FAILED" | "">("");
  const [note, setNote] = useState("");
  const [evidence, setEvidence] = useState("");
  const { run, outcomeToast, busy } = useAction();

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!target) return;
    const r = await run(`confirm-${item.enrolment_id}`, async (k) => {
      // The resolve body needs the current version; read it fresh.
      const detail = await api.getEnrolment(item.enrolment_id);
      return api.resolve(item.enrolment_id, { version: detail.version, action: "CONFIRM", target_status: target, note: note.trim(), evidence_ref: evidence.trim() || null }, k);
    });
    if (r) {
      outcomeToast(r, s.confirm);
      onDone();
    }
  }

  return (
    <Modal title={`${s.confirmTitle}: ${item.our_reference_no}`} onClose={onClose}>
      <form onSubmit={(ev) => void submit(ev)} className="space-y-4">
        <fieldset>
          <legend className="field-label">{s.targetStatus}</legend>
          <div className="space-y-2">
            {(["PAID", "PAYMENT_FAILED"] as const).map((t) => (
              <label key={t} className="flex items-center gap-2 text-sm">
                <input type="radio" name="target" required checked={target === t} onChange={() => setTarget(t)} className="h-4 w-4" />
                {s.targets[t]}
              </label>
            ))}
          </div>
        </fieldset>
        <Field id="cf-note" label={s.note}>
          <textarea id="cf-note" className="input" rows={3} required maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Field id="cf-evidence" label={s.evidence}>
          <input id="cf-evidence" className="input" maxLength={60} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>{strings.common.cancel}</button>
          <button type="submit" className="btn-primary" disabled={busy !== null}>{s.submitConfirm}</button>
        </div>
      </form>
    </Modal>
  );
}

export function Attention() {
  const [params, setParams] = useSearchParams();
  const { hasRole } = useAuth();
  const canAct = hasRole("OPERATIONS");
  const reason = (params.get("reason") ?? "") as AttentionReason | "";
  const page = Number(params.get("page") ?? "1") || 1;
  const { data, error, loading, reload } = useAsync<EnrolmentPage>(() => api.listAttention({ reason: reason || undefined, page, page_size: 20 }), [reason, page]);
  const { run, busy, outcomeToast } = useAction(reload);
  const [confirming, setConfirming] = useState<EnrolmentSummary | null>(null);

  async function recheck(item: EnrolmentSummary) {
    const r = await run(`recheck-${item.enrolment_id}`, async (k) => {
      const detail = await api.getEnrolment(item.enrolment_id);
      return api.resolve(item.enrolment_id, { version: detail.version, action: "RECHECK" }, k);
    });
    if (r) {
      outcomeToast(r, `${s.recheck}: ${strings.status[r.enrolment.status]}`);
      reload();
    }
  }

  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next);
  };

  return (
    <>
      <PageHeader title={s.heading} subtitle={s.help} />
      <Card className="mb-4">
        <div className="p-4">
          <label htmlFor="at-reason" className="field-label">{s.reasonFilter}</label>
          <select id="at-reason" className="input max-w-xs" value={reason} onChange={(e) => setFilter("reason", e.target.value)}>
            <option value="">{s.allReasons}</option>
            {REASONS.map((r) => <option key={r} value={r}>{strings.attentionReason[r]}</option>)}
          </select>
        </div>
      </Card>
      <Card>
        {loading && !data ? (
          <Spinner />
        ) : error ? (
          <div className="p-4"><ErrorState error={error} onRetry={reload} /></div>
        ) : data && data.items.length === 0 ? (
          <EmptyState text={s.empty} />
        ) : data ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="table-head">
                  <tr>
                    <th className="px-4 py-2.5">{strings.enrolments.cols.reference}</th>
                    <th className="px-4 py-2.5">{strings.enrolments.cols.insured}</th>
                    <th className="px-4 py-2.5">{strings.detail.fields.reason}</th>
                    <th className="px-4 py-2.5">{strings.enrolments.cols.status}</th>
                    <th className="px-4 py-2.5 text-right">{strings.enrolments.cols.premium}</th>
                    <th className="px-4 py-2.5">{strings.enrolments.cols.branch}</th>
                    <th className="px-4 py-2.5">{strings.detail.fields.since}</th>
                    {canAct && <th className="px-4 py-2.5" />}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((e) => (
                    <tr key={e.enrolment_id}>
                      <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">
                        <Link to={`/enrolments/${e.enrolment_id}`} className="text-brand-700 hover:underline">{e.our_reference_no}</Link>
                      </td>
                      <td className="px-4 py-2.5 font-medium">{e.insured_name}</td>
                      <td className="px-4 py-2.5">{e.attention_reason ? strings.attentionReason[e.attention_reason] : "-"}</td>
                      <td className="px-4 py-2.5"><StatusBadge status={e.status} /></td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{formatInr(e.gross_premium)}</td>
                      <td className="px-4 py-2.5">{e.branch_code}</td>
                      <td className="px-4 py-2.5 whitespace-nowrap text-slate-500">{formatDateTime(e.status_changed_at)}</td>
                      {canAct && (
                        <td className="px-4 py-2.5 whitespace-nowrap">
                          <div className="flex gap-2">
                            <button type="button" className="btn-primary px-2.5 py-1" disabled={busy !== null} onClick={() => void recheck(e)}>
                              {busy === `recheck-${e.enrolment_id}` ? strings.common.loading : s.recheck}
                            </button>
                            <button type="button" className="btn-secondary px-2.5 py-1" onClick={() => setConfirming(e)}>{s.confirm}</button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => setFilter("page", String(p))} />
          </>
        ) : null}
      </Card>
      {confirming && (
        <ConfirmDialog
          item={confirming}
          onClose={() => setConfirming(null)}
          onDone={() => {
            setConfirming(null);
            reload();
          }}
        />
      )}
    </>
  );
}
