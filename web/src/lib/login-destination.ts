const APP_ORIGIN = "https://app.invalid";
const ENCODED_PATH_SEPARATOR_OR_CONTROL = /%(?:25)*(?:2f|5c|0[0-9a-f]|1[0-9a-f]|7f)/i;

export function loginDestination(next: string | null | undefined): string {
  if (!next?.startsWith("/") || next.startsWith("//") || /[\\\u0000-\u001f\u007f]/.test(next)) {
    return "/";
  }

  const destination = new URL(next, APP_ORIGIN);
  // Canonicalization can turn dot segments into a leading double slash.
  if (
    destination.origin !== APP_ORIGIN ||
    destination.pathname.startsWith("//") ||
    ENCODED_PATH_SEPARATOR_OR_CONTROL.test(destination.pathname)
  ) {
    return "/";
  }
  return destination.pathname + destination.search + destination.hash;
}
