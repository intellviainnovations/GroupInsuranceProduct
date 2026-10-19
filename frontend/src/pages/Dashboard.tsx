import { Link } from "react-router";
import { api } from "../api/endpoints";
import type { Approval, Dashboard as DashboardData, EnrolmentSummary } from "../api/model";
import { strings } from "../strings";
import { Card, EmptyState, ErrorState, PageHeader, Spinner, StatusBadge, useAsync } from "../ui/components";
import { formatDateTime, formatInr } from "../ui/format";

function Kpi({ label, value, tone = "slate", to }: { label: string; value: string; tone?: "slate" | "amber" | "red" | "green"; to?: string }) {
  const tones = { slate: "text-slate-900", amber: "text-amber-700", red: "text-rose-700", green: "text-emerald-700" };
  const body = (
    <div className="card h-full p-4 transition-shadow hover:shadow-md">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-lg">
      {body}
    </Link>
  ) : (
    body
  );
}

function EnrolmentQueue({ title, items, to }: { title: string; items: EnrolmentSummary[]; to: string }) {
  return (
    <Card
      title={title}
      actions={
        <Link to={to} className="text-xs font-medium text-brand-600 hover:underline">
          {strings.dashboard.viewAll}
        </Link>
      }
    >
      {items.length === 0 ? (
        <EmptyState text={strings.common.empty} />
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((e) => (
            <li key={e.enrolment_id}>
              <Link to={`/enrolments/${e.enrolment_id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-slate-50">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{e.insured_name}</p>
                  <p className="text-xs text-slate-500">
                    <span className="font-mono">{e.our_reference_no}</span> - {formatDateTime(e.status_changed_at)}
                  </p>
                </div>
                <StatusBadge status={e.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ApprovalQueue({ items }: { items: Approval[] }) {
  return (
    <Card
      title={strings.dashboard.queues.awaiting_my_approval}
      actions={
        <Link to="/approvals" className="text-xs font-medium text-brand-600 hover:underline">
          {strings.dashboard.viewAll}
        </Link>
      }
    >
      {items.length === 0 ? (
        <EmptyState text={strings.common.empty} />
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((a) => (
            <li key={a.approval_id}>
              <Link to={a.enrolment_id ? `/enrolments/${a.enrolment_id}` : "/approvals"} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-slate-50">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{a.insured_name ?? a.our_reference_no}</p>
                  <p className="text-xs text-slate-500">
                    {strings.approvals.actionNames[a.action]} - {a.maker.roll_no} - {formatDateTime(a.requested_at)}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function Dashboard() {
  const { data, error, loading, reload } = useAsync<DashboardData>(() => api.dashboard(), []);
  const s = strings.dashboard;
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorState error={error} onRetry={reload} />;
  const k = data.kpis;
  const q = data.queues ?? {};
  return (
    <>
      <PageHeader
        title={s.heading}
        subtitle={`${s.asOf} ${formatDateTime(data.as_of)} - ${data.scope.all_branches ? strings.nav.allBranches : `${strings.nav.branch} ${data.scope.branch_code ?? ""}`}`}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label={s.issuedToday} value={String(k.issued_today)} tone="green" />
        <Kpi label={s.issuedMonth} value={String(k.issued_month)} />
        <Kpi label={s.premiumToday} value={formatInr(k.gross_premium_today)} />
        <Kpi label={s.premiumMonth} value={formatInr(k.gross_premium_month)} />
        <Kpi label={s.inProcess} value={String(k.in_process)} to="/enrolments?status=APPROVED&status=PROPOSAL_CREATED&status=PAYMENT_PENDING&status=PAYMENT_FAILED&status=PAID" />
        <Kpi label={s.drafts} value={String(k.drafts)} to="/enrolments?status=DRAFT" />
        <Kpi label={s.pendingApprovals} value={String(k.pending_approvals)} tone={k.pending_approvals > 0 ? "amber" : "slate"} />
        <Kpi label={s.needsAttention} value={String(k.needs_attention)} tone={k.needs_attention > 0 ? "red" : "slate"} />
      </div>
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {q.awaiting_my_approval && <ApprovalQueue items={q.awaiting_my_approval} />}
        {q.needs_attention && <EnrolmentQueue title={s.queues.needs_attention} items={q.needs_attention} to="/attention" />}
        {q.my_drafts && <EnrolmentQueue title={s.queues.my_drafts} items={q.my_drafts} to="/enrolments?status=DRAFT&mine=true" />}
        {q.in_process && <EnrolmentQueue title={s.queues.in_process} items={q.in_process} to="/enrolments?status=APPROVED&status=PROPOSAL_CREATED&status=PAYMENT_PENDING&status=PAYMENT_FAILED&status=PAID" />}
        {q.recently_issued && <EnrolmentQueue title={s.queues.recently_issued} items={q.recently_issued} to="/enrolments?status=ISSUED" />}
      </div>
    </>
  );
}
