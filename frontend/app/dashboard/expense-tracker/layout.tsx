import type { ReactNode } from "react";
import { pageTitle } from "@/lib/navigation";

/** Names this page in the browser tab and in the route announcement. */
export const metadata = { title: pageTitle("expense-tracker") };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
