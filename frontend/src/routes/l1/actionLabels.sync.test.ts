// t233 (B2, ĐP 01/11 14:50 điều kiện 3 + 15:00): bảng nhãn FE ↔ tập giá trị backend, so HAI CHIỀU, đọc thẳng file nguồn backend.
// OpenAPI không có các enum này (`action` là dict tự do) → đồng bộ mức test (ĐP chấp nhận 15:00). Không tìm thấy file / không
// parse được / tập rỗng / ít hơn số tối thiểu ghi cứng → ĐỎ, không bỏ qua.
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ACCOUNT_TYPE,
  ACTION_TYPE_LABEL,
  CERT_STATUS,
  DISABLE_REASON,
  FLAT_KEY_LABEL,
  LEVEL,
  LOCK_REASON,
  PERMISSION,
  PRIVILEGE,
  REVERSIBILITY,
  SCOPE_LABEL,
  USER_STATUS,
  VALUE_LABEL,
} from "./actionLabels.ts";

/** Đọc file nguồn ở gốc repo (vitest chạy ở frontend/ → gốc repo = ".."). Không có file → ném lỗi → test đỏ. */
const repo = (path: string): string => readFileSync(join(process.cwd(), "..", path), "utf8");
const actionPy = repo("backend/app/domain/action.py");
const factsPy = repo("backend/app/domain/facts.py");
const metadataYaml = repo("config/action_metadata.yaml");
const slotsYaml = repo("config/slots.yaml");

const quoted = (text: string): string[] => [...text.matchAll(/"([^"]+)"/g)].map((m) => m[1]!);

/** `type Name = Literal["a", "b"]` trong action.py. */
function literal(name: string): string[] {
  const m = new RegExp(`^type ${name} = Literal\\[([^\\]]*)\\]`, "m").exec(actionPy);
  if (!m) throw new Error(`action.py: không thấy type ${name}`);
  return quoted(m[1]!);
}

/** Thân `NAME: ... = {` … `}` mức cột 0 (dict nhiều dòng). */
function block(source: string, name: string): string {
  const start = source.search(new RegExp(`^${name}\\b[^\\n]*=\\s*\\{`, "m"));
  if (start < 0) throw new Error(`không thấy ${name}`);
  const end = source.indexOf("\n}", start);
  if (end < 0) throw new Error(`${name}: không thấy dấu đóng`);
  return source.slice(start, end);
}

/** `"fact": frozenset({...})` hoặc `"fact": TÊN_HẰNG` trong FACT_VALUE_SETS. */
function factSet(fact: string): string[] {
  const body = block(factsPy, "FACT_VALUE_SETS");
  const line = new RegExp(`"${fact}":\\s*([^\\n]+)`).exec(body)?.[1];
  if (!line) throw new Error(`FACT_VALUE_SETS thiếu ${fact}`);
  const inline = /frozenset\(\{([^}]*)\}\)/.exec(line);
  if (inline) return quoted(inline[1]!);
  const ref = /^([A-Z_]+)/.exec(line)?.[1];
  const def = ref ? new RegExp(`^${ref}[^=]*=\\s*frozenset\\(\\{([^}]*)\\}\\)`, "m").exec(factsPy) : null;
  if (!def) throw new Error(`FACT_VALUE_SETS[${fact}]: không parse được`);
  return quoted(def[1]!);
}

const sorted = (xs: Iterable<string>) => [...xs].sort();
/** Tập đọc được: khác rỗng, ≥ tối thiểu, không trùng. */
function checked(values: string[], min: number, what: string): string[] {
  expect(values.length, `${what}: số phần tử`).toBeGreaterThanOrEqual(min);
  expect(new Set(values).size, `${what}: trùng`).toBe(values.length);
  return values;
}
/** Hai chiều: backend thiếu nhãn → đỏ; nhãn FE thừa → đỏ. */
const same = (labels: object, backend: string[], what: string) =>
  expect(sorted(Object.keys(labels)), what).toStrictEqual(sorted(backend));

