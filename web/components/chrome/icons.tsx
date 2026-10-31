"use client";

import {
  ArrowClockwise, ArrowLeft, ArrowRight, BookOpen, CaretDown, ChatsCircle,
  Check, CheckCircle, Eye, FileArrowDown, House, MagnifyingGlass, Microphone,
  Notebook, PaperPlaneTilt, Pause, Play, Plus, SignOut, Trash, UploadSimple,
  UserCircle, Users, WarningCircle, X,
} from "@phosphor-icons/react";
import type { IconProps } from "@phosphor-icons/react";

export const appIcons = {
  classrooms: House,
  review: Notebook,
  teaching: BookOpen,
  publishing: ChatsCircle,
  student: BookOpen,
  parent: Users,
  admin: Users,
  user: UserCircle,
  signOut: SignOut,
  play: Play,
  pause: Pause,
  plus: Plus,
  refresh: ArrowClockwise,
  search: MagnifyingGlass,
  upload: UploadSimple,
  microphone: Microphone,
  download: FileArrowDown,
  delete: Trash,
  warning: WarningCircle,
  check: Check,
  confirmed: CheckCircle,
  close: X,
  chevronDown: CaretDown,
  back: ArrowLeft,
  next: ArrowRight,
  eye: Eye,
  send: PaperPlaneTilt,
} as const;

export type AppIconName = keyof typeof appIcons;

export function AppIcon({ name, size = 20, ...props }: Omit<IconProps, "weight"> & { name: AppIconName }) {
  const Icon = appIcons[name];
  return <Icon {...props} size={size} weight="regular" aria-hidden="true" focusable="false" />;
}
