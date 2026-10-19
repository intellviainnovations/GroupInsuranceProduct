// Generates src/api/types.ts from the backend's OpenAPI snapshot
// (docs/contracts/staff-api.openapi.snapshot.json). Node built-ins only.
//   node scripts/gen-api-types.mjs          write src/api/types.ts
//   node scripts/gen-api-types.mjs --check  fail if the committed file differs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const specPath = join(here, "..", "..", "docs", "contracts", "staff-api.openapi.snapshot.json");
const outPath = join(here, "..", "src", "api", "types.ts");

const spec = JSON.parse(readFileSync(specPath, "utf8"));
const schemas = spec.components?.schemas ?? {};

const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const propKey = (k) => (IDENT.test(k) ? k : JSON.stringify(k));
const refName = (ref) => {
  const m = /^#\/components\/schemas\/(.+)$/.exec(ref);
  if (!m) throw new Error(`Unsupported $ref: ${ref}`);
  return m[1].replace(/[^A-Za-z0-9_$]/g, "_");
};

function union(parts) {
  const seen = [];
  for (const p of parts.flatMap((x) => splitTop(x))) if (!seen.includes(p)) seen.push(p);
  // keep null last for readability
  seen.sort((a, b) => (a === "null") - (b === "null"));
  return seen.length ? seen.join(" | ") : "never";
}

// Split a type string on top-level " | " (not inside braces/parens/brackets).
function splitTop(t) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (c === "{" || c === "(" || c === "[" || c === "<") depth++;
    else if (c === "}" || c === ")" || c === "]" || c === ">") depth--;
    else if (depth === 0 && t.startsWith(" | ", i)) {
      out.push(t.slice(start, i));
      start = i + 3;
      i += 2;
    }
  }
  out.push(t.slice(start));
  return out;
}

function literal(v) {
  return v === null ? "null" : JSON.stringify(v);
}

function objectBody(s, indent) {
  const pad = "  ".repeat(indent + 1);
  const required = new Set(s.required ?? []);
  const lines = Object.keys(s.properties ?? {}).map((k) => {
    const opt = required.has(k) ? "" : "?";
    return `${pad}${propKey(k)}${opt}: ${tsType(s.properties[k], indent + 1)};`;
  });
  if (s.additionalProperties && typeof s.additionalProperties === "object") {
    lines.push(`${pad}[key: string]: ${tsType(s.additionalProperties, indent + 1)};`);
  }
  return `{\n${lines.join("\n")}\n${"  ".repeat(indent)}}`;
}

function tsType(s, indent = 0) {
  if (s === true || s === undefined || s === null) return "unknown";
  if (s.$ref) return refName(s.$ref);
  if (s.const !== undefined) return literal(s.const);
  if (s.enum) return union(s.enum.map(literal));
  if (s.anyOf || s.oneOf) return union((s.anyOf ?? s.oneOf).map((x) => tsType(x, indent)));
  if (s.allOf) {
    const parts = s.allOf.map((x) => tsType(x, indent));
    return parts.length === 1 ? parts[0] : parts.map((p) => (splitTop(p).length > 1 ? `(${p})` : p)).join(" & ");
  }
  if (Array.isArray(s.type)) return union(s.type.map((t) => tsType({ ...s, type: t }, indent)));
  switch (s.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "null":
      return "null";
    case "array": {
      const item = tsType(s.items, indent);
      return splitTop(item).length > 1 ? `(${item})[]` : `${item}[]`;
    }
    case "object":
    case undefined:
      if (s.properties) return objectBody(s, indent);
      if (s.additionalProperties && typeof s.additionalProperties === "object") {
        return `Record<string, ${tsType(s.additionalProperties, indent)}>`;
      }
      return s.type === "object" ? "Record<string, unknown>" : "unknown";
    default:
      return "unknown";
  }
}

function doc(s) {
  const text = (s.description ?? "").replace(/\*\//g, "*\\/").trim();
  if (!text) return "";
  return `/** ${text.replace(/\s*\n\s*/g, " ")} */\n`;
}

let out =
  "// GENERATED FILE - DO NOT EDIT.\n" +
  "// Source: docs/contracts/staff-api.openapi.snapshot.json\n" +
  "// Regenerate with `npm run gen:api`; CI runs `npm run check:api`.\n" +
  "// UI-only helper types live in ./model.ts.\n";
for (const name of Object.keys(schemas).sort()) {
  const s = schemas[name];
  const id = name.replace(/[^A-Za-z0-9_$]/g, "_");
  const isPlainObject = (s.type === "object" || s.type === undefined) && s.properties && !s.anyOf && !s.oneOf && !s.allOf;
  out += "\n" + doc(s);
  out += isPlainObject ? `export interface ${id} ${objectBody(s, 0)}\n` : `export type ${id} = ${tsType(s, 0)};\n`;
}

const normalise = (t) => t.replace(/\r\n/g, "\n");
if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = readFileSync(outPath, "utf8");
  } catch {
    current = "";
  }
  if (normalise(current) !== out) {
    console.error("src/api/types.ts is out of date with the OpenAPI snapshot. Run `npm run gen:api` and commit.");
    process.exit(1);
  }
  console.log("API types match the OpenAPI snapshot.");
} else {
  writeFileSync(outPath, out);
  console.log(`Wrote ${outPath}`);
}
