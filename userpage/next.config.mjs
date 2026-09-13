/** @type {import('next').NextConfig} */
const desktop = process.env.NEXT_PUBLIC_DESKTOP === "1";

const nextConfig = {
  reactStrictMode: true,
  // The desktop build is plain files in out/, served by desktop/app.py.
  // trailingSlash gives every route its own folder/index.html to serve.
  ...(desktop && {
    output: "export",
    trailingSlash: true,
    images: { unoptimized: true },
  }),
};

export default nextConfig;
