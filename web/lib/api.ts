import { z } from "zod";
import { classroomSchema, userSchema } from "./types";
import type { ClassroomContent } from "./types";
import type { DemoRole } from "./types";

const errorSchema = z.object({
  detail: z.union([
    z.string(),
    z.array(z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() })),
  ]),
});

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, method = "GET", body?: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method, body, credentials: "same-origin", cache: "no-store",
      headers: body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, "无法连接应用接口，请检查服务是否启动；当前操作没有确认成功。");
  }
  if (response.status === 204) return schema.parse(undefined);
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new ApiError(response.status, `接口返回非 JSON 内容（HTTP ${response.status}）。`);
  }
  if (!response.ok) {
    const error = errorSchema.safeParse(raw);
    const detail = error.success
      ? typeof error.data.detail === "string"
        ? error.data.detail
        : error.data.detail.map((item) => `${item.loc.join(".")}：${item.msg}`).join("；")
      : "接口没有提供可识别的错误说明";
    throw new ApiError(response.status, `${detail}（HTTP ${response.status}）`);
  }
  const result = schema.safeParse(raw);
  if (!result.success) {
    throw new ApiError(response.status, "接口响应不符合课堂数据格式，未将结果写入页面。");
  }
  return result.data;
}

export const api = {
  me: () => request("/auth/me", userSchema),
  demoLogin: (role: DemoRole, studentId?: string) => request(
    "/auth/demo-login", userSchema, "POST", JSON.stringify({ role,
      ...(role === "student" ? { student_id: studentId ?? "student-01" } : {}) }),
  ),
  logout: () => request("/auth/logout", z.undefined(), "POST"),
  classrooms: () => request("/classrooms", z.array(classroomSchema)),
  classroom: (id: string) => request(`/classrooms/${encodeURIComponent(id)}`, classroomSchema),
  create: (content: ClassroomContent, key: string) => request(
    "/classrooms", classroomSchema, "POST", JSON.stringify({ ...content, idempotency_key: key }),
  ),
  update: (id: string, content: ClassroomContent, revision: number) => request(
    `/classrooms/${encodeURIComponent(id)}`, classroomSchema, "PUT",
    JSON.stringify({ ...content, expected_revision: revision }),
  ),
};
