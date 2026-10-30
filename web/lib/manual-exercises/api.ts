import { z } from "zod";
import { request } from "../api";
import { exercisesSchema } from "../exercises";
import type { Exercise } from "../exercises";

const recordSchema = z.object({
  id: z.string(), classroom_id: z.string(), origin: z.literal("teacher_manual_general"),
  initial_exercises: exercisesSchema, exercises: exercisesSchema, created_by: z.string(),
  reviewed_by: z.string().nullable(), revision: z.number().int().positive(),
  status: z.enum(["pending", "confirmed", "rejected"]), adopted: z.boolean(), adopted_by: z.string().nullable(),
});
export type ManualExerciseRecord = z.infer<typeof recordSchema>;
const path = (cid: string) => `/classrooms/${encodeURIComponent(cid)}/manual-exercises`;
export const manualExercises = {
  list: (cid: string) => request(path(cid), z.array(recordSchema)),
  create: (cid: string, exercises: Exercise[], idempotency_key: string) => request(
    path(cid), recordSchema, "POST", JSON.stringify({ exercises, idempotency_key }),
  ),
  review: (cid: string, id: string, expected_revision: number,
    action: "confirmed" | "rejected", exercises: Exercise[]) => request(
    `${path(cid)}/${encodeURIComponent(id)}/review`, recordSchema, "PUT",
    JSON.stringify({ expected_revision, action, exercises }),
  ),
  adopt: (cid: string, id: string, expected_revision: number, adopted: boolean) => request(
    `${path(cid)}/${encodeURIComponent(id)}/adoption`, recordSchema, "PUT",
    JSON.stringify({ expected_revision, adopted }),
  ),
};
