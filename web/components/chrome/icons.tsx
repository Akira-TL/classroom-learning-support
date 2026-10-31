"use client";

import { ArrowClockwise } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { ArrowLeft } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowRight } from "@phosphor-icons/react/dist/csr/ArrowRight";
import { BookOpen } from "@phosphor-icons/react/dist/csr/BookOpen";
import { CaretDown } from "@phosphor-icons/react/dist/csr/CaretDown";
import { ChatsCircle } from "@phosphor-icons/react/dist/csr/ChatsCircle";
import { Check } from "@phosphor-icons/react/dist/csr/Check";
import { CheckCircle } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { Eye } from "@phosphor-icons/react/dist/csr/Eye";
import { FileArrowDown } from "@phosphor-icons/react/dist/csr/FileArrowDown";
import { House } from "@phosphor-icons/react/dist/csr/House";
import { MagnifyingGlass } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { Microphone } from "@phosphor-icons/react/dist/csr/Microphone";
import { Notebook } from "@phosphor-icons/react/dist/csr/Notebook";
import { PaperPlaneTilt } from "@phosphor-icons/react/dist/csr/PaperPlaneTilt";
import { Pause } from "@phosphor-icons/react/dist/csr/Pause";
import { Play } from "@phosphor-icons/react/dist/csr/Play";
import { Plus } from "@phosphor-icons/react/dist/csr/Plus";
import { SignOut } from "@phosphor-icons/react/dist/csr/SignOut";
import { Trash } from "@phosphor-icons/react/dist/csr/Trash";
import { UploadSimple } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { UserCircle } from "@phosphor-icons/react/dist/csr/UserCircle";
import { Users } from "@phosphor-icons/react/dist/csr/Users";
import { WarningCircle } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { X } from "@phosphor-icons/react/dist/csr/X";
import type { IconProps } from "@phosphor-icons/react/lib";

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