describe("t233: bảng nhãn B2 khớp tập giá trị backend (hai chiều)", () => {
  it("action.py — scope (=4), privilege_level (=3), reversibility (=3), data_sensitivity (=3), permission_level (=3)", () => {
    same(SCOPE_LABEL, checked(literal("Scope"), 4, "Scope"), "scope");
    same(PRIVILEGE, checked(literal("PrivilegeLevel"), 3, "PrivilegeLevel"), "privilege_level");
    same(REVERSIBILITY, checked(literal("Reversibility"), 3, "Reversibility"), "reversibility");
    same(LEVEL, checked(literal("Sensitivity"), 3, "Sensitivity"), "data_sensitivity");
    const perm = /^PERMISSION_LEVELS[^=]*=\s*frozenset\(\{([^}]*)\}\)/m.exec(actionPy);
    if (!perm) throw new Error("action.py: không thấy PERMISSION_LEVELS");
    same(PERMISSION, checked(quoted(perm[1]!), 3, "PERMISSION_LEVELS"), "params.permission_level");
    // Bảng nhãn dùng đúng các bảng này cho đúng khoá.
    expect(VALUE_LABEL.scope).toBe(SCOPE_LABEL);
    expect(VALUE_LABEL.privilege_level).toBe(PRIVILEGE);
    expect(VALUE_LABEL.reversibility).toBe(REVERSIBILITY);
    expect(VALUE_LABEL.data_sensitivity).toBe(LEVEL);
    expect(VALUE_LABEL["params.permission_level"]).toBe(PERMISSION);
  });

  it("action_metadata.yaml — loại hành động (≥ 9); PARAMS_BY_ACTION cùng tập loại", () => {
    const types = checked([...metadataYaml.matchAll(/^ {2}([a-z_]+):\s*\{/gm)].map((m) => m[1]!), 9, "action_metadata");
    same(ACTION_TYPE_LABEL, types, "type");
    const params = block(actionPy, "PARAMS_BY_ACTION");
    const byAction = checked([...params.matchAll(/^ {4}"([a-z_]+)":/gm)].map((m) => m[1]!), 9, "PARAMS_BY_ACTION");
    expect(sorted(byAction)).toStrictEqual(sorted(types));
  });

  it("PARAMS_BY_ACTION — mọi khoá params có nhãn khoá; nhãn params.* thừa → đỏ (≥ 6 khoá)", () => {
    const params = block(actionPy, "PARAMS_BY_ACTION");
    const keys = checked(sorted(new Set([...params.matchAll(/"([a-z_]+)":\s*ParamKey\(/g)].map((m) => m[1]!))), 6, "params keys");
    const fe = Object.keys(FLAT_KEY_LABEL).filter((k) => k.startsWith("params.")).map((k) => k.slice("params.".length));
    expect(sorted(fe)).toStrictEqual(keys);
  });

  it("slots.yaml — account_type (=3)", () => {
    const m = /account_type:\s*\{pattern:\s*'\^\(([^)]*)\)\$'\}/.exec(slotsYaml);
    if (!m) throw new Error("slots.yaml: không thấy pattern account_type");
    same(ACCOUNT_TYPE, checked(m[1]!.split("|"), 3, "account_type"), "params.account_type");
  });

  it("facts.py — FACT_TYPES (≥ 20 khoá) ↔ nhãn khoá facts.*; fact bool ↔ nhãn Có/Không; FACT_VALUE_SETS ↔ bảng nhãn", () => {
    const body = block(factsPy, "FACT_TYPES");
    const types = new Map([...body.matchAll(/^ {4}"([a-z_]+)":\s*([a-z]+),/gm)].map((m) => [m[1]!, m[2]!]));
    checked([...types.keys()], 20, "FACT_TYPES");
    const fe = Object.keys(FLAT_KEY_LABEL).filter((k) => k.startsWith("facts.")).map((k) => k.slice("facts.".length));
    expect(sorted(fe)).toStrictEqual(sorted(types.keys()));
    const bools = [...types].filter(([, t]) => t === "bool").map(([k]) => `facts.${k}`);
    const feBools = Object.entries(VALUE_LABEL).filter(([, v]) => Object.hasOwn(v, "true") && Object.hasOwn(v, "false")).map(([k]) => k).filter((k) => k.startsWith("facts."));
    expect(sorted(feBools)).toStrictEqual(sorted(bools));

    const sets: [string, object, number][] = [
      ["cert_status", CERT_STATUS, 4],
      ["target_account_privilege", PRIVILEGE, 3],
      ["target_user_status", USER_STATUS, 4],
      ["target_disable_reason", DISABLE_REASON, 2],
      ["target_lock_reason", LOCK_REASON, 4],
      ["resource_sensitivity", LEVEL, 3],
      ["existing_permission_level", PERMISSION, 3],
    ];
    const listed = [...block(factsPy, "FACT_VALUE_SETS").matchAll(/^ {4}"([a-z_]+)":/gm)].map((m) => m[1]!);
    expect(sorted(listed)).toStrictEqual(sorted(sets.map(([f]) => f))); // fact chuỗi mới ở backend → đỏ, thêm nhãn
    for (const [fact, labels, min] of sets) {
      same(labels, checked(factSet(fact), min, fact), `facts.${fact}`);
      expect(VALUE_LABEL[`facts.${fact}`]).toBe(labels);
    }
  });
});
