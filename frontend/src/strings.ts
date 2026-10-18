// All user-visible text lives here so the app can be localised later (Q17).
// Components must not contain literal user-facing strings.
export const strings = {
  appName: "Group Insurance",
  document: {
    title: "Group Insurance - Staff",
  },
  signIn: {
    heading: "Sign in",
    branchCode: "Branch code",
    rollNumber: "Roll number",
    password: "Password", // secret-scan:allow (UI label)
    submit: "Sign in",
    notConnected:
      "Sign-in is not connected yet. Nothing was sent. This page is a placeholder.",
  },
  notFound: {
    heading: "Page not found",
    body: "The page you asked for does not exist.",
    backToSignIn: "Go to sign in",
  },
  fatal: {
    missingRoot: "The page could not start.",
  },
} as const;
