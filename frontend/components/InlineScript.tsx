/** A script that runs while the browser parses the HTML, before first paint (the pattern in Next's "preventing flash before hydration" guide). React warns
 * about script tags it renders on the client, so the type differs by side and `suppressHydrationWarning` accepts the difference. */
export function InlineScript({ html }: { html: string }) {
  return <script type={typeof window === "undefined" ? "text/javascript" : "text/plain"} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: html }} />;
}
