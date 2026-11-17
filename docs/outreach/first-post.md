# First posts — drafts

Goal of the first post is **not** signups. It is twenty people pasting a
`doctor` output, so the checks stop being guesses. Everything below is written
to survive the obvious reply, which is *"why should I run a stranger's script?"*

Rules we're holding ourselves to:

- Lead with the thing that's useful on its own. The project comes second.
- Say plainly that it's new and thin. People forgive new; they don't forgive
  being oversold.
- One ask, and make it small.
- Never post the same text in two places on the same day.
- Reply to every single response for the first two weeks. That is the whole job.

---

## A. Reddit — r/RockchipNPU, r/OrangePI, r/SBCs

**Title:** A one-file script that tells you why RKLLM won't run on your board

Body:

> I kept seeing the same handful of RK3588 problems come up — `load model file
> error!` with no explanation, `failed to allocate handle ... errno: 12`, and the
> "driver version is too low" warning that turns into something that looks like
> an unrelated OOM three lines later.
>
> So I collected the failure signatures people have posted and wrapped them in a
> single file with no dependencies:
>
> ```
> curl -fsSL https://raw.githubusercontent.com/npuzoo/npuzoo/main/standalone/npuzoo-doctor.py | python3
> ```
>
> It reads `/proc`, `/sys` and your `librkllmrt.so` / `librknnrt.so`, and prints
> what's wrong plus the fix. It sends nothing anywhere — it's ~700 lines, read it
> first if you'd rather (and you should, it's piped into python).
>
> It also takes a log:
>
> ```
> ./your-demo 2>&1 | python3 npuzoo-doctor.py --explain
> ```
>
> Honest status: the thresholds come from reports I found publicly, not from
> boards I own. So it may be wrong about yours, and that's the thing I'd most
> like to know. **If you run it, please paste the output** — working or broken,
> both are useful. Especially if you're on Armbian edge, an 8 GB board, or
> anything that isn't an Orange Pi 5.
>
> Source and what it's based on: https://github.com/npuzoo/npuzoo

---

## B. Radxa / Orange Pi / Armbian forums

Same substance, calmer, and lead with the board. Forum readers are allergic to
anything that smells like a product launch.

**Title:** Script to diagnose RKNPU / RKLLM setup problems — looking for test output

> Running LLMs on RK3588 breaks in a small number of repeated ways, and the
> error messages rarely name the real cause. I put the known ones into a single
> dependency-free Python file that checks the board and explains a failing log.
>
> [one-liner]
>
> I don't yet own every board it claims to support, so some of its thresholds
> are inferred rather than measured. If you have a few seconds, running it and
> pasting the output here would directly improve it — particularly the driver
> version it reports and whether it got your chip right.
>
> Apache-2.0, source here: [link]. Happy to take corrections in this thread
> rather than on GitHub if that's easier.

---

## C. Hacker News — not yet

Hold this until there are measured numbers on real hardware. A "Show HN" with
inferred thresholds and no benchmark data gets taken apart, and you only get
one first impression there.

---

## D. Discord / X — short form

> npuzoo doctor: one file, no install, tells you why RKLLM won't run on your
> RK3588/RK3576 board — old driver, missing NPU node, toolkit/runtime mismatch,
> model too big for your RAM. Pipe a failing log through `--explain` and it names
> the cause.
>
> It's new and the thresholds are inferred, not measured. If you run it, paste
> the output — that's how it stops being inferred.
>
> github.com/npuzoo/npuzoo

---

## What to do with the replies

Every pasted output is data. For each one:

1. Save it as a fixture in `tests/logs/` (strip anything identifying).
2. If `doctor` got it wrong, fix the check and say so in the thread, by name:
   *"you were right, 0.9.6 on RK3576 doesn't behave like 0.9.6 on RK3588 — fixed."*
   Visible correction is what earns the next twenty.
3. If it got it right, say nothing in the repo and just thank them.

The failure mode to avoid: collecting outputs and going quiet for three weeks.
A thread that dies after the author stops replying is worse than no thread.
