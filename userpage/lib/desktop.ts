// True in the Windows desktop build (NEXT_PUBLIC_DESKTOP=1, see desktop/).
// That build is a static export served by the Python app itself: the API is
// on the same origin, there is no database server, and there is one local
// user instead of accounts.
export const DESKTOP = process.env.NEXT_PUBLIC_DESKTOP === "1";

/** The single account every desktop install signs in as, silently. */
export const DESKTOP_USER = { name: "Local", email: "local@traceworks.desktop" };
