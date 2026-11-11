import { useEffect, useRef } from "react";

// Plotly is large, so it is loaded on first use in its own chunk.
const loadPlotly = () => import("plotly.js-dist-min").then((m) => m.default);

export const palette = ["#0f6e6e", "#3b5ba5", "#b4532a", "#9a6a12", "#6b3fa0", "#2f7d32"];

const baseLayout = {
  margin: { l: 48, r: 12, t: 28, b: 40 },
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "system-ui, sans-serif", size: 12, color: "#1f2328" },
  xaxis: { gridcolor: "#e6e1d6", zeroline: false },
  yaxis: { gridcolor: "#e6e1d6", zeroline: false },
  legend: { orientation: "h", y: -0.2 },
};

type Props = {
  data: object[];
  layout?: Record<string, unknown>;
  height?: number;
};

export function Plot({ data, layout = {}, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    loadPlotly().then((Plotly) => {
      if (cancelled || !ref.current) return;
      const merged = {
        ...baseLayout,
        ...layout,
        xaxis: { ...baseLayout.xaxis, ...(layout.xaxis as object) },
        yaxis: { ...baseLayout.yaxis, ...(layout.yaxis as object) },
        height,
      };
      Plotly.react(ref.current, data, merged, {
        displaylogo: false,
        responsive: true,
        toImageButtonOptions: { format: "svg" },
        // research data must not leave the institute: no "Share chart" (uploads the data to Plotly Cloud)
        showSendToCloud: false,
        modeBarButtonsToRemove: ["sendChartToCloud"],
      });
    });
    return () => {
      cancelled = true;
    };
  }, [data, layout, height]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) loadPlotly().then((Plotly) => Plotly.purge(el));
    };
  }, []);

  return <div ref={ref} style={{ width: "100%", minHeight: height }} />;
}
