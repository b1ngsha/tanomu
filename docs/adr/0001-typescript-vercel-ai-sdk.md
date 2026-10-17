# TypeScript + Vercel AI SDK with a hand-rolled agent loop

Each Capability must be bindable to a different model, and the code should stay clear and controllable for long-term maintenance. So we use the Vercel AI SDK as a uniform model layer and write a thin agent loop ourselves, rather than adopting a heavier framework such as Mastra or LangGraph. The Claude Agent SDK was ruled out because it is Claude-centric and doesn't fit the multi-model requirement. If memory or workflows become too complex to hand-roll, revisit Mastra — it is built on the AI SDK, so migration cost is bounded.
