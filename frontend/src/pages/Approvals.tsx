import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/endpoints";
import type { Approval, ApprovalAction, ApprovalPage, ApprovalStatus } from "../api/types";
import { strings } from "../strings";
import { Card, EmptyState, ErrorState, PageHeader, Pill, Spinner, useAsync } from "../ui/components";
import { formatDateTime } from "../ui/format";
import { DecisionDialog } from "./DecisionDialog";
import { Pagination } from "./EnrolmentList";

const s = strings.approvals;
const ACTIONS: ApprovalAction[] = ["SUBMIT_SALE", "CANCEL_CERTIFICATE", "ATTENTION_RESOLVE"];
const STATUSES: ApprovalStatus[] = ["PENDING", "APPROVED", "REJECTED", "WITHDRAWN"];

export function Approvals() {
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "PENDING") as ApprovalStatus;
  const action = (params.get("action") ?? "") as ApprovalAction | "";
  const page = Number(params.get("page") ?? "1") || 1;
  const { data, error, loading, reload } = useAsync<ApprovalPage>(
    () => api.listApprovals({ status, action: action || undefined, page, page_size: 20 }),
    [status, action, page],
  );
  const [decision, setDecision] = useState<{ approval: Approval; kind: "approve" | "reject" } | null>(null);

  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    next.delete("page");
    setParams(next);
  };

  return (
    <>
      <PageHeader title={s.heading} />
      <Card className="mb-4">
        <div className="flex flex-wrap gap-4 p-4">
          <div>
            <label htmlFor="ap-status" className="field-label">{s.statusFilter}</label>
            <select id="ap-status" className="input" value={status} onChange={(e) => setFilter("status", e.target.value)}>
              {STATUSES.map((st) => <option key={st} value={st}>{s.statuses[st]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="ap-action" className="field-label">{s.actionFilter}</label>
            <select id="ap-action" className="input" value={action} onChange={(e) => setFilter("action", e.target.value)}>
              <option value="">{s.allTypes}</option>
              {ACTIONS.map((a) => <option key={a} value={a}>{s.actionNames[a]}</option>)}
            </select>
          </div>
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
                    <th className="px-4 py-2.5">{s.actionFilter}</th>
                    <th className="px-4 py-2.5">{strings.detail.fields.maker}</th>
                    <th className="px-4 py-2.5">{strings.detail.fields.comment}</th>
                    <th className="px-4 py-2.5">{strings.detail.fields.when}</th>
                    <th className="px-4 py-2.5">{s.statusFilter}</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((a) => (
                    <tr key={a.approval_id} className="align-top">
                      <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">
                        {a.enrolment_id ? <Link to={`/enrolments/${a.enrolment_id}`} className="text-brand-700 hover:underline">{a.our_reference_no ?? a.enrolment_id}</Link> : a.our_reference_no}
                      </td>
                      <td className="px-4 py-2.5 font-medium">{a.insured_name ?? "-"}</td>
                      <td className="px-4 py-2.5">
                        {s.actionNames[a.action]}
                        {a.proposed_status && <p className="text-xs text-slate-500">{s.proposedStatus}: {strings.status[a.proposed_status]}</p>}
                        {a.evidence_ref && <p className="text-xs text-slate-500">{s.evidence}: {a.evidence_ref}</p>}
                      </td>
                      <td className="px-4 py-2.5">{a.maker.display_name ?? a.maker.roll_no}</td>
                      <td className="max-w-xs px-4 py-2.5 text-slate-600">
                        {a.maker_comment ?? "-"}
                        {a.checker_comment && <p className="mt-1 text-xs">{a.checker?.display_name ?? a.checker?.roll_no}: {a.checker_comment}</p>}
                      </td>
                      <td className="px-4 py-2.5 whitespace-nowrap text-slate-500">{formatDateTime(a.decided_at ?? a.requested_at)}</td>
                      <td className="px-4 py-2.5">
                        <Pill tone={a.status === "APPROVED" ? "green" : a.status === "REJECTED" ? "red" : a.status === "PENDING" ? "amber" : "slate"}>{s.statuses[a.status]}</Pill>
                      </td>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        {a.status === "PENDING" &&
                          (a.can_decide ? (
                            <div className="flex gap-2">
                              <button type="button" className="btn-primary px-2.5 py-1" onClick={() => setDecision({ approval: a, kind: "approve" })}>{s.approve}</button>
                              <button type="button" className="btn-danger px-2.5 py-1" onClick={() => setDecision({ approval: a, kind: "reject" })}>{s.reject}</button>
                            </div>
                          ) : (
                            <span className="text-xs text-slate-500">{s.cannotDecide}</span>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => setFilter("page", String(p))} />
          </>
        ) : null}
      </Card>
      {decision && (
        <DecisionDialog
          approval={decision.approval}
          decision={decision.kind}
          onClose={() => setDecision(null)}
          onDone={() => {
            setDecision(null);
            reload();
          }}
        />
      )}
    </>
  );
}
