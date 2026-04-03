import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

type BrandLogoProps = Omit<ComponentProps<"img">, "src" | "alt">;

export default function BrandLogo({ className, ...props }: BrandLogoProps) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/Buyer_Agent_Image.png"
      alt="Buyer Agent"
      className={cn("block h-10 w-auto object-contain", className)}
      {...props}
    />
  );
}
