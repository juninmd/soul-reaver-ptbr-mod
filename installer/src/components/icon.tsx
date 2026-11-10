import type { IconName } from '../installer/model';

const paths: Record<IconName, string> = {
  arrow: 'M4 12h15m-6-6 6 6-6 6', check: 'm5 12 4 4L19 6', folder: 'M3 7V5h6l3 3h9v11H3V7Z',
  shield: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6',
  voice: 'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  film: 'M3 4h18v16H3V4Zm4 0v16M17 4v16M3 9h4m-4 6h4m10-6h4m-4 6h4',
  rune: 'm12 2 7 10-7 10-7-10 7-10Zm0 0v20m-7-10h14', restore: 'M3 10a9 9 0 1 1 2 9M3 4v6h6m3-3v6l4 2',
  close: 'm6 6 12 12M6 18 18 6', minus: 'M5 12h14', maximize: 'M5 5h14v14H5V5Z',
  pause: 'M8 5v14M16 5v14', play: 'm8 4 12 8-12 8V4Z', settings: 'M4 7h16M4 17h16M8 4v6M16 14v6',
  spark: 'm12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z',
  alert: 'M12 3 2 20h20L12 3Zm0 6v5m0 3v.5',
};

export default function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return (
    <svg className={`icon ${className}`} width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}
