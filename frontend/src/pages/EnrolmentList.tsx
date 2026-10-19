import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api } from "../api/endpoints";
import { ENROLMENT_STATUSES } from "../api/model";
import type { EnrolmentPage, EnrolmentStatus } from "../api/model";
import { useAuth } from "../auth/AuthContext";
import { strings } from "../strings";
import { Card, EmptyState, ErrorState, PageHeader, Spinner, StatusBadge, useAsync } from "../ui/components";
import { formatDateTime, formatInr, show } from "../ui/format";
import { IconPlus, IconSearch } from "../ui/icons";

const PAGE_SIZE = 20;

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
      <span>
        {total} {strings.common.results}
      </span>
      <div className="flex items-center gap-2">
        <button type="button" className="btn-secondary px-2.5 py-1" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          {strings.common.previous}
        </button>
        <span>
          {strings.common.page} {page} {strings.common.of} {pages}
        </span>
        <button type="button" className="btn-secondary px-2.5 py-1" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          {strings.common.next}
        </button>
      </div>
    </div>
  );
}

export function EnrolmentTable({ data, showReason = false }: { data: EnrolmentPage; showReason?: boolean }) {
  const navigate = useNavigate();
  const c = strings.enrolments.cols;
  if (data.items.length === 0) return <EmptyState text={strings.enrolments.empty} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="table-head">
          <tr>
            <th className="px-4 py-2.5">{c.reference}</th>
            <th className="px-4 py-2.5">{c.insured}</th>
            <th className="px-4 py-2.5">{c.status}</th>
            {showReason && <th className="px-4 py-2.5">{strings.detail.fields.reason}</th>}
            <th className="px-4 py-2.5">{c.plan}</th>
            <th className="px-4 py-2.5 text-right">{c.premium}</th>
            <th className="px-4 py-2.5">{c.certificate}</th>
            <th className="px-4 py-2.5">{c.branch}</th>
            <th className="px-4 py-2.5">{c.created}</th>
            <th className="px-4 py-2.5">{c.createdBy}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.items.map((e) => (
            <tr
              key={e.enrolment_id}
              className="cursor-pointer hover:bg-brand-50/50"
              onClick={() => void navigate(`/enrolments/${e.enrolment_id}`)}
            >
              <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">
                <Link to={`/enrolments/${e.enrolment_id}`} className="text-brand-700 hover:underline" onClick={(ev) => ev.stopPropagation()}>
                  {e.our_reference_no}
                </Link>
              </td>
              <td className="px-4 py-2.5 font-medium text-slate-900">{e.insured_name}</td>
              <td className="px-4 py-2.5">
                <StatusBadge status={e.status} />
              </td>
              {showReason && <td className="px-4 py-2.5 text-xs">{e.attention_reason ? strings.attentionReason[e.attention_reason] : "-"}</td>}
              <td className="px-4 py-2.5">{show(e.plan_code)}</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{formatInr(e.gross_premium)}</td>
              <td className="px-4 py-2.5 font-mono text-xs">{show(e.certificate_no)}</td>
              <td className="px-4 py-2.5">{e.branch_code}</td>
              <td className="px-4 py-2.5 whitespace-nowrap text-slate-500">{formatDateTime(e.created_at)}</td>
              <td className="px-4 py-2.5 text-slate-500">{e.created_by.display_name ?? e.created_by.roll_no}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EnrolmentList() {
  const [params, setParams] = useSearchParams();
  const { me, hasRole } = useAuth();
  const statuses = params.getAll("status") as EnrolmentStatus[];
  const q = params.get("q") ?? "";
  const from = params.get("created_from") ?? "";
  const to = params.get("created_to") ?? "";
  const branch = params.get("branch_code") ?? "";
  const mine = params.get("mine") === "true";
  const page = Number(params.get("page") ?? "1") || 1;
  const key = params.toString();

  const [draft, setDraft] = useState({ q, from, to, branch, status: statuses.length === 1 ? statuses[0] ?? "" : "", mine });

  const { data, error, loading, reload } = useAsync<EnrolmentPage>(
    () =>
      api.listEnrolments({
        status: statuses.length ? statuses : undefined,
        q: q.length >= 3 ? q : undefined,
        created_from: from || undefined,
        created_to: to || undefined,
        branch_code: branch || undefined,
        mine: mine || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [key],
  );

  function apply(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.status) next.append("status", draft.status);
    if (draft.q.trim()) next.set("q", draft.q.trim());
    if (draft.from) next.set("created_from", draft.from);
    if (draft.to) next.set("created_to", draft.to);
    if (draft.branch.trim()) next.set("branch_code", draft.branch.trim().toUpperCase());
    if (draft.mine) next.set("mine", "true");
    setParams(next);
  }

  function clear() {
    setDraft({ q: "", from: "", to: "", branch: "", status: "", mine: false });
    setParams(new URLSearchParams());
  }

  function goPage(p: number) {
    const next = new URLSearchParams(params);
    next.set("page", String(p));
    setParams(next);
  }

  const s = strings.enrolments;
  return (
    <>
      <PageHeader
        title={s.heading}
        actions={
          hasRole("BRANCH_USER") && (
            <Link to="/sale/new" className="btn-primary">
              <IconPlus className="h-4 w-4" />
              {strings.nav.newSale}
            </Link>
          )
        }
      />
      <Card className="mb-4">
        <form onSubmit={apply} className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-6">
          <div className="lg:col-span-2">
            <label htmlFor="f-q" className="field-label">
              {s.searchLabel}
            </label>
            <div className="relative">
              <IconSearch className="pointer-events-none absolute top-2.5 left-2.5 h-4 w-4 text-slate-400" />
              <input
                id="f-q"
                className="input pl-8"
                value={draft.q}
                placeholder={s.searchHint}
                maxLength={40}
                pattern="[A-Za-z0-9/_\-]{3,40}"
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
              />
            </div>
          </div>
          <div>
            <label htmlFor="f-status" className="field-label">
              {s.statusFilter}
            </label>
            <select id="f-status" className="input" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
              <option value="">{s.allStatuses}</option>
              {ENROLMENT_STATUSES.map((st) => (
                <option key={st} value={st}>
                  {strings.status[st]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="f-from" className="field-label">
              {s.from}
            </label>
            <input id="f-from" type="date" className="input" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </div>
          <div>
            <label htmlFor="f-to" className="field-label">
              {s.to}
            </label>
            <input id="f-to" type="date" className="input" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </div>
          {me?.cross_branch ? (
            <div>
              <label htmlFor="f-branch" className="field-label">
                {s.cols.branch}
              </label>
              <input id="f-branch" className="input" value={draft.branch} maxLength={10} onChange={(e) => setDraft({ ...draft, branch: e.target.value })} />
            </div>
          ) : (
            <div className="flex items-end">
              <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
                <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={draft.mine} onChange={(e) => setDraft({ ...draft, mine: e.target.checked })} />
                {s.mine}
              </label>
            </div>
          )}
          <div className="flex gap-2 sm:col-span-2 lg:col-span-6">
            <button type="submit" className="btn-primary">
              {s.apply}
            </button>
            <button type="button" className="btn-secondary" onClick={clear}>
              {s.clear}
            </button>
            {statuses.length > 1 && (
              <span className="flex flex-wrap items-center gap-1">
                {statuses.map((st) => (
                  <StatusBadge key={st} status={st} />
                ))}
              </span>
            )}
          </div>
        </form>
      </Card>
      <Card>
        {loading && !data ? (
          <Spinner />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : data ? (
          <>
            <EnrolmentTable data={data} />
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={goPage} />
          </>
        ) : null}
      </Card>
    </>
  );
}
