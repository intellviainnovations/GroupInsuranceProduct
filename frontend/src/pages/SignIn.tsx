import { useState } from "react";
import type { FormEvent } from "react";
import { strings } from "../strings";

// Placeholder only: no submit logic, no network call, nothing stored.
// Fields are uncontrolled so no credential is held in React state; the form is
// reset on submit so the password does not linger in the page.
export function SignIn() {
  const [submitted, setSubmitted] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.currentTarget.reset();
    setSubmitted(true);
  }

  return (
    <main>
      <h1>{strings.signIn.heading}</h1>
      <form onSubmit={onSubmit} autoComplete="off">
        <label htmlFor="branch-code">{strings.signIn.branchCode}</label>
        <input
          id="branch-code"
          name="branchCode"
          type="text"
          autoComplete="off"
          inputMode="numeric"
          required
        />
        <label htmlFor="roll-number">{strings.signIn.rollNumber}</label>
        <input
          id="roll-number"
          name="rollNumber"
          type="text"
          autoComplete="off"
          required
        />
        <label htmlFor="password">{strings.signIn.password}</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="off"
          required
        />
        <button type="submit">{strings.signIn.submit}</button>
      </form>
      {submitted ? (
        <p role="status" className="status">
          {strings.signIn.notConnected}
        </p>
      ) : null}
    </main>
  );
}
