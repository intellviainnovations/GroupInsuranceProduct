import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { labelFor, loadPlans, loadRefCodes } from "../api/reference";
import type { CustomerLookupResult, EnrolmentDetail, InsuredInput, NomineeInput, Plan, RefCodes } from "../api/model";
import { strings } from "../strings";
import { Card, DefList, ErrorState, Field, PageHeader, Pill, Spinner, useAsync } from "../ui/components";
import { formatDate, formatDateTime, formatInr, show } from "../ui/format";
import { IconCheck, IconPlus, IconSearch, IconTrash } from "../ui/icons";
import { useAction } from "../ui/useAction";

const s = strings.sale;
const f = strings.detail.fields;

function Stepper({ current }: { current: number }) {
  return (
    <ol className="mb-5 flex flex-wrap gap-2" aria-label={s.heading}>
      {s.steps.map((label, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={label} aria-current={state === "current" ? "step" : undefined} className="flex items-center gap-2">
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                state === "done" ? "bg-emerald-600 text-white" : state === "current" ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-600"
              }`}
            >
              {state === "done" ? <IconCheck className="h-4 w-4" /> : i + 1}
            </span>
            <span className={`text-sm ${state === "current" ? "font-semibold text-slate-900" : "text-slate-500"}`}>{label}</span>
            {i < s.steps.length - 1 && <span className="mx-1 hidden h-px w-8 bg-slate-300 sm:block" />}
          </li>
        );
      })}
    </ol>
  );
}

function fieldErrors(err: unknown, prefix: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (err instanceof ApiError) {
    for (const fe of err.fields) {
      const path = fe.field.startsWith(prefix) ? fe.field.slice(prefix.length) : fe.field;
      out[path] = fe.message ?? fe.code;
    }
  }
  return out;
}

// ---------------- Step 0: customer lookup ----------------
export function NewSale() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"account_no" | "cif">("account_no");
  const [value, setValue] = useState("");
  const [result, setResult] = useState<CustomerLookupResult | null>(null);
  const [lookupError, setLookupError] = useState<unknown>(null);
  const [accountKey, setAccountKey] = useState("");
  const [looking, setLooking] = useState(false);
  const { run, busy, toast } = useAction();

  async function lookup(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLooking(true);
    setLookupError(null);
    setResult(null);
    setAccountKey("");
    try {
      const v = value.trim();
      const r = await api.lookupCustomer(mode === "account_no" ? { account_no: v } : { cif: v });
      setResult(r);
      const sel = r.accounts.filter((a) => a.selectable);
      if (sel.length === 1 && sel[0]) setAccountKey(sel[0].account_key);
    } catch (err) {
      setLookupError(err);
    } finally {
      setLooking(false);
    }
  }

  async function start() {
    const v = value.trim();
    const r = await run("create", (k) =>
      api.createEnrolment({ lookup: mode === "account_no" ? { account_no: v } : { cif: v }, debit_account_key: accountKey }, k),
    );
    if (r) {
      setValue("");
      toast.push({ tone: "success", title: s.draftSaved, body: r.our_reference_no });
      void navigate(`/sale/${r.enrolment_id}?step=1`);
    }
  }

  const c = result?.customer;
  return (
    <>
      <PageHeader title={s.heading} />
      <Stepper current={0} />
      <Card title={s.lookupHeading}>
        <form onSubmit={(ev) => void lookup(ev)} className="space-y-4 p-4" autoComplete="off">
          <p className="text-sm text-slate-500">{s.lookupHelp}</p>
          <div role="radiogroup" className="inline-flex rounded-md border border-slate-300 p-0.5">
            {(["account_no", "cif"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${mode === m ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}
              >
                {m === "account_no" ? s.byAccount : s.byCif}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-full max-w-sm">
              <label htmlFor="lookup-value" className="field-label">
                {mode === "account_no" ? s.byAccount : s.byCif}
              </label>
              <input
                id="lookup-value"
                className="input font-mono"
                required
                value={value}
                autoComplete="off"
                inputMode={mode === "account_no" ? "numeric" : "text"}
                pattern={mode === "account_no" ? "[0-9]{6,30}" : "[A-Za-z0-9]{1,20}"}
                maxLength={30}
                onChange={(e) => setValue(e.target.value)}
              />
            </div>
            <button type="submit" className="btn-primary" disabled={looking}>
              <IconSearch className="h-4 w-4" />
              {looking ? s.lookingUp : s.lookup}
            </button>
          </div>
          {lookupError !== null && <ErrorState error={lookupError} />}
        </form>
        {c && result && (
          <div className="border-t border-slate-200">
            <DefList
              items={[
                [f.name, [c.first_name, c.middle_name, c.last_name].filter(Boolean).join(" ")],
                [f.cif, <span className="font-mono">{c.cif_masked}</span>],
                [f.dob, formatDate(c.date_of_birth)],
                [f.mobile, show(c.mobile_masked)],
                [f.city, show(c.city)],
                ["KYC", show(c.kyc_status)],
              ]}
            />
            <div className="px-4 pb-4">
              <p className="field-label">{s.chooseAccount}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {result.accounts.map((a) => (
                  <label
                    key={a.account_key}
                    className={`flex items-center gap-3 rounded-md border p-3 text-sm ${
                      !a.selectable ? "cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400" : accountKey === a.account_key ? "border-brand-500 bg-brand-50 ring-2 ring-brand-200" : "cursor-pointer border-slate-300 hover:border-brand-300"
                    }`}
                  >
                    <input type="radio" name="acct" disabled={!a.selectable} checked={accountKey === a.account_key} onChange={() => setAccountKey(a.account_key)} className="h-4 w-4" />
                    <div className="flex-1">
                      <p className="font-mono font-medium">{a.account_no_masked}</p>
                      <p className="text-xs">
                        {show(a.account_type)} - {show(a.account_status)} - {strings.detail.branch} {show(a.branch_code)}
                      </p>
                    </div>
                    {a.joint_account && <Pill>{s.joint}</Pill>}
                    {!a.selectable && <Pill tone="red">{s.notSelectable}</Pill>}
                  </label>
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {strings.detail.cbsFetched}: {formatDateTime(result.fetched_at)}
              </p>
              <div className="mt-4 flex justify-end">
                <button type="button" className="btn-primary" disabled={!accountKey || busy !== null} onClick={() => void start()}>
                  {s.startDraft}
                </button>
              </div>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

// ---------------- Steps 1-4: edit draft ----------------
type InsuredForm = Record<keyof InsuredInput, string>;
const INSURED_FIELDS: (keyof InsuredInput)[] = [
  "first_name", "middle_name", "last_name", "gender_code", "date_of_birth", "mobile", "email", "address1", "address2",
  "city", "state_code", "pincode", "occupation_code", "other_occupation", "any_disability", "disability_description", "guardian_name_address",
];
const NULLABLE = new Set<keyof InsuredInput>(["middle_name", "email", "address2", "other_occupation", "disability_description", "guardian_name_address"]);

function toInsuredForm(i: InsuredInput): InsuredForm {
  const out = {} as InsuredForm;
  for (const k of INSURED_FIELDS) {
    const v = i[k];
    out[k] = v === null || v === undefined ? "" : typeof v === "boolean" ? (v ? "true" : "false") : String(v);
  }
  return out;
}

/** Only fields the maker changed, never CBS-sourced ones (the server rejects those). */
function toInsuredPatch(form: InsuredForm, original: InsuredInput, cbs: Set<string>): InsuredInput {
  const before = toInsuredForm(original);
  const out: Record<string, unknown> = {};
  for (const k of INSURED_FIELDS) {
    if (cbs.has(k)) continue;
    const v = form[k].trim();
    if (v === before[k]) continue;
    if (k === "any_disability") {
      if (v) out[k] = v === "true";
    } else if (v) out[k] = v;
    else if (NULLABLE.has(k)) out[k] = null;
  }
  return out;
}

interface NomineeForm {
  name: string;
  relation_code: string;
  share_percent: string;
  date_of_birth: string;
  mobile: string;
}

function toNomineePatch(n: NomineeForm): NomineeInput {
  return {
    name: n.name.trim(),
    relation_code: n.relation_code,
    share_percent: n.share_percent.trim(),
    date_of_birth: n.date_of_birth || null,
    mobile: n.mobile.trim() || null,
  };
}

function Footer({ onBack, children }: { onBack?: (() => void) | undefined; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-2 border-t border-slate-200 p-4">
      {onBack ? (
        <button type="button" className="btn-secondary" onClick={onBack}>
          {s.back}
        </button>
      ) : (
        <span />
      )}
      {children}
    </div>
  );
}

export function SaleWizard() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const step = Math.min(Math.max(Number(params.get("step") ?? "1") || 1, 1), 4);
  const goStep = (n: number) => setParams({ step: String(n) });
  const enrol = useAsync<EnrolmentDetail>(() => api.getEnrolment(id), [id]);
  const codes = useAsync<RefCodes>(() => loadRefCodes(), []);
  const plans = useAsync<Plan[]>(() => loadPlans(), []);
  const { run, busy, outcomeToast, toast } = useAction(enrol.reload);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const [insured, setInsured] = useState<InsuredForm | null>(null);
  const [nominees, setNominees] = useState<NomineeForm[] | null>(null);
  const [planCode, setPlanCode] = useState<string>("");
  const [comment, setComment] = useState("");

  const e = enrol.data;
  useEffect(() => {
    if (!e) return;
    setInsured(toInsuredForm(e.insured));
    setNominees(
      e.nominees.map((n) => ({ name: n.name, relation_code: n.relation_code, share_percent: n.share_percent, date_of_birth: n.date_of_birth ?? "", mobile: n.mobile ?? "" })),
    );
    setPlanCode(e.plan?.plan_code ?? "");
  }, [e]);

  if (enrol.loading && !e) return <Spinner />;
  if (enrol.error || !e) return <ErrorState error={enrol.error} onRetry={enrol.reload} />;
  if (!insured || !nominees) return <Spinner />;
  if (!e.allowed_actions.includes("EDIT") && !e.allowed_actions.includes("SUBMIT")) {
    return (
      <Card>
        <div className="p-6 text-sm">
          <p>{strings.errors.invalidState}</p>
          <Link to={`/enrolments/${e.enrolment_id}`} className="btn-primary mt-3">
            {s.openDetail}
          </Link>
        </div>
      </Card>
    );
  }
  const rc = codes.data ?? undefined;
  const cbs = new Set(e.insured.cbs_sourced_fields);

  async function save(body: Parameters<typeof api.patchEnrolment>[1], prefix: string, next: number) {
    setErrs({});
    let failure: unknown = null;
    const r = await run(`patch-${prefix}`, async () => {
      try {
        return await api.patchEnrolment(id, body);
      } catch (err) {
        failure = err;
        throw err;
      }
    });
    if (r) {
      enrol.setData(r);
      goStep(next);
    } else if (failure) setErrs(fieldErrors(failure, prefix));
  }

  async function submit() {
    setErrs({});
    let failure: unknown = null;
    const r = await run("submit", async () => {
      try {
        return await api.submit(id, { version: e!.version, comment: comment.trim() || null });
      } catch (err) {
        failure = err;
        throw err;
      }
    });
    if (!r && failure) setErrs(fieldErrors(failure, ""));
    if (r) {
      outcomeToast(r, s.submitted);
      setComment("");
      void navigate(`/enrolments/${id}`);
    }
  }

  const inp = (k: keyof InsuredInput, label: string, props: Record<string, unknown> = {}) => {
    const locked = cbs.has(k);
    const errId = errs[k] ? `ins-${k}-error` : undefined;
    return (
      <Field id={`ins-${k}`} label={label} error={errs[k]} hint={locked ? strings.detail.cbsSourced : undefined}>
        <input
          id={`ins-${k}`}
          className={`input ${errs[k] ? "input-invalid" : ""}`}
          value={insured[k]}
          disabled={locked}
          aria-invalid={!!errs[k]}
          aria-describedby={errId}
          autoComplete="off"
          onChange={(ev) => setInsured({ ...insured, [k]: ev.target.value })}
          {...props}
        />
      </Field>
    );
  };
  const sel = (k: keyof InsuredInput, label: string, list: { code: string; label: string }[] | undefined) => {
    const locked = cbs.has(k);
    return (
      <Field id={`ins-${k}`} label={label} error={errs[k]} hint={locked ? strings.detail.cbsSourced : undefined}>
        <select id={`ins-${k}`} className={`input ${errs[k] ? "input-invalid" : ""}`} value={insured[k]} disabled={locked} onChange={(ev) => setInsured({ ...insured, [k]: ev.target.value })}>
          <option value="" />
          {list?.map((c) => (
            <option key={c.code} value={c.code}>
              {c.label}
            </option>
          ))}
          {insured[k] && !list?.some((c) => c.code === insured[k]) && <option value={insured[k]}>{insured[k]}</option>}
        </select>
      </Field>
    );
  };

  return (
    <>
      <PageHeader title={s.heading} subtitle={<span className="font-mono">{e.our_reference_no}</span>} actions={<Link to={`/enrolments/${id}`} className="btn-secondary">{s.openDetail}</Link>} />
      <Stepper current={step} />

      {step === 1 && (
        <Card title={s.insuredHeading}>
          <p className="px-4 pt-4 text-sm text-slate-500">{s.insuredHelp}</p>
          <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {inp("first_name", f.name)}
            {inp("middle_name", `${f.name} (middle)`)}
            {inp("last_name", `${f.name} (last)`)}
            {sel("gender_code", f.gender, rc?.GENDER)}
            {inp("date_of_birth", f.dob, { type: "date" })}
            {inp("mobile", f.mobile, { inputMode: "numeric", maxLength: 15 })}
            {inp("email", f.email, { type: "email", maxLength: 150 })}
            {inp("address1", f.address, { maxLength: 150 })}
            {inp("address2", `${f.address} 2`, { maxLength: 150 })}
            {inp("city", f.city, { maxLength: 60 })}
            {sel("state_code", f.state, rc?.STATE)}
            {inp("pincode", f.pincode, { inputMode: "numeric", maxLength: 6 })}
            {sel("occupation_code", f.occupation, rc?.OCCUPATION)}
            {inp("other_occupation", `${f.occupation} (other)`, { maxLength: 60 })}
            <Field id="ins-any_disability" label={f.disability} error={errs.any_disability}>
              <select id="ins-any_disability" className="input" value={insured.any_disability} onChange={(ev) => setInsured({ ...insured, any_disability: ev.target.value })}>
                <option value="" />
                <option value="false">{strings.common.no}</option>
                <option value="true">{strings.common.yes}</option>
              </select>
            </Field>
            {insured.any_disability === "true" && inp("disability_description", `${f.disability} - details`, { maxLength: 500 })}
          </div>
          <Footer>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => {
                const patch = toInsuredPatch(insured, e.insured, cbs);
                if (Object.keys(patch).length === 0) goStep(2);
                else void save({ version: e.version, insured: patch }, "insured.", 2);
              }}>
              {s.saveContinue}
            </button>
          </Footer>
        </Card>
      )}

      {step === 2 && (
        <Card title={s.nomineesHeading}>
          <p className="px-4 pt-4 text-sm text-slate-500">{s.nomineesHelp}</p>
          {errs.nominees && <p className="mx-4 mt-2 rounded bg-rose-50 p-2 text-sm text-rose-700">{errs.nominees}</p>}
          <div className="space-y-3 p-4">
            {nominees.map((n, i) => {
              const set = (patch: Partial<NomineeForm>) => setNominees(nominees.map((x, j) => (j === i ? { ...x, ...patch } : x)));
              const er = (k: string) => errs[`nominees[${i}].${k}`] ?? errs[`[${i}].${k}`];
              return (
                <fieldset key={i} className="rounded-md border border-slate-200 p-3">
                  <legend className="px-1 text-xs font-semibold text-slate-600">
                    {s.nominee} {i + 1}
                  </legend>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
                    <div className="lg:col-span-2">
                      <Field id={`n${i}-name`} label={f.name} error={er("name")}>
                        <input id={`n${i}-name`} className="input" required maxLength={150} value={n.name} onChange={(ev) => set({ name: ev.target.value })} />
                      </Field>
                    </div>
                    <Field id={`n${i}-rel`} label={f.relation} error={er("relation_code")}>
                      <select id={`n${i}-rel`} className="input" value={n.relation_code} onChange={(ev) => set({ relation_code: ev.target.value })}>
                        <option value="" />
                        {rc?.RELATION.map((c) => (
                          <option key={c.code} value={c.code}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field id={`n${i}-share`} label={s.sharePercent} error={er("share_percent")}>
                      <input id={`n${i}-share`} className="input" inputMode="decimal" maxLength={8} value={n.share_percent} onChange={(ev) => set({ share_percent: ev.target.value })} />
                    </Field>
                    <Field id={`n${i}-dob`} label={f.dob} error={er("date_of_birth")}>
                      <input id={`n${i}-dob`} type="date" className="input" value={n.date_of_birth} onChange={(ev) => set({ date_of_birth: ev.target.value })} />
                    </Field>
                    <div className="flex items-end gap-2">
                      <div className="flex-1">
                        <Field id={`n${i}-mob`} label={f.mobile} error={er("mobile")}>
                          <input id={`n${i}-mob`} className="input" inputMode="numeric" maxLength={15} value={n.mobile} onChange={(ev) => set({ mobile: ev.target.value })} />
                        </Field>
                      </div>
                      <button type="button" className="btn-ghost px-2 text-rose-600" aria-label={`${s.removeNominee} ${i + 1}`} onClick={() => setNominees(nominees.filter((_, j) => j !== i))}>
                        <IconTrash className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </fieldset>
              );
            })}
            {nominees.length < 10 && (
              <button type="button" className="btn-secondary" onClick={() => setNominees([...nominees, { name: "", relation_code: "", share_percent: nominees.length === 0 ? "100" : "", date_of_birth: "", mobile: "" }])}>
                <IconPlus className="h-4 w-4" />
                {s.addNominee}
              </button>
            )}
          </div>
          <Footer onBack={() => goStep(1)}>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => void save({ version: e.version, nominees: nominees.map(toNomineePatch) }, "", 3)}>
              {s.saveContinue}
            </button>
          </Footer>
        </Card>
      )}

      {step === 3 && (
        <Card title={s.planHeading}>
          {plans.loading ? (
            <Spinner />
          ) : plans.error ? (
            <div className="p-4">
              <ErrorState error={plans.error} onRetry={plans.reload} />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
              {plans.data?.map((p) => {
                const active = planCode === p.plan_code;
                return (
                  <button
                    key={p.plan_code}
                    type="button"
                    aria-pressed={active}
                    disabled={!p.rate}
                    onClick={() => setPlanCode(p.plan_code)}
                    className={`rounded-lg border p-4 text-left transition ${active ? "border-brand-500 bg-brand-50 ring-2 ring-brand-200" : "border-slate-200 bg-white hover:border-brand-300"} disabled:opacity-50`}
                  >
                    <div className="flex items-center justify-between">
                      <p className="font-semibold text-slate-900">{p.name}</p>
                      {active && <IconCheck className="h-5 w-5 text-brand-600" />}
                    </div>
                    {p.rate ? (
                      <>
                        <p className="mt-3 text-xs text-slate-500">{f.sumInsured}</p>
                        <p className="text-lg font-semibold tabular-nums">{formatInr(p.rate.sum_insured)}</p>
                        <dl className="mt-2 grid grid-cols-3 gap-1 text-xs">
                          <div><dt className="text-slate-500">{f.net}</dt><dd className="tabular-nums">{formatInr(p.rate.net_premium)}</dd></div>
                          <div><dt className="text-slate-500">{f.gst}</dt><dd className="tabular-nums">{formatInr(p.rate.gst_amount)}</dd></div>
                          <div><dt className="text-slate-500">{f.gross}</dt><dd className="font-semibold tabular-nums">{formatInr(p.rate.gross_premium)}</dd></div>
                        </dl>
                        <p className="mt-2 text-xs text-slate-500">{f.term}: {p.rate.policy_term_days}</p>
                        {p.rate.synthetic && <p className="mt-2"><Pill tone="amber">{s.syntheticRate}</Pill></p>}
                      </>
                    ) : (
                      <p className="mt-3 text-sm text-slate-500">{s.noRate}</p>
                    )}
                  </button>
                );
              })}
            </div>
          )}
          {errs.plan_code && <p className="mx-4 mb-2 text-sm text-rose-700">{errs.plan_code}</p>}
          <Footer onBack={() => goStep(2)}>
            <button
              type="button"
              className="btn-primary"
              disabled={!planCode || busy !== null}
              onClick={() => (planCode === e.plan?.plan_code ? goStep(4) : void save({ version: e.version, plan_code: planCode }, "", 4))}
            >
              {s.saveContinue}
            </button>
          </Footer>
        </Card>
      )}

      {step === 4 && (
        <Card title={s.reviewHeading}>
          <p className="px-4 pt-4 text-sm text-slate-500">{s.reviewHelp}</p>
          <DefList
            items={[
              [f.name, [e.insured.first_name, e.insured.middle_name, e.insured.last_name].filter(Boolean).join(" ")],
              [f.dob, formatDate(e.insured.date_of_birth)],
              [f.gender, labelFor(rc?.GENDER, e.insured.gender_code)],
              [f.mobile, show(e.insured.mobile)],
              [f.address, [e.insured.address1, e.insured.city, labelFor(rc?.STATE, e.insured.state_code), e.insured.pincode].filter(Boolean).join(", ")],
              [f.occupation, labelFor(rc?.OCCUPATION, e.insured.occupation_code)],
              [strings.detail.debitAccount, <span className="font-mono">{e.debit_account.account_no_masked}</span>],
              [strings.enrolments.cols.plan, e.plan ? e.plan.name : "-"],
              [f.gross, (
                <span className="inline-flex items-center gap-1.5 font-semibold">
                  {formatInr(e.plan?.rate?.gross_premium)}
                  {e.plan?.rate?.synthetic && <Pill tone="amber">{s.syntheticRate}</Pill>}
                </span>
              )],
              [strings.detail.nominees, e.nominees.map((n) => `${n.name} (${labelFor(rc?.RELATION, n.relation_code)}, ${n.share_percent}%)`).join("; ") || "-"],
            ]}
          />
          {step === 4 && Object.keys(errs).length > 0 && (
            <ul role="alert" className="mx-4 mb-4 list-inside list-disc rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {Object.entries(errs).map(([k, v]) => (
                <li key={k}>
                  <span className="font-mono">{k}</span>: {v}
                </li>
              ))}
            </ul>
          )}
          <div className="px-4 pb-4">
            <Field id="rev-comment" label={strings.detail.submitDialog.comment}>
              <textarea id="rev-comment" className="input" rows={2} maxLength={300} value={comment} onChange={(ev) => setComment(ev.target.value)} />
            </Field>
          </div>
          <Footer onBack={() => goStep(3)}>
            {e.allowed_actions.includes("SUBMIT") ? (
              <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => void submit()}>
                {s.submit}
              </button>
            ) : (
              <button type="button" className="btn-primary" onClick={() => { toast.push({ tone: "info", title: s.draftSaved }); void navigate(`/enrolments/${id}`); }}>
                {s.openDetail}
              </button>
            )}
          </Footer>
        </Card>
      )}
    </>
  );
}
