"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { cn } from "@/lib/utils";

interface BorderBeamProps {
  size?: number;
  duration?: number;
  delay?: number;
  colorFrom?: string;
  colorTo?: string;
  className?: string;
  style?: CSSProperties;
  reverse?: boolean;
  initialOffset?: number;
  borderWidth?: number;
}

export function BorderBeam({
  className,
  size,
  delay = 0,
  duration = 6,
  colorFrom = "#ffaa40",
  colorTo = "#9c40ff",
  style,
  reverse = false,
  initialOffset = 0,
  borderWidth = 1,
}: BorderBeamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoSize, setAutoSize] = useState(0);

  useEffect(() => {
    if (size || !containerRef.current) {
      return;
    }

    const element = containerRef.current;
    const updateSize = () => {
      const { width, height } = element.getBoundingClientRect();
      setAutoSize(Math.ceil(Math.hypot(width, height)));
    };

    updateSize();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(updateSize);
    observer.observe(element);

    return () => observer.disconnect();
  }, [size]);

  const beamSize = size ?? (autoSize || 220);

  const ringMaskStyle: CSSProperties = {
    padding: `${borderWidth}px`,
    WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
    WebkitMaskComposite: "xor",
    maskComposite: "exclude",
  };

  const beamStyle = {
    width: `${beamSize}px`,
    height: `${beamSize}px`,
    animationDuration: `${duration}s`,
    animationDelay: `${-delay}s`,
    animationDirection: reverse ? "reverse" : "normal",
    transform: `translate(-50%, -50%) rotate(${(initialOffset / 100) * 360}deg)`,
    "--beam-from": colorFrom,
    "--beam-to": colorTo,
    ...style,
  } as CSSProperties;

  return (
    <div ref={containerRef} className="pointer-events-none absolute inset-0 rounded-[inherit]" style={ringMaskStyle}>
      <div
        className={cn(
          "absolute left-1/2 top-1/2 animate-spin bg-[conic-gradient(from_0deg,transparent_0deg,var(--beam-from)_95deg,var(--beam-to)_165deg,transparent_240deg)] opacity-95",
          className
        )}
        style={beamStyle}
      />
    </div>
  );
}
