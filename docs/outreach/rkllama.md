# rkllama: contribution + replies (drafts — nothing sent)

rkllama (627★, 31 open issues, actively maintained) is the largest project in
this space. More than half its open issues are environment, driver, conversion
or compatibility problems rather than bugs in rkllama itself. Its maintainer
cannot answer them all; one has sat unanswered for eleven months.

That is not a competitor. That is a queue of people with exactly the problem
npuzoo exists to solve, and a maintainer who would be glad to have it shorter.

**Rule for all of this: be useful first, and be right.** One wrong technical
answer in someone else's tracker costs more than ten correct ones earn. Do not
mention npuzoo in a reply until after the reply has already answered the
question.

---

## 1. PR: add issue templates

rkllama has no `.github/ISSUE_TEMPLATE` — only a docker-publish workflow. Every
bug report arrives in whatever shape the reporter chose, so the maintainer's
first reply is almost always "what board, what driver, what runtime?"

Proposed PR adds two templates. The environment block is the whole point: it
turns a round trip into a single message.

**PR title:** Add issue templates with an environment checklist

**PR body:**

> About half the open issues here turn out to be environment problems — driver
> version, non-vendor kernel, or a model/runtime version mismatch — and each one
> costs a round trip to establish. These templates ask for that up front.
>
> The bug template includes a one-liner that prints board, kernel, NPU driver,
> and the versions of `librkllmrt.so` / `librknnrt.so`, so reporters can paste
> one block instead of answering four questions. It is a single dependency-free
> file, Apache-2.0, reads only `/proc`, `/sys` and the runtime `.so` files, and
> sends nothing anywhere. If you would rather not point at an external script, I
> am happy to replace it with a plain checklist — the templates are the useful
> part either way.

**`.github/ISSUE_TEMPLATE/bug_report.yml`** — fields: what happened, steps,
model file and where it came from, and:

> **Environment**
> ```
> curl -fsSL https://raw.githubusercontent.com/npuzoo/npuzoo/main/standalone/npuzoo-doctor.py | python3
> ```
> Paste the output. If you would rather not run a script, tell us: board, `uname -a`,
> `sudo cat /sys/kernel/debug/rknpu/version`, and
> `strings /usr/lib/librkllmrt.so | grep 'RKLLM SDK'`.

**`.github/ISSUE_TEMPLATE/config.yml`** — point "my model will not load" at a
discussion rather than a new issue.

Offer the fallback genuinely. A maintainer who declines the external link and
takes the plain checklist is still a win: the question gets standardised, and
the next person's log arrives in a shape we can read.

---

## 2. Reply to #97 — "Supported kernel driver versions?"

Open since 2025-12-09. Six comments, none from a maintainer. Two users worked it
out by reading rknn-llm git tags by hand; one wrote "I still haven't gotten an
answer."

Answer it properly, with the table, and credit their work. Do not lead with the
tool.

> Pulling this together, since the thread deserves a real answer.
>
> The driver minimum is a compiled-in constant, so it cannot be read out of the
> binary — these come from reported logs:
>
> | Driver | Behaviour |
> |---|---|
> | 0.8.x | `Your rknpu driver version is too low`, then allocation failures on larger models |
> | 0.9.6 | practical floor |
> | 0.9.7 | what runtime 1.2.x asks for |
> | 0.9.8 | what current images ship |
>
> The runtime version *can* be read directly, and it is not where people look.
> `rkllm-runtime version: %s` is a format string inside the library; the literal
> is in the SDK banner:
>
> ```
> strings /usr/lib/librkllmrt.so | grep 'RKLLM SDK'
> RKLLM SDK (version: 1.3.1 | target: Linux | build: 20cd29809 2026-09-28 ...)
> ```
>
> @gnull — your reconstruction from the tags was right. I extracted the banner
> from every release tag to confirm; build dates and platform support per release
> are [here](https://github.com/npuzoo/npuzoo/blob/main/docs/compatibility.md).
> One trap worth knowing: **1.2.1b1 is not 1.2.1** — it was built seven weeks
> earlier, so a model converted by toolkit 1.2.1 can fail on it.
>
> @flappyjet — happy to run your detection script against boards when I have
> them, if you are still working on it.

Mention npuzoo once, as the source of the table, and never again in that thread.

---

## 3. Reply to #94 — "LLM deployment on RK3566?"

Short, definite, kind. The answer is no, and nobody has said so plainly.

> Short answer: not on the NPU. RK3566/RK3568 appear in no RKLLM release — I
> checked the platform strings compiled into `librkllmrt.so` for every tag from
> 1.1.0 to 1.3.1, and the list is RK3588, RK3576, RK3562, and RV1126B (added in
> 1.2.0). The RKNN side still works, so vision and audio models are fine; LLMs
> will run on the CPU via llama.cpp, which on a 3566 means a very small model.

## 4. Reply to #102 — "Garbage when using librkllmrt v1.2.3"

Do not guess. Ask the one question that discriminates, and say which answer
means what.

> Garbage output rather than a load failure usually means the model and runtime
> are mismatched in a way that still passes the load check. Worth pinning down
> which:
>
> ```
> strings /usr/lib/librkllmrt.so | grep 'RKLLM SDK'
> ```
>
> and the `rkllm-toolkit version:` line the loader prints at init. If the toolkit
> is newer than the runtime you would normally get an explicit error, so if these
> match and the output is still garbage, it is more likely the quantization than
> the pairing — which model and which dtype (w8a8, w8a8_g128, …)?
>
> Asking because group-wise variants and plain w8a8 do not degrade the same way,
> and there is very little published about which combinations stay coherent.

That last paragraph is the real reason to be in this thread. Quality
degradation is the gap nobody is working on, and this is a live instance of it.

---

## What to do with what comes back

Every reply is a data point for the same corpus:

1. A pasted log that `npuzoo explain` does not recognise → new signature, new
   fixture, new test.
2. A driver/runtime pair that contradicts `docs/compatibility.md` → fix the
   table, say so in the thread.
3. A quality complaint with model + dtype → the start of the quantization
   quality dataset, which is the thing that cannot be copied in a weekend.

Reply to everything for the first two weeks. A thread that dies when the author
stops answering is worse than no thread.
