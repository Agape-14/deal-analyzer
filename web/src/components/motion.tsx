"use client";

import * as React from "react";
import { motion, useInView, useMotionValue, useSpring, useTransform } from "framer-motion";

/**
 * Minimal motion primitives used across the app.
 *
 * Kept small on purpose — extra effects like HoverTilt / Stagger were
 * removed in the cleanup pass because nothing was using them. Re-add
 * from git history if you want them back.
 */

/** A spring preset that feels like iOS — quick but not snappy. */
export const easeOutSpring = { type: "spring", stiffness: 320, damping: 32, mass: 0.6 } as const;
export const easeOutSnap = { type: "spring", stiffness: 420, damping: 28, mass: 0.55 } as const;

/**
 * Fade + rise entry. Wrap any block that should animate in on mount or
 * when it scrolls into view.
 */
export function FadeIn({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
      transition={{ duration: 0.4, delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/**
 * Animated number that eases from its previous value to the new one.
 * Looks like Robinhood's ticker animation. Optionally formats as
 * currency / %.
 */
export function AnimatedNumber({
  value,
  format,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  className?: string;
}) {
  const motionValue = useMotionValue(value);
  const spring = useSpring(motionValue, { stiffness: 120, damping: 22, mass: 0.6 });
  const display = useTransform(spring, (v) =>
    format ? format(v) : Math.round(v).toLocaleString(),
  );

  React.useEffect(() => {
    motionValue.set(value);
  }, [value, motionValue]);

  return (
    <motion.span data-figure className={className}>
      {display as unknown as string}
    </motion.span>
  );
}
