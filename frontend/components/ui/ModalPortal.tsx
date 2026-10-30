"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Renders a modal into <body>. A `position: fixed` dialog inside a glass card is clipped to that card, because the card's backdrop blur makes it the
 * containing block; in <body> it covers the whole window. Nothing is rendered on the server or during hydration, so there is no mismatch. */
export function ModalPortal({ children }: { children: ReactNode }) {
  const onClient = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  return onClient ? createPortal(children, document.body) : null;
}
