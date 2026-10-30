import { z } from "zod";
import { ApiError, request } from "../api";

const metadataSchema = z.object({
  id: z.string(), revision: z.number().int().positive(), created_at: z.string(),
  status: z.enum(["active", "revoked", "stale", "deleted"]),
});
export type ExportMetadata = z.infer<typeof metadataSchema>;
export interface CreateExport {
  plan_id: string; expected_plan_revision: number; parent_report_id: string | null;
  expected_parent_revision: number | null; idempotency_key: string;
}
export const exportStatus = { active: "有效", revoked: "已撤回", stale: "依据已过期", deleted: "课堂已删除" };
const route = (classroom: string) => `/classrooms/${encodeURIComponent(classroom)}/exports`;
export const downloadUrl = (id: string) => `/api/exports/${encodeURIComponent(id)}/download`;
export const statusUrl = (id: string) => `/api/exports/${encodeURIComponent(id)}/status`;
export const exportsApi = {
  list: (classroom: string) => request(route(classroom), z.array(metadataSchema)),
  create: (classroom: string, body: CreateExport) => request(
    route(classroom), metadataSchema, "POST", JSON.stringify(body),
  ),
  revoke: (classroom: string, metadata: ExportMetadata) => request(
    `${route(classroom)}/${encodeURIComponent(metadata.id)}/revoke`, metadataSchema, "POST",
    JSON.stringify({ expected_revision: metadata.revision }),
  ),
};

export async function previewHtml(id: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(downloadUrl(id), { credentials: "same-origin", cache: "no-store" });
  } catch { throw new ApiError(0, "报告预览连接失败，未打开文件。"); }
  if (!response.ok) {
    const errorSchema = z.object({ detail: z.string() });
    let raw: unknown;
    try { raw = await response.json(); } catch { raw = null; }
    const parsed = errorSchema.safeParse(raw);
    throw new ApiError(response.status, parsed.success ? parsed.data.detail : "报告已不可用，预览失败。");
  }
  if (!response.headers.get("content-type")?.startsWith("text/html")) {
    throw new ApiError(response.status, "报告预览格式不正确，未打开文件。");
  }
  // 报告仅由服务端转义后生成；以额外 CSP 禁用脚本、外部请求及表单。
  const policy = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
  const html = `<meta http-equiv="Content-Security-Policy" content="${policy}">` + await response.text();
  return URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
}
