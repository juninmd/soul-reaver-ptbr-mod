import type { CSSProperties } from 'react';

// Positions are percentages of the 1100 × 1250 illustration, so every layer
// stays registered with the artwork at any window size.
const motes: [x: number, y: number, seconds: number, delay: number][] = [
  [22, 25, 11, 0], [65, 31, 14, -3], [33, 39, 12, -7], [73, 43, 16, -2], [45, 32, 13, -9],
  [29, 49, 15, -5], [59, 26, 12, -11], [82, 34, 17, -6], [15, 50, 14, -8], [52, 45, 11, -4],
];

interface Props {
  /** `hero` and `progress` are alive; `aside` is a dimmed, static backdrop. */
  variant: 'hero' | 'progress' | 'aside';
  /** Stops every ambient animation, e.g. while an operation is paused. */
  still?: boolean;
  label?: string;
}

/** The Nosgoth illustration with ambient light, mist and drifting motes layered on top. */
export default function NosgothScene({ variant, still = false, label }: Props) {
  const ambient = variant !== 'aside';
  return (
    <div className={`scene scene-${variant} ${still ? 'scene-still' : ''}`} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <div className="scene-canvas">
        <img src="/nosgoth.svg" alt="" decoding="async" draggable={false} />
        {ambient && <>
          <span className="scene-corona" />
          <span className="scene-mist scene-mist-far" />
          <span className="scene-mist scene-mist-near" />
          <span className="scene-blade" />
          {motes.map(([x, y, seconds, delay], index) => (
            <span key={index} className="scene-mote" style={{ '--x': `${x}%`, '--y': `${y}%`, '--drift': `${seconds}s`, '--delay': `${delay}s` } as CSSProperties} />
          ))}
        </>}
      </div>
      <div className="scene-shade" />
    </div>
  );
}
