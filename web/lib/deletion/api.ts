import { z } from "zod";
import { request } from "../api";

export const deletionSchema = z.object({
  id: z.string(), classroom_id: z.string(), revision: z.number().int().positive(), created_at: z.string(),
  local_status: z.enum(["pending", "complete", "failed"]), local_complete: z.boolean(),
  external_status: z.literal("not_requested"), external_pending: z.boolean(),
  remaining_files: z.number().int().nonnegative(), error: z.string().nullable(), notice: z.string(),
});
const createSchema = z.object({
  expected_revision: z.number().int().positive(), idempotency_key: z.string().min(8).max(100),
  confirmation: z.string().min(1).max(200),
});
export type DeletionView = z.infer<typeof deletionSchema>;
export type DeleteInput = z.infer<typeof createSchema>;
export const deletionApi = {
  create: (classroom: string, body: DeleteInput) => request(
    `/classrooms/${encodeURIComponent(classroom)}/deletion`, deletionSchema, "POST",
    JSON.stringify(createSchema.parse(body)),
  ),
  get: (id: string) => request(`/classroom-deletions/${encodeURIComponent(id)}`, deletionSchema),
  retry: (id: string) => request(`/classroom-deletions/${encodeURIComponent(id)}/retry`, deletionSchema, "POST"),
};
