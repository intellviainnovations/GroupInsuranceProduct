import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/endpoints";
import type { Approval } from "../api/types";
import { strings } from "../strings";
import { Field, Modal } from "../ui/components";
import { useAction } from "../ui/useAction";

/** Approve or reject one approval. The server re-checks can_decide and maker != checker. */
export function DecisionDialog({
  approval,
  decision,
  onClose,
  onDone,
}: {
  approval: Approval;
  decision: "approve" | "reject";
  onClose: () => void;
  onDone: () => void;
}) {
  const [comment, setComment] = useState("");
  const { run, busy, outcomeToast } = useAction();
  const s = strings.approvals;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = comment.trim();
    const r =
      decision === "approve"
        ? await run(`approve-${approval.approval_id}`, (k) => api.approve(approval.approval_id, { comment: text || null }, k))
        : await run(`reject-${approval.approval_id}`, () => api.reject(approval.approval_id, { comment: text }));
    if (r) {
      outcomeToast(r, decision === "approve" ? s.approved : s.rejected);
      onDone();
    }
  }

  return (
    <Modal title={`${decision === "approve" ? s.approve : s.reject}: ${approval.our_reference_no ?? ""}`} onClose={onClose}>
      <form onSubmit={(ev) => void submit(ev)} className="space-y-4">
        <p className="text-sm text-slate-600">
          {s.actionNames[approval.action]} - {approval.insured_name ?? ""}
          {approval.proposed_status && ` - ${s.proposedStatus}: ${strings.status[approval.proposed_status]}`}
        </p>
        {approval.maker_comment && (
          <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
            <span className="font-medium">{approval.maker.display_name ?? approval.maker.roll_no}:</span> {approval.maker_comment}
          </p>
        )}
        <Field id="decision-comment" label={decision === "approve" ? s.commentOptional : s.commentRequired}>
          <textarea
            id="decision-comment"
            className="input"
            rows={3}
            maxLength={300}
            required={decision === "reject"}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            {strings.common.cancel}
          </button>
          <button type="submit" className={decision === "approve" ? "btn-primary" : "btn-danger"} disabled={busy !== null}>
            {decision === "approve" ? s.approve : s.reject}
          </button>
        </div>
      </form>
    </Modal>
  );
}
