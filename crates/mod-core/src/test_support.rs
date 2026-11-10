//! Helpers shared by the ignored benchmark tests.

use std::time::Instant;

/// Deterministic incompressible bytes (xorshift), so hashing sees realistic data.
pub(crate) fn noise(seed: u64, len: usize) -> Vec<u8> {
    let mut state = seed | 1;
    let mut out = Vec::with_capacity(len + 8);
    while out.len() < len {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        out.extend_from_slice(&state.to_le_bytes());
    }
    out.truncate(len);
    out
}

pub(crate) fn elapsed_ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

/// Fastest of `runs` executions, in milliseconds.
pub(crate) fn best_ms(runs: usize, mut task: impl FnMut()) -> f64 {
    (0..runs)
        .map(|_| {
            let start = Instant::now();
            task();
            elapsed_ms(start)
        })
        .fold(f64::INFINITY, f64::min)
}

/// Peak resident memory of the process while `task` runs, in MiB (Linux only).
pub(crate) fn peak_rss_mb<T>(task: impl FnOnce() -> T) -> (T, Option<f64>) {
    // Writing 5 resets the high-water mark; unsupported systems report `None`.
    let reset = std::fs::write("/proc/self/clear_refs", "5").is_ok();
    let value = task();
    let peak = reset
        .then(|| std::fs::read_to_string("/proc/self/status").ok())
        .flatten()
        .and_then(|status| {
            status
                .lines()
                .find_map(|line| line.strip_prefix("VmHWM:"))
                .and_then(|rest| {
                    rest.trim()
                        .trim_end_matches("kB")
                        .trim()
                        .parse::<f64>()
                        .ok()
                })
        })
        .map(|kilobytes| kilobytes / 1024.0);
    (value, peak)
}
