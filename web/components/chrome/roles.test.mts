import assert from "node:assert/strict";
import test from "node:test";
import { demoRoleNames, demoRolePermissions, sessionRoleName } from "./roles.ts";
import type { User } from "../../lib/types.ts";

test("五种演示身份共享既有服务端权限边界，班主任保留其展示身份", () => {
  assert.deepEqual(Object.keys(demoRoleNames), ["teacher", "head_teacher", "student", "parent", "teaching_director"]);
  assert.equal(demoRolePermissions.head_teacher, "teacher");
  assert.equal(demoRolePermissions.teaching_director, "admin");
  assert.equal(sessionRoleName({ id: "teacher-01", role: "teacher", display_role: "head_teacher" }), "班主任");
  assert.equal(sessionRoleName({ id: "admin-01", role: "admin", display_role: "teaching_director" }), "教导主任");
});

test("不符合实际角色的展示字段不能冒充其他身份，旧会话仍可正确显示", () => {
  const student: User = { id: "student-03", role: "student", student_id: "student-03" };
  assert.equal(sessionRoleName(student), "学生");
  assert.equal(sessionRoleName({ ...student, display_role: "head_teacher" }), "学生");
  assert.equal(sessionRoleName({ id: "parent-01", role: "parent", display_role: "parent" }), "家长");
});
