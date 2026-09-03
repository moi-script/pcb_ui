import PcbBoard from "./PcbBoard";

export default function AuthAside({
  caption,
}: {
  caption: string;
}) {
  return (
    <aside className="relative hidden overflow-hidden border-l border-line bg-panel lg:flex lg:flex-col">
      <div className="substrate absolute inset-0 opacity-60" />
      <div className="relative flex flex-1 flex-col justify-between p-10">
        <div className="flex items-center justify-between">
          <span className="tlabel">TraceWorks · workbench</span>
          <span className="tlabel !text-copper">v0.1</span>
        </div>

        <div className="panel ticked p-1.5">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="tlabel">labExam.kicad_pcb</span>
            <span className="tlabel !text-copper">F.CU + B.CU</span>
          </div>
          <div className="panel-2 aspect-[16/11] p-4">
            <PcbBoard animate showBack className="h-full w-full" />
          </div>
        </div>

        <p className="max-w-sm font-mono text-sm leading-relaxed text-muted">
          {caption}
        </p>
      </div>
    </aside>
  );
}
