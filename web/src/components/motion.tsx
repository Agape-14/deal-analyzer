"use client";

import * as React from "react";
import { motion, useInView, useMotionValue, useSpring, useTransform, type MotionValue } from "framer-motion";

/** A spring preset that feels like iOS — quick but not snappy. */
export const easeOutSpring = { type: "spring", stiffness: 320, damping: 32, mass: 0.6 } as const;
export const easeOutSnap = { type: "spring", stiffness: 420, damping: 28, mass: 0.55 } as const;

/**
 * Fade + rise entry. Wrap any block that should animate in on mount or when
 * it scrolls into view.
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
 * Staggered list wrapper. Use with `<StaggerItem>` children to get a
 * cascading entry animation — feels expensive for minimal code.
 */
export function Stagger({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{
        hidden: {},
        show: {
          transition: { staggerChildren: 0.04, delayChildren: delay },
        },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 10 },
        show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] } },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/**
 * Animated number that eases from its previous value to the new one. Looks
 * like Robinhood's ticker animation. Optionally formats as currency / %.
 */
export function AnimatedNumber({
  value,
  format,
  duration = 0.8,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const motionValue = useMotionValue(value);
  const spring = useSpring(motionValue, { stiffness: 120, damping: 22, mass: 0.6 });
  const display = useTransform(spring, (v) => (format ? format(v) : Math.round(v).toLocaleString()));

  React.useEffect(() => {
    motionValue.set(value);
    // duration is baked into the spring; kept as a prop for future tweaks
    void duration;
  }, [value, motionValue, duration]);

  return <motion.span data-figure className={className}>{display as unknown as string}</motion.span>;
}

/** Tilt a card subtly as the cursor moves over it. Magnetic hover. */
export function HoverTilt({ children, className }: { children: React.ReactNode; className?: string }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const rotX = useTransform(y, [-30, 30], [3, -3]);
  const rotY = useTransform(x, [-30, 30], [-3, 3]);

  function onMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * 60 - 30;
    const py = ((e.clientY - rect.top) / rect.height) * 60 - 30;
    x.set(px);
    y.set(py);
  }

  function onMouseLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      style={{ rotateX: rotX, rotateY: rotY, transformPerspective: 900 }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export type { MotionValue };
