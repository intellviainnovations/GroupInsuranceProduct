import { Link } from "react-router";
import { strings } from "../strings";

export function NotFound() {
  return (
    <main>
      <h1>{strings.notFound.heading}</h1>
      <p>{strings.notFound.body}</p>
      <p>
        <Link to="/sign-in">{strings.notFound.backToSignIn}</Link>
      </p>
    </main>
  );
}
