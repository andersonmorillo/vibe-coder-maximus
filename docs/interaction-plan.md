# User–agent interaction plan

Voice-cursor is a terminal voice loop, not a GUI. The research below is mapped onto
spoken commands and the existing talk-then-apply split. No kanban, no AG-UI client.

## What already works

- Talk vs apply: mcp-agent plans and may write `.voice-cursor/request.md`; Firstmate
  only runs after `apply`.
- Start / stop / cancel / quiet, including `stop` canceling an in-flight run.
- Barge-in during agent work; **stop / be quiet / Enter during TTS** stops speech and waits for your next sentence (higher mic gate while speaking).
- Wake-word gating and a Whisper near-miss list so `apple` does not mean apply.
- Speakable replies (strip fences) and a live `you>` transcript line.

That is Hatchworks' two-phase action (plan → execute) plus basic start/stop.

## Research (what to steal)

Sources:

- [Agent UX patterns (Hatchworks)](https://hatchworks.com/blog/ai-agents/agent-ux-patterns/)
  — receipts, undo, checkpoints, activity you can ask for; chat is a side channel.
- [Coding-agent GUI overhaul (LoreAI)](https://loreai.dev/blog/coding-agent-gui-ux-overhaul)
  — ambient status, notify on decisions not on every token, replay later.
- [Harness anatomy (Mastra)](https://mastra.ai/blog/anatomy-of-a-coding-agent)
  — interrupt, queue a follow-up, steer, survive restart.
- [Agentic UX 2026 (Zylos)](https://zylos.ai/research/2026-05-28-agentic-ux-frontend-design-patterns-ai-agents/)
  — plan-and-execute preview, progressive disclosure.
- [Interruption handling](https://relinns.com/blogs/interruption-handling-in-voice-agents)
  and [semantic turn-endpointing](https://github.com/agentpatternscatalog/patterns/blob/main/patterns/semantic-turn-endpointing.md)
  — `yeah` / `uh-huh` is not a barge-in; do not abort the run.

## Gaps in this product

1. Discoverability: commands live in the README, not in the ear.
2. No spoken status: you cannot ask what is pending after planning.
3. No repeat: TTS is one-shot.
4. No local undo: the spec stays until the next write.
5. Backchannel / wake-miss during a run cancels work (treats `yeah` as a new prompt).

## This slice (ship now)

Voice-native Level-2 controls, no new dependencies:

| Say | Does |
| --- | --- |
| `help` / `what can I say` | Spoken command map |
| `status` / `what's the plan` | Read back the pending spec |
| `repeat` / `say that again` | Re-speak the last reply |
| `forget that` / `scratch that` | Drop the local spec (idle); cancel the run (busy) |
| `yeah` / `ok` / `uh-huh` | Ignored; never sent to talk; never aborts a run |
| session start | One-line greeting with the three verbs: talk, apply, help |

## Later (do not build until a real blocker)

- Queue `also …` while apply is in flight (Mastra follow-up queue).
- Poll Firstmate and speak only decision/blocker lines (ambient monitoring).
- Semantic end-of-turn instead of a fixed pause.
- Timeline / replay of a session.
- Extra confirm step after `apply` (talk-then-apply already is the gate).
