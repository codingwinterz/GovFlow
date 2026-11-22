// Motion smoothness of a video, measured with ffmpeg's mpdecimate (default thresholds).
//   node scripts/measure_video.mjs <video> [--from S] [--to S] [--crop W:H:X:Y] [--windows motion.json] [--fast timelapse.json]
// mpdecimate drops every frame that is a near-duplicate of the last kept one; the kept frames are the distinct ones.
// Printed (JSON):
//   distinct_fps         kept frames / measured seconds
//   gaps_over_0_1        intervals between consecutive distinct frames longer than 0.1 s, split into
//                        stutters_0_1_to_0_5 (motion that skipped) and holds_over_0_5 (static: nothing changed)
//   distinct_fps_moving  kept frames / seconds, counting only intervals of 0.5 s or less (a gap over 0.5 s is a
//                        static pause and is left out)
//   stills_over_1_5      intervals between distinct frames longer than 1.5 s (a frozen screen), listed in stills;
//                        with --fast timelapse.json ([{from, to}]) also how many of them touch a time-lapse
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const args = process.argv.slice(2);
const file = args[0];
const opt = (k) => { const i = args.indexOf(k); return i < 0 ? null : args[i + 1]; };
if (!file) { console.error("usage: node scripts/measure_video.mjs <video> [--from S] [--to S] [--crop W:H:X:Y]"); process.exit(1); }
const start = Number(opt("--from") ?? 0);
const end = opt("--to") === null ? null : Number(opt("--to"));
const crop = opt("--crop");

const pre = ["-hide_banner", "-nostats", "-ss", String(start)];
if (end !== null) pre.push("-to", String(end));
const vf = [crop ? `crop=${crop}` : null, "mpdecimate", "showinfo"].filter(Boolean).join(",");
const r = spawnSync("ffmpeg", [...pre, "-i", file, "-vf", vf, "-an", "-f", "null", "-"], { encoding: "utf8", maxBuffer: 1 << 28 });
if (r.status !== 0) { console.error(r.stderr.slice(-800)); process.exit(1); }
const ts = [...r.stderr.matchAll(/Parsed_showinfo.*?pts_time:\s*([0-9.]+)/g)].map((m) => Number(m[1]));
const dur = Number(spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file], { encoding: "utf8" }).stdout);
const seconds = (end ?? dur) - start;
const gaps = ts.slice(1).map((t, i) => t - ts[i]);
const moving = gaps.filter((g) => g <= 0.5);
const movingSeconds = moving.reduce((s, g) => s + g, 0);
const out = {
  file, seconds: +seconds.toFixed(2), distinct: ts.length, distinct_fps: +(ts.length / seconds).toFixed(2),
  gaps_over_0_1: gaps.filter((g) => g > 0.1).length,
  stutters_0_1_to_0_5: gaps.filter((g) => g > 0.1 && g <= 0.5).length,
  holds_over_0_5: gaps.filter((g) => g > 0.5).length,
  moving_seconds: +movingSeconds.toFixed(2), distinct_fps_moving: +(moving.length / movingSeconds).toFixed(2),
};
const stills = ts.slice(1).map((t, i) => ({ from: +(ts[i] + start).toFixed(2), seconds: +(t - ts[i]).toFixed(2) }))
  .filter((x) => x.seconds > 1.5);
out.stills_over_1_5 = stills.length;
const fastFile = opt("--fast");
if (fastFile) {
  const fast = JSON.parse(readFileSync(fastFile, "utf8"));
  out.stills_over_1_5_in_timelapse = stills.filter((x) => fast.some((w) => x.from < w.to && x.from + x.seconds > w.from)).length;
}
out.stills = stills;
// --windows file.json: [{from, to}] in the video's own time. Distinct frames inside them, and gaps over 0.1 s between
// distinct frames that both fall inside the same window (motion that skipped).
const winFile = opt("--windows");
if (winFile) {
  const wins = JSON.parse(readFileSync(winFile, "utf8")).filter((w) => w.from >= start && (end === null || w.to <= end));
  const abs = ts.map((t) => t + start);
  let secs = 0, frames = 0, skips = 0;
  for (const w of wins) {
    const inside = abs.filter((t) => t >= w.from && t < w.to);
    secs += w.to - w.from; frames += inside.length;
    skips += inside.slice(1).filter((t, i) => t - inside[i] > 0.1).length;
  }
  Object.assign(out, { motion_windows: wins.length, motion_seconds: +secs.toFixed(2),
    distinct_fps_in_motion: +(frames / secs).toFixed(2), gaps_over_0_1_in_motion: skips });
}
console.log(JSON.stringify(out));
