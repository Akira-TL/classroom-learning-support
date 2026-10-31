import type { DemoRole, User } from "../../lib/types";

export const demoRoleNames: Record<DemoRole, string> = {
  teacher: "教师", head_teacher: "班主任", student: "学生", parent: "家长", teaching_director: "教导主任",
};
export const demoRolePermissions = {
  teacher: "teacher", head_teacher: "teacher", student: "student", parent: "parent", teaching_director: "admin",
} as const;
export function sessionRoleName(user: User) {
  const role = user.display_role;
  if (role && demoRolePermissions[role] === user.role) return demoRoleNames[role];
  return { teacher: "教师", student: "学生", parent: "家长", admin: "教导主任" }[user.role];
}
