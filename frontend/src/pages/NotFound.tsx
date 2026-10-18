import { Link } from "react-router";
import { strings } from "../strings";

export function NotFound() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-6">
      <div className="card max-w-md p-6 text-center">
        <h1 className="text-lg font-semibold text-slate-900">{strings.notFound.heading}</h1>
        <p className="mt-2 text-sm text-slate-600">{strings.notFound.body}</p>
        <Link to="/" className="btn-primary mt-4">
          {strings.notFound.backToSignIn}
        </Link>
      </div>
    </div>
  );
}

export function NoAccess() {
  return (
    <div className="card mx-auto mt-10 max-w-lg p-6 text-center">
      <h1 className="text-lg font-semibold text-slate-900">{strings.noAccess.heading}</h1>
      <p className="mt-2 text-sm text-slate-600">{strings.noAccess.body}</p>
    </div>
  );
}
