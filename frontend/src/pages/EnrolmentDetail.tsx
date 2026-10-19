import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/endpoints";
import { labelFor, loadRefCodes } from "../api/reference";
import type { ActionResult, AllowedAction, Approval, EnrolmentDetail as Detail, RefCodes } from "../api/model";
import { strings } from "../strings";
import { Card, DefList, EmptyState, ErrorState, Field, Modal, Pill, Spinner, StatusBadge, useAsync } from "../ui/components";
import { formatDate, formatDateTime, formatInr, show } from "../ui/format";
import { IconAlert, IconChevronLeft, IconDownload } from "../ui/icons";
import { useAction } from "../ui/useAction";
import { DecisionDialog } from "./DecisionDialog";

type DialogKind = "submit" | "consent" | "abandon" | "cancel" | null;

const d = strings.detail;
const f = strings.detail.fields;

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="table-head">
          <tr>
            {head.map((h) => (
              <th key={h} className="px-4 py-2">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className="px-4 py-2 align-top">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function postingTone(s: string): "green" | "red" | "amber" | "slate" {
  return s === "SUCCESS" ? "green" : s === "FAILED" ? "red" : s === "UNKNOWN" || s === "PENDING" ? "amber" : "slate";
}

export function EnrolmentDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { data: e, error, loading, reload, setData } = useAsync<Detail>(() => api.getEnrolment(id), [id]);
  const codes = useAsync<RefCodes>(() => loadRefCodes(), []);
  const { run, busy, outcomeToast, toast } = useAction(reload);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [decision, setDecision] = useState<{ approval: Approval; kind: "approve" | "reject" } | null>(null);

  if (loading && !e) return <Spinner />;
  if (error || !e) return <ErrorState error={error} onRetry={reload} />;
  const rc = codes.data ?? undefined;
  const can = (a: AllowedAction) => e.allowed_actions.includes(a);
  const v = { version: e.version };

  async function act(intent: string, title: string, fn: (k: string) => Promise<ActionResult>) {
    const r = await run(intent, fn);
    if (r) {
      setData(r.enrolment);
      outcomeToast(r, title);
      setDialog(null);
    }
  }

  async function download() {
    const r = await run("certificate", () => api.certificate(e!.enrolment_id));
    if (!r) return;
    const url = URL.createObjectURL(r.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = r.fileName ?? `${e!.certificate?.certificate_no ?? "certificate"}.pdf`.replace(/[\\/]/g, "-");
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  async function copy() {
    const r = await run("copy", (k) => api.copy(e!.enrolment_id, k));
    if (r) {
      toast.push({ tone: "success", title: d.copied });
      void navigate(`/enrolments/${r.enrolment_id}`);
    }
  }

  const ins = e.insured;
  const cbs = new Set(ins.cbs_sourced_fields);
  const tagged = (field: string, value: ReactNode): ReactNode => (
    <span className="inline-flex items-center gap-1.5">
      {value}
      {cbs.has(field) && <Pill tone="blue">{d.cbsSourced}</Pill>}
    </span>
  );
  const pendingApprovals = e.approvals.filter((a) => a.status === "PENDING");
  const isBusy = busy !== null;

  const buttons: ReactNode[] = [];
  if (can("EDIT")) buttons.push(<Link key="edit" to={`/sale/${e.enrolment_id}`} className="btn-secondary">{strings.actions.EDIT}</Link>);
  if (can("SUBMIT")) buttons.push(<button key="submit" type="button" className="btn-primary" disabled={isBusy} onClick={() => setDialog("submit")}>{strings.actions.SUBMIT}</button>);
  if (can("CREATE_PROPOSAL"))
    buttons.push(
      <button key="prop" type="button" className="btn-primary" disabled={isBusy} onClick={() => { if (window.confirm(d.confirmProposal)) void act("proposal", strings.actions.CREATE_PROPOSAL, (k) => api.proposal(e.enrolment_id, v, k)); }}>
        {busy === "proposal" ? strings.common.loading : strings.actions.CREATE_PROPOSAL}
      </button>,
    );
  if (can("RECORD_CONSENT")) buttons.push(<button key="consent" type="button" className="btn-primary" disabled={isBusy} onClick={() => setDialog("consent")}>{strings.actions.RECORD_CONSENT}</button>);
  if (can("POST_PAYMENT"))
    buttons.push(
      <button key="pay" type="button" className="btn-primary" disabled={isBusy} onClick={() => { if (window.confirm(d.confirmPayment)) void act("payment", strings.actions.POST_PAYMENT, (k) => api.payment(e.enrolment_id, v, k)); }}>
        {busy === "payment" ? strings.common.loading : strings.actions.POST_PAYMENT}
      </button>,
    );
  if (can("RETRY_ISSUE"))
    buttons.push(
      <button key="policy" type="button" className="btn-primary" disabled={isBusy} onClick={() => void act("policy", strings.actions.RETRY_ISSUE, (k) => api.policy(e.enrolment_id, v, k))}>
        {busy === "policy" ? strings.common.loading : strings.actions.RETRY_ISSUE}
      </button>,
    );
  if (can("DOWNLOAD_CERTIFICATE"))
    buttons.push(
      <button key="cert" type="button" className="btn-primary" disabled={isBusy} onClick={() => void download()}>
        <IconDownload className="h-4 w-4" />
        {strings.actions.DOWNLOAD_CERTIFICATE}
      </button>,
    );
  if (can("REOPEN")) buttons.push(<button key="reopen" type="button" className="btn-secondary" disabled={isBusy} onClick={() => void act("reopen", strings.actions.REOPEN, () => api.reopen(e.enrolment_id, v))}>{strings.actions.REOPEN}</button>);
  if (can("COPY")) buttons.push(<button key="copy" type="button" className="btn-secondary" disabled={isBusy} onClick={() => void copy()}>{strings.actions.COPY}</button>);
  if (can("REQUEST_CANCELLATION")) buttons.push(<button key="cancel" type="button" className="btn-secondary" disabled={isBusy} onClick={() => setDialog("cancel")}>{strings.actions.REQUEST_CANCELLATION}</button>);
  if (can("RESOLVE")) buttons.push(<Link key="resolve" to="/attention" className="btn-secondary">{strings.actions.RESOLVE}</Link>);
  if (can("ABANDON")) buttons.push(<button key="abandon" type="button" className="btn-danger" disabled={isBusy} onClick={() => setDialog("abandon")}>{strings.actions.ABANDON}</button>);

  return (
    <>
      <Link to="/enrolments" className="mb-3 inline-flex items-center gap-1 text-sm text-brand-700 hover:underline">
        <IconChevronLeft className="h-4 w-4" />
        {d.back}
      </Link>
      <div className="card mb-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold text-slate-900">{[ins.first_name, ins.middle_name, ins.last_name].filter(Boolean).join(" ") || e.our_reference_no}</h1>
              <StatusBadge status={e.status} />
            </div>
            <p className="mt-1 text-sm text-slate-500">
              <span className="font-mono">{e.our_reference_no}</span> - {d.branch} {e.branch.code} - {d.createdBy} {e.created_by.display_name ?? e.created_by.roll_no} - {d.lastChange} {formatDateTime(e.status_changed_at)} - {d.version} {e.version}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          {buttons.length > 0 ? buttons : <p className="text-sm text-slate-500">{d.noActions}</p>}
        </div>
      </div>

      {e.attention && (
        <div role="alert" className="mb-4 flex items-center gap-3 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
          <IconAlert className="h-5 w-5" />
          {d.attention}: {strings.attentionReason[e.attention.reason]} - {d.fields.since} {formatDateTime(e.attention.since)}
        </div>
      )}
      {e.premium && !e.premium.matches_rate && (
        <div role="alert" className="mb-4 flex items-center gap-3 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
          <IconAlert className="h-5 w-5" />
          {d.mismatch}
        </div>
      )}

      {pendingApprovals.length > 0 && (
        <Card title={d.approvals} className="mb-4">
          <ul className="divide-y divide-slate-100">
            {pendingApprovals.map((a) => (
              <li key={a.approval_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                <div>
                  <p className="font-medium">{strings.approvals.actionNames[a.action]}</p>
                  <p className="text-xs text-slate-500">
                    {f.maker} {a.maker.display_name ?? a.maker.roll_no} - {formatDateTime(a.requested_at)}
                    {a.maker_comment ? ` - ${a.maker_comment}` : ""}
                  </p>
                </div>
                {a.can_decide ? (
                  <div className="flex gap-2">
                    <button type="button" className="btn-primary" onClick={() => setDecision({ approval: a, kind: "approve" })}>{strings.approvals.approve}</button>
                    <button type="button" className="btn-danger" onClick={() => setDecision({ approval: a, kind: "reject" })}>{strings.approvals.reject}</button>
                  </div>
                ) : (
                  <Pill tone="amber">{strings.approvals.cannotDecide}</Pill>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title={d.insured}>
            <DefList
              items={[
                [f.name, tagged("first_name", [ins.first_name, ins.middle_name, ins.last_name].filter(Boolean).join(" ") || "-")],
                [f.gender, tagged("gender_code", labelFor(rc?.GENDER, ins.gender_code))],
                [f.dob, tagged("date_of_birth", formatDate(ins.date_of_birth))],
                [f.mobile, tagged("mobile", show(ins.mobile))],
                [f.email, tagged("email", show(ins.email))],
                [f.address, tagged("address1", [ins.address1, ins.address2].filter(Boolean).join(", ") || "-")],
                [f.city, tagged("city", show(ins.city))],
                [f.state, tagged("state_code", labelFor(rc?.STATE, ins.state_code))],
                [f.pincode, tagged("pincode", show(ins.pincode))],
                [f.occupation, tagged("occupation_code", labelFor(rc?.OCCUPATION, ins.occupation_code))],
                [f.disability, ins.any_disability === undefined ? "-" : ins.any_disability ? `${strings.common.yes}${ins.disability_description ? ` - ${ins.disability_description}` : ""}` : strings.common.no],
              ]}
            />
          </Card>
          <Card title={d.nominees}>
            {e.nominees.length === 0 ? (
              <EmptyState text={d.noNominees} />
            ) : (
              <Table
                head={[f.name, f.relation, f.share, f.dob, f.mobile]}
                rows={e.nominees.map((n) => [n.name, labelFor(rc?.RELATION, n.relation_code), `${n.share_percent}%`, formatDate(n.date_of_birth), show(n.mobile)])}
              />
            )}
          </Card>
          <Card title={d.plan}>
            <DefList
              items={[
                [strings.enrolments.cols.plan, e.plan ? `${e.plan.plan_code} - ${e.plan.name}` : "-"],
                [f.sumInsured, formatInr(e.plan?.rate?.sum_insured)],
                [f.term, show(e.plan?.rate?.policy_term_days)],
                [`${d.planRate}: ${f.gross}`, (
                  <span className="inline-flex items-center gap-1.5">
                    {formatInr(e.plan?.rate?.gross_premium)}
                    {e.plan?.rate?.synthetic && <Pill tone="amber">{strings.sale.syntheticRate}</Pill>}
                  </span>
                )],
                [`${d.premiumFromInsurer}: ${f.net}`, formatInr(e.premium?.net_premium)],
                [`${d.premiumFromInsurer}: ${f.gst}`, formatInr(e.premium?.gst_amount)],
                [`${d.premiumFromInsurer}: ${f.gross}`, (
                  <span className="inline-flex items-center gap-1.5 font-semibold">
                    {formatInr(e.premium?.gross_premium)}
                    {e.premium && <Pill tone={e.premium.matches_rate ? "green" : "red"}>{e.premium.matches_rate ? d.matchesRate : d.mismatch}</Pill>}
                  </span>
                )],
              ]}
            />
          </Card>
          <Card title={d.postings}>
            {e.postings.length === 0 ? (
              <EmptyState text={d.noPostings} />
            ) : (
              <Table
                head={[f.kind, f.amount, f.status, f.requestRef, f.tranId, f.attempt, f.error, f.when]}
                rows={e.postings.map((p) => [p.kind, formatInr(p.amount), <Pill tone={postingTone(p.status)}>{p.status}</Pill>, <span className="font-mono text-xs">{p.cbs_request_ref}</span>, show(p.cbs_tran_id_masked), p.attempt_no, show(p.error_code), formatDateTime(p.requested_at)])}
              />
            )}
          </Card>
          <Card title={d.insurerCalls}>
            {e.insurer_calls.length === 0 ? (
              <EmptyState text={d.noCalls} />
            ) : (
              <Table
                head={[f.operation, f.attempt, f.status, f.error, f.when, f.duration]}
                rows={e.insurer_calls.map((c) => [c.operation, c.attempt_no, <Pill tone={postingTone(c.status === "SUCCESS" ? "SUCCESS" : c.status === "UNKNOWN" ? "UNKNOWN" : "FAILED")}>{c.status}</Pill>, show(c.error_category), formatDateTime(c.started_at), show(c.duration_ms)])}
              />
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title={d.customer}>
            <DefList
              items={[
                [f.cif, <span className="font-mono">{e.customer.cif_masked}</span>],
                [d.debitAccount, <span className="font-mono">{e.debit_account.account_no_masked}</span>],
                [f.accountType, show(e.debit_account.account_type)],
                [f.status, show(e.debit_account.account_status)],
                [d.cbsFetched, formatDateTime(e.customer.cbs_fetched_at)],
              ]}
            />
          </Card>
          <Card title={`${d.proposal} / ${d.consent} / ${d.certificate}`}>
            <DefList
              items={[
                [f.proposalNo, e.proposal ? <span className="font-mono">{e.proposal.insurer_proposal_no}</span> : "-"],
                [d.consent, e.consent ? `${labelFor(rc?.CONSENT_METHOD, e.consent.method)} - ${e.consent.reference}` : "-"],
                [f.consentedAt, formatDateTime(e.consent?.consented_at)],
                [f.certificateNo, e.certificate ? <span className="font-mono">{e.certificate.certificate_no}</span> : "-"],
                [f.riskStart, formatDate(e.certificate?.risk_start_date)],
                [f.riskEnd, formatDate(e.certificate?.risk_end_date)],
              ]}
            />
          </Card>
          {e.cancellation && (
            <Card title={d.cancellation}>
              <DefList
                items={[
                  [f.reason, labelFor(rc?.CANCEL_REASON, e.cancellation.reason_code)],
                  [f.status, e.cancellation.status],
                  [f.maker, e.cancellation.requested_by.display_name ?? e.cancellation.requested_by.roll_no],
                  [f.refund, formatInr(e.cancellation.refund_amount)],
                ]}
              />
            </Card>
          )}
          <Card title={d.timeline}>
            <ol className="relative space-y-4 p-4 before:absolute before:top-5 before:bottom-5 before:left-[1.4rem] before:w-px before:bg-slate-200">
              {[...e.status_history].reverse().map((h, i) => (
                <li key={i} className="relative flex gap-3 pl-1">
                  <span className={`relative z-10 mt-1 h-3 w-3 shrink-0 rounded-full ring-4 ring-white ${i === 0 ? "bg-brand-600" : "bg-slate-300"}`} />
                  <div className="text-sm">
                    <StatusBadge status={h.to_status} />
                    <p className="mt-1 text-xs text-slate-500">
                      {formatDateTime(h.changed_at)} - {h.actor ? h.actor.display_name ?? h.actor.roll_no : strings.common.system}
                    </p>
                    {h.reason && <p className="mt-0.5 text-xs text-slate-700">{h.reason}</p>}
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>

      {dialog === "submit" && <SubmitDialog e={e} onClose={() => setDialog(null)} onAct={act} />}
      {dialog === "consent" && <ConsentDialog e={e} codes={rc} onClose={() => setDialog(null)} onAct={act} />}
      {dialog === "abandon" && <AbandonDialog e={e} onClose={() => setDialog(null)} onAct={act} />}
      {dialog === "cancel" && <CancelDialog e={e} codes={rc} onClose={() => setDialog(null)} onAct={act} />}
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

type Act = (intent: string, title: string, fn: (k: string) => Promise<ActionResult>) => Promise<void>;

function DialogButtons({ onClose, label, danger = false }: { onClose: () => void; label: string; danger?: boolean }) {
  return (
    <div className="flex justify-end gap-2">
      <button type="button" className="btn-secondary" onClick={onClose}>{strings.common.cancel}</button>
      <button type="submit" className={danger ? "btn-danger" : "btn-primary"}>{label}</button>
    </div>
  );
}

export function SubmitDialog({ e, onClose, onAct }: { e: Detail; onClose: () => void; onAct: Act }) {
  const [comment, setComment] = useState("");
  const s = d.submitDialog;
  return (
    <Modal title={s.title} onClose={onClose}>
      <form className="space-y-4" onSubmit={(ev: FormEvent<HTMLFormElement>) => { ev.preventDefault(); void onAct("submit", strings.actions.SUBMIT, () => api.submit(e.enrolment_id, { version: e.version, comment: comment.trim() || null })); }}>
        <Field id="sub-comment" label={s.comment}>
          <textarea id="sub-comment" className="input" rows={3} maxLength={300} value={comment} onChange={(x) => setComment(x.target.value)} />
        </Field>
        <DialogButtons onClose={onClose} label={s.submit} />
      </form>
    </Modal>
  );
}

function ConsentDialog({ e, codes, onClose, onAct }: { e: Detail; codes: RefCodes | undefined; onClose: () => void; onAct: Act }) {
  const [method, setMethod] = useState("");
  const [reference, setReference] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const s = d.consentDialog;
  const amount = e.premium?.gross_premium;
  return (
    <Modal title={s.title} onClose={onClose}>
      <form
        className="space-y-4"
        autoComplete="off"
        onSubmit={(ev: FormEvent<HTMLFormElement>) => {
          ev.preventDefault();
          void onAct("consent", strings.actions.RECORD_CONSENT, () =>
            api.consent(e.enrolment_id, { version: e.version, method, reference: reference.trim(), ...(amount ? { confirmed_amount: amount } : {}) }),
          );
        }}
      >
        <Field id="c-method" label={s.method}>
          <select id="c-method" className="input" required value={method} onChange={(x) => setMethod(x.target.value)}>
            <option value="" />
            {codes?.CONSENT_METHOD.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
          </select>
        </Field>
        <Field id="c-ref" label={s.reference} hint={s.referenceHint}>
          <input id="c-ref" className="input" required maxLength={60} pattern="[A-Za-z0-9/_ \-]+" value={reference} onChange={(x) => setReference(x.target.value)} />
        </Field>
        {amount && (
          <div className="rounded-md bg-brand-50 p-3">
            <p className="text-xs font-medium text-brand-800">{s.amount}</p>
            <p className="text-2xl font-semibold text-brand-900 tabular-nums">{formatInr(amount)}</p>
            <p className="text-xs text-brand-700">{s.amountHint}</p>
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input type="checkbox" required checked={confirmed} onChange={(x) => setConfirmed(x.target.checked)} className="h-4 w-4" />
              {s.confirmAmount}
            </label>
          </div>
        )}
        <DialogButtons onClose={onClose} label={s.submit} />
      </form>
    </Modal>
  );
}

function AbandonDialog({ e, onClose, onAct }: { e: Detail; onClose: () => void; onAct: Act }) {
  const [comment, setComment] = useState("");
  const s = d.abandonDialog;
  return (
    <Modal title={s.title} onClose={onClose}>
      <form className="space-y-4" onSubmit={(ev: FormEvent<HTMLFormElement>) => { ev.preventDefault(); void onAct("abandon", strings.actions.ABANDON, (k) => api.abandon(e.enrolment_id, { version: e.version, comment: comment.trim() }, k)); }}>
        <Field id="ab-comment" label={s.comment}>
          <textarea id="ab-comment" className="input" rows={3} required maxLength={300} value={comment} onChange={(x) => setComment(x.target.value)} />
        </Field>
        <DialogButtons onClose={onClose} label={s.submit} danger />
      </form>
    </Modal>
  );
}

function CancelDialog({ e, codes, onClose, onAct }: { e: Detail; codes: RefCodes | undefined; onClose: () => void; onAct: Act }) {
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const s = d.cancelDialog;
  return (
    <Modal title={s.title} onClose={onClose}>
      <form className="space-y-4" onSubmit={(ev: FormEvent<HTMLFormElement>) => { ev.preventDefault(); void onAct("cancellation", strings.actions.REQUEST_CANCELLATION, (k) => api.cancellation(e.enrolment_id, { version: e.version, reason_code: reason, remarks: remarks.trim() || null }, k)); }}>
        <Field id="cn-reason" label={s.reason}>
          <select id="cn-reason" className="input" required value={reason} onChange={(x) => setReason(x.target.value)}>
            <option value="" />
            {codes?.CANCEL_REASON.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
          </select>
        </Field>
        <Field id="cn-remarks" label={s.remarks}>
          <textarea id="cn-remarks" className="input" rows={3} maxLength={500} value={remarks} onChange={(x) => setRemarks(x.target.value)} />
        </Field>
        <DialogButtons onClose={onClose} label={s.submit} danger />
      </form>
    </Modal>
  );
}
