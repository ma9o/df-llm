# Room conversation test — 2026-09-06

Completed direct conversations with **11 people**, using only DFHack text,
structured state, and harness actions after the user cleared the earlier action
prompt. Each person received a greeting, a question about their feelings, and a
question about local troubles. The transcript contains **66 reports: 33 player
utterances and 33 replies**, matched by conversation ID and speaker ID.

| Person | What they said |
|---|---|
| Rigu Kádhehan, head executioner | Sad about separation from Pathril Gulfvaults. Warned about the troglodyte Odmu Rampartruled. |
| Ibu Cilciro, baroness | Misses Struslot Paddlerasp and is resisting sadness. Gave the same troglodyte warning. |
| Ustres Mekgosmárbok, child | Also misses Struslot Paddlerasp. Gave the troglodyte warning and expressed disapproval of the adventurer's undertaking. |
| Alá Fensastkadi, child | Enjoyed reciting **Time Knows**. Gave the troglodyte warning. |
| Iguk Utaglegu, child | Also misses Struslot Paddlerasp. Gave the troglodyte warning; greeted us with a remark about the weather and disapproval of our undertaking. |
| Nastrisp Gukiulet, child | Asked about dreams and wanted a story. Gave the troglodyte warning. |
| Par Somegkastrol, child | Enjoyed **Sushsath Amazedrinkers'** recitation of **Time Knows**. Gave the troglodyte warning. |
| Ithev Xemgib, bowman | Was unimpressed by **Alá's** recitation of **Time Knows**. Warned that the troll **Kozi Spatterspited the Wisp of Torches** has been attacking them. |
| Jestri Ceruabba, crossbowman | Doing alright. Reported a recent leadership change in **The Council of Hearts**. |
| Utast Cobisiñur, pikeman | Said he sometimes goes with the flow. Reported the same leadership change. |
| Utag Ushuslestruh, clothier | Said “It's my mess.” Greeted us as a servant of Akmol and reported the same leadership change. |

The leadership report literally names **Spepip Hoaryscolded** as both the new
lady and the person replaced. We preserved that oddity rather than inferring a
different predecessor.

Seven direct replies independently named Odmu. Claims about monsters and local
politics are NPC reports; we have not investigated them. Nearby conversations
also mentioned a hydra, titan, and bronze colossus. Those were incidental chatter
and are excluded from the direct-conversation table.

The first eight rows cover everyone still visible from the original room roster
when we resumed; the last three are visitors who arrived during the test.
Specut, the high justiciar from the earlier roster, was no longer visible when
we resumed. Another arriving clothier, Issok, left the map viewport before we
could speak; the harness rejected that selection. More visitors continued to
arrive, so this is a completed encounter roster, not a claim that everyone
subsequently entering the room has been interviewed.

The adventurer remained at `(76,73,128)`, with full blood and no wounds. The test
ended at world frame 1435 with the conversation picker closed and no detected
modal. No movement was needed for the conversations.

Evidence: [direct transcript](.df-llm/room-transcript.json),
[full action/observation log](.df-llm/conversations.jsonl), and
[ending observation](.df-llm/post-conversation-state.json).

The harness now exposes full conversation labels, participant IDs, and persistent
report text. `select_unit` resolves the selected person's current map location
through the game viewport; `dismiss` handles one help/announcement page. “More”
and “Okay” were both exercised live, including rejecting movement while a prompt
was present.
