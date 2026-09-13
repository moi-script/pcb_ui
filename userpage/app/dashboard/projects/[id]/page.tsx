import ProjectDetail from "./ProjectDetail";

// A static export (the desktop build) must know every page at build time.
// Board ids are made at runtime, so it gets one placeholder copy that the
// desktop app serves for any id; ProjectDetail reads the real one from the
// URL. The dev server ignores this and renders any id on demand.
export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function Page() {
  return <ProjectDetail />;
}
