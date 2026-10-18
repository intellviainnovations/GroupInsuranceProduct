// Cheap source scan for patterns the frontend must never contain: raw HTML
// injection, browser storage (no tokens or secrets there), eval, and inline
// scripts in index.html (so the bank proxy can apply a strict CSP).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const forbidden = [
  [/dangerouslySetInnerHTML/, "dangerouslySetInnerHTML"],
  [/\.innerHTML\s*=/, "innerHTML assignment"],
  [/\blocalStorage\b/, "localStorage"],
  [/\bsessionStorage\b/, "sessionStorage"],
  [/\beval\s*\(/, "eval"],
  [/new\s+Function\s*\(/, "new Function"],
];

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const problems = [];
for (const file of walk("src").filter((f) => /\.(ts|tsx)$/.test(f))) {
  const text = readFileSync(file, "utf8");
  for (const [pattern, label] of forbidden) {
    if (pattern.test(text)) problems.push(`${file}: ${label}`);
  }
}

const html = readFileSync("index.html", "utf8");
for (const m of html.matchAll(/<script\b([^>]*)>/gi)) {
  if (!/\bsrc=/.test(m[1] ?? "")) problems.push("index.html: inline script");
}
if (/\son[a-z]+\s*=/i.test(html)) problems.push("index.html: inline event handler");

if (problems.length > 0) {
  console.error("Security scan failed:\n" + problems.join("\n"));
  process.exit(1);
}
console.log("Security scan passed.");
