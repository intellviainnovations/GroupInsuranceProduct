import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../layout/AppLayout";
import { strings } from "../strings";
import { ErrorState } from "../ui/components";

export function SignIn() {
  const { me, login, verifyOtp, signOutReason } = useAuth();
  const [branchCode, setBranchCode] = useState("");
  const [rollNo, setRollNo] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (me) return <Navigate to="/dashboard" replace />;

  async function onLogin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await login({ branch_code: branchCode.trim().toUpperCase(), roll_no: rollNo.trim(), password });
      setPassword("");
      if (r.status === "OTP_REQUIRED" && r.challenge_id) setChallenge(r.challenge_id);
    } catch (err) {
      setPassword("");
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onOtp(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!challenge) return;
    setBusy(true);
    setError(null);
    try {
      await verifyOtp(challenge, otp.trim());
    } catch (err) {
      setError(err);
      setChallenge(null);
    } finally {
      setOtp("");
      setBusy(false);
    }
  }

  const s = strings.signIn;
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-900 via-brand-800 to-brand-600 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Brand light />
        </div>
        <main className="card p-6 shadow-xl">
          <h1 className="text-lg font-semibold text-slate-900">{challenge ? s.otpHeading : s.heading}</h1>
          <p className="mt-1 mb-5 text-sm text-slate-500">{challenge ? s.otpHelp : s.subheading}</p>
          {signOutReason && !error && (
            <p role="status" className="mb-4 rounded-md bg-brand-50 p-3 text-sm text-brand-800">
              {signOutReason === "expired" ? s.expired : s.signedOut}
            </p>
          )}
          {error !== null && (
            <div className="mb-4">
              <ErrorState error={error} />
            </div>
          )}
          {!challenge ? (
            <form onSubmit={onLogin} className="space-y-4" autoComplete="off">
              <div>
                <label htmlFor="branch" className="field-label">
                  {s.branchCode}
                </label>
                <input id="branch" className="input" value={branchCode} onChange={(e) => setBranchCode(e.target.value)} required maxLength={10} autoComplete="off" />
              </div>
              <div>
                <label htmlFor="roll" className="field-label">
                  {s.rollNumber}
                </label>
                <input id="roll" className="input" value={rollNo} onChange={(e) => setRollNo(e.target.value)} required maxLength={20} autoComplete="off" />
              </div>
              <div>
                <label htmlFor="pw" className="field-label">
                  {s.password}
                </label>
                <input id="pw" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} required maxLength={128} autoComplete="off" />
              </div>
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? s.signingIn : s.submit}
              </button>
            </form>
          ) : (
            <form onSubmit={onOtp} className="space-y-4" autoComplete="off">
              <div>
                <label htmlFor="otp" className="field-label">
                  {s.otp}
                </label>
                <input
                  id="otp"
                  className="input text-center font-mono tracking-[0.4em]"
                  inputMode="numeric"
                  pattern="[0-9]{4,8}"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  required
                  maxLength={8}
                  autoComplete="one-time-code"
                />
              </div>
              <div className="flex gap-2">
                <button type="button" className="btn-secondary flex-1" onClick={() => setChallenge(null)}>
                  {s.back}
                </button>
                <button type="submit" className="btn-primary flex-1" disabled={busy}>
                  {s.verify}
                </button>
              </div>
            </form>
          )}
        </main>
      </div>
    </div>
  );
}
