/**
 * The login page renders without the standard app chrome (sidebar,
 * header, environment banner). This segment layout simply passes the
 * children through so those components don't intercept the request.
 */
export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
