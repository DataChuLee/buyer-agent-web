"use client";

import React from "react";
import { CheckCircle2, Circle, CircleDotDashed } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export interface AgentStep {
  id: string;
  message: string;
  status: "pending" | "in-progress" | "completed";
}

export default function AgentProgress({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="flex items-center gap-2 px-1 py-1">
        <CircleDotDashed className="h-4 w-4 text-blue-400 animate-[spin_2s_linear_infinite]" />
        <span className="text-sm text-white/60">시작하는 중...</span>
      </div>
    );
  }

  return (
    <div className="relative py-1">
      {/* 세로 연결선 */}
      {steps.length > 1 && (
        <div className="absolute top-3 bottom-3 left-[7px] border-l-2 border-dashed border-white/15" />
      )}

      <ul className="space-y-2">
        <AnimatePresence initial={false}>
          {steps.map((step, index) => (
            <motion.li
              key={step.id}
              className="flex items-center gap-3 pl-0.5"
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                type: "spring",
                stiffness: 500,
                damping: 30,
                delay: index * 0.04,
              }}
            >
              {/* 아이콘 */}
              <div className="relative z-10 flex-shrink-0">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={step.status}
                    initial={{ opacity: 0, scale: 0.7, rotate: -15 }}
                    animate={{ opacity: 1, scale: 1, rotate: 0 }}
                    exit={{ opacity: 0, scale: 0.7, rotate: 15 }}
                    transition={{ duration: 0.18, ease: [0.2, 0.65, 0.3, 0.9] }}
                  >
                    {step.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4 text-green-400" />
                    ) : step.status === "in-progress" ? (
                      <CircleDotDashed className="h-4 w-4 text-blue-400 animate-[spin_2s_linear_infinite]" />
                    ) : (
                      <Circle className="h-4 w-4 text-white/25" />
                    )}
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* 메시지 */}
              <span
                className={`text-sm transition-colors duration-300 ${
                  step.status === "completed"
                    ? "text-white/35 line-through"
                    : step.status === "in-progress"
                      ? "text-white"
                      : "text-white/30"
                }`}
              >
                {step.message}
              </span>

              {/* in-progress 뱃지 */}
              {step.status === "in-progress" && (
                <motion.span
                  className="ml-auto flex-shrink-0 rounded-full bg-blue-500/15 px-2 py-0.5 text-[11px] text-blue-400"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.2 }}
                >
                  진행 중
                </motion.span>
              )}
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </div>
  );
}
