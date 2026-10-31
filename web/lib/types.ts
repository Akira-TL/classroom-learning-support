import { z } from "zod";

export const demoRoleSchema = z.enum(["teacher", "head_teacher", "student", "parent", "teaching_director"]);
export type DemoRole = z.infer<typeof demoRoleSchema>;

export const userSchema = z.object({
  id: z.string(),
  role: z.enum(["teacher", "student", "parent", "admin"]),
  student_id: z.string().nullable().optional(),
  display_role: demoRoleSchema.optional(),
});

export const questionSchema = z.object({
  id: z.string().trim().min(1).max(80),
  text: z.string().trim().min(1).max(6000),
  reference_answer: z.string().trim().min(1).max(6000),
  diagram_required: z.boolean(),
  diagram_description: z.string().trim().min(1).max(4000).nullable(),
});

export const contentSchema = z.object({
  title: z.string().trim().min(1).max(200),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  objective: z.string().trim().min(1).max(2000),
  students: z.array(z.string().regex(/^student-(0[1-9]|10)$/)).min(1).max(10),
  questions: z.array(questionSchema).min(1).max(30),
  source: z.string().trim().min(1).max(1000),
  authorization: z.string().trim().min(1).max(2000),
});

export const classroomSchema = contentSchema.extend({
  id: z.string(),
  teacher_id: z.string(),
  revision: z.number().int().positive(),
});

export type User = z.infer<typeof userSchema>;
export type Question = z.infer<typeof questionSchema>;
export type ClassroomContent = z.infer<typeof contentSchema>;
export type Classroom = z.infer<typeof classroomSchema>;

export function emptyClassroom(): ClassroomContent {
  const now = new Date();
  const date = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0")].join("-");
  return {
    title: "", date, objective: "", students: [], questions: [emptyQuestion(1)],
    source: "成人模拟教学材料", authorization: "",
  };
}

export function emptyQuestion(index: number): Question {
  return {
    id: `question-${index}`, text: "", reference_answer: "",
    diagram_required: false, diagram_description: null,
  };
}
