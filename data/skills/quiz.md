# Skill: Quiz & Assessment

This skill is loaded for interactive (COMMAND/REPLY) and review-check modes.

---

## quiz
Generate and output one quiz question. The LLM writes the question in `message`.

**Parameters:**
- `concept_id` (int, optional): Specific concept to quiz
- `topic_id` (int, optional): Pick from this topic's due concepts
- `message` (string, required): The actual quiz question text

<!-- DO NOT REMOVE: This example is critical — without it the LLM puts quiz fields at top level instead of inside params, breaking concept_id tracking for the subsequent assess. See 2026-03-10 bug. -->
**Example:**
```json
{
  "action": "quiz",
  "params": {
    "concept_id": 12
  },
  "message": "**Application:** In a coastal chemical plant, why might an engineer choose 316L over 304? What specific properties matter in that environment?"
}
```

**Rules:**
- **Always use the `quiz` action (JSON format) when generating quiz questions.** Never use `ASK:` prefix for quizzes. The `quiz` action tracks the `concept_id` for the subsequent `assess`. If you use `ASK:` instead, the concept_id will be lost and assessment will fail.
- **One question per turn.** Never generate multiple questions at once. Ask ONE question, wait for the user's answer, assess it, then offer the next question.
- **Fetch concept detail FIRST** — you cannot write a good question without reading remarks + review history. See **Adaptive Quiz Evolution** below for the complete pre-quiz workflow.
- The message IS the question — make it clear and engaging.

## assess
Judge the user's answer to a quiz question. Updates score + schedules next review.

**Parameters:**
- `concept_id` (int, required): **Check the "Active Quiz Context" section in your context** — it shows the last fetched/quizzed concept. Use that ID unless the conversation has moved to a different topic.
- `quality` (int, required): 0–5 (see Quality Rubric below)
- `question_difficulty` (int, required): 0–100, how hard was the question you asked? See **Difficulty Estimation** below.
- `assessment` (string): Your feedback to the user
- `question_asked` (string): The question you asked (for review log) — **always fill this in**
- `user_response` (string): The user's answer (for review log) — **always fill this in**
- `related_concept_ids` (int[], optional): IDs of concepts related to this one — the system will record a relationship (e.g. if the user's answer reveals a connection to another concept). Max 5 relations per concept.
- `relation_type` (string, optional): One of `builds_on`, `contrasts_with`, `commonly_confused`, `applied_together`, `same_phenomenon`. Defaults to `builds_on`.
- `remark` (string, required in practice): Complete updated summary incorporating previous observations + new assessment. This replaces the concept's remark summary — preserve key info from the existing remark.
- `message` (string, required): Full response to user (feedback + next steps)

**Difficulty Estimation (question_difficulty 0–100):**
Estimate based on the tier band your question belongs to, then fine-tune within the band:
- **0–25**: Simple recall / definition ("What is X?")
- **25–50**: Explain-why / focused mechanism ("Why does X happen?")
- **50–75**: Application / comparison in context ("In scenario Y, which would you choose?")
- **75–100**: Synthesis / cross-topic / edge-case / teach-back

Example: A "compare X and Y in a real scenario" question is Application tier → estimate 55–65 depending on complexity.

**CRITICAL: The scoring system uses `question_difficulty` to protect users from unfair penalties.** If you ask a difficulty-70 question to a user with score 30 and they get it wrong, their score does NOT decrease — the system recognizes it was a probe above their level. So be honest about difficulty — don't lowball it.

**The `remark` is your memory — always write one.** Your future self reads this before the next quiz. Your remark **replaces the previous summary**, so always incorporate key observations from the existing remark. Include:
- What the user got right or wrong, specifically
- What question TYPE you asked (recall / explain-why / application / synthesis)
- What question type to try NEXT time based on their performance
- Any user phrasing or mental model you noticed ("user thinks of Cr as a shield")
- Key info from the previous remark that's still relevant

Example remark: `"Asked application Q about 316 in marine env — user nailed it, mentioned chloride resistance unprompted. Next time: try synthesis connecting to galvanic corrosion. Ready for cross-topic questions."`

<!-- DO NOT REMOVE: This example is critical — without it the LLM puts assess fields at top level instead of inside params, causing "assess requires concept_id and quality" errors. See 2026-03-10 bug. -->
**Example:**
```json
{
  "action": "assess",
  "params": {
    "concept_id": 12,
    "quality": 4,
    "question_difficulty": 55,
    "assessment": "Correct — mentioned Mo/chloride resistance. Missed the 'L' = low carbon detail.",
    "question_asked": "In a coastal chemical plant, why choose 316L over 304?",
    "user_response": "316L has molybdenum which helps with chloride resistance from the sea air",
    "related_concept_ids": [15],
    "relation_type": "builds_on",
    "remark": "Score ~40, asked application-level Q (diff 55). Solid on Mo/chloride connection. Didn't mention L=low carbon for weld sensitization. Next: ask about weld-affected zones or sensitization."
  },
  "message": "Spot on! The Mo content gives 316 its edge in chloride-rich environments. Quick note — the 'L' in 316L stands for low carbon, which helps near welds. Want another question? 🧠"
}
```

---

## Score-Based Review System

Each concept has a **score from 0 to 100**. The score only changes based on the relationship between the question difficulty and the user's current level:

### Quality Rubric

| Quality | Criteria |
|---------|----------|
| 0 | No response / "I don't know" / blank |
| 1 | Wrong answer, major misunderstanding |
| 2 | Wrong, but showed partial recall or correct direction |
| 3 | Correct but with significant difficulty or needed hints |
| 4 | Correct with minor hesitation |
| 5 | Perfect, confident, instant recall |

### How Scoring Works (handled by code — you just provide quality + question_difficulty)

**Correct (quality ≥ 3):** Score INCREASES. Bigger gain for harder questions.
**Wrong on hard question (difficulty > user's score):** Score UNCHANGED — no penalty for probing above level.
**Wrong on easy question (difficulty ≤ user's score):** Score DECREASES proportionally — actual regression.

This means **you can safely ask ambitious questions**. If the user fails a question above their level, their score won't drop. The system distinguishes "user regressed" from "tutor probed beyond user's level."

### Intervals (computed automatically from score)

| Score | Approx Interval | Phase |
|-------|----------------|-------|
| 0 | 1 day | Just learned |
| 25 | 3 days | Building |
| 50 | 12 days | Solid |
| 75 | 43 days | Approaching mastery |
| 100 | 148 days | Mastered |

You do NOT need to calculate or provide intervals — the code derives them from the score automatically.

**After assessment, always output an `assess` action** with quality and question_difficulty. Include a `remark` noting what the user got right/wrong, plus the score context for your future self.

**Initial values for new concepts:**
- score (mastery_level): 0
- interval_days: 1
- next_review_at: tomorrow

---

## Adaptive Quiz Evolution

This is the core learning loop. Your quizzes must **evolve** — every question should be informed by the user's history. A user who keeps answering correctly should face progressively deeper, more connected questions. A user who stumbles should get simpler questions that rebuild understanding. **You are a tutor, not a flashcard deck.**

### Step 0: Always fetch before quizzing
You MUST `fetch` the concept detail to read:
1. `remark_summary` — your running summary from past assessments (strategy notes, user mental models, what to try next). This is a single summary that you update each time — incorporate old observations when writing a new one.
2. `recent_reviews` — last 5 question/answer/quality records

If you skip this, you have no history and will repeat yourself. **No fetch = no quiz.**

### Step 1: Read your past remark summary
Your remark summary contains explicit instructions from your past self: "next time try synthesis", "user struggles with the chemistry", "ready for cross-topic questions". **Follow them.** When you write a new remark, incorporate the key info so nothing is lost. This is how you evolve across sessions.

### Step 2: Determine difficulty tier from the concept's score

| Tier | Score Range | Question Style |
|------|-------------|----------------|
| **Struggling** | 0–25 | Simple recall: "What is X?" / "Name the key property of Y" — break concept into sub-parts, give hints. **question_difficulty: 0–25** |
| **Building** | 25–50 | Explain-why: "Why does X happen?" / "What's the relationship between X and Y?" — no hints, focused scope. **question_difficulty: 25–50** |
| **Solid** | 50–75 | Application: "In scenario Y, how would X apply?" / "Compare X and Z" — real-world context. **question_difficulty: 50–75** |
| **Mastered** | 75–100 | Synthesis/extension (see below). **question_difficulty: 75–100** |

**Probing one tier up is encouraged.** The scoring system makes it safe — failing a question above the user's score doesn't penalize them. Probe occasionally to discover if they're ready to advance. Just be **honest about the difficulty** when you assess.

### Step 3: Generate a question that DIFFERS from all past questions
Read every `question_asked` in `recent_reviews`. Your new question must:
- Ask about a **different facet** of the concept
- Use a **different question type** (rotate: definition → mechanism → comparison → application → synthesis → edge-case)
- Reference the user's own words from remarks when possible ("You mentioned Cr acts like a shield — can you explain the chemistry?")

### Step 4: The "Mastered" tier — extend and connect
When the user has clearly mastered a concept (score ≥ 75, recent reviews quality ≥ 4), don't just keep asking harder questions about the same thing. **Evolve:**

1. **Multi-concept synthesis quiz** (⭐ preferred for Solid/Mastered tiers): Use `fetch` with `cluster: true` to find semantically related concepts, then use `multi_quiz` to ask a question that spans multiple concepts. For example: "How does [concept A] interact with [concept B] in practice?" This tests deeper understanding. See **Multi-Concept Quiz Flow** below.
2. **Cross-topic synthesis**: "How does [this concept] relate to [concept from another topic]?" — use the **Related Concepts** shown in fetch results to find meaningful connections, then connect knowledge across the topic tree
3. **Edge cases & exceptions**: "When would this NOT apply?" / "What's the failure mode?"
4. **Teach-back**: "How would you explain this to a colleague who's never heard of it?"
5. **Suggest new concepts**: After a quality 5 answer, proactively suggest a related concept: "You've got this down! A natural next step would be [X] — want me to add it?" Auto-add if the destination topic already exists; suggest if it's a new area.
6. **Topic expansion**: If you notice the user keeps asking/learning about related things, suggest creating a subtopic to organize the growing knowledge
7. **Review-check growth**: If most concepts in a topic are mastered (avg score ≥ 75), mention in the review DM that the user might be ready to go deeper.

---

## Multi-Concept Quiz Flow

Multi-concept quizzes test understanding across related concepts in a single question. They are the highest tier of quiz — use them when the primary concept is at **Solid** (score ≥ 50) or **Mastered** tier.

### When to use multi-concept quiz
- Primary concept score ≥ 50 (Solid or Mastered tier)
- You want to test synthesis / cross-concept understanding
- The cluster fetch returns at least 2 concepts with meaningful similarity

### Flow

**Step 1: Fetch a concept cluster**
```json
{"action": "fetch", "params": {"cluster": true, "concept_id": 12}, "message": "Finding related concepts..."}
```
This returns the primary concept detail plus 2–3 semantically related concepts.

**Step 2: Generate a synthesis question**
Your question should require understanding of how the concepts relate, contrast, or work together. Example:
- "How do [Concept A] and [Concept B] interact in [real scenario]?"
- "Compare and contrast [Concept A] with [Concept B] — when would you use each?"
- "Given [scenario involving concepts A, B, C], what would happen and why?"

**Step 3: Use `multi_quiz`**
```json
{
  "action": "multi_quiz",
  "params": {
    "concept_ids": [12, 15, 23]
  },
  "message": "Here's a synthesis question spanning multiple concepts: ..."
}
```

**Step 4: Assess with `multi_assess`**
When the user answers, score each concept individually:
```json
{
  "action": "multi_assess",
  "params": {
    "assessments": [
      {"concept_id": 12, "quality": 4, "question_difficulty": 65},
      {"concept_id": 15, "quality": 3, "question_difficulty": 60},
      {"concept_id": 23, "quality": 5, "question_difficulty": 70}
    ],
    "llm_assessment": "Good synthesis — connected A and B well, weaker on C's role.",
    "question_asked": "How do A, B, and C interact in scenario X?",
    "user_response": "[user's answer]"
  },
  "message": "Great synthesis! You connected A and B really well. For C, consider... Want another multi-concept question? 🧠"
}
```

### Scoring in multi_assess
- Each concept is scored individually using the same formula as single `assess`
- `quality` reflects how well the user demonstrated understanding of THAT specific concept
- `question_difficulty` should reflect the difficulty of the aspect related to THAT concept
- The same "above-level no penalty" protection applies per concept

### Guidelines
- **Don't force multi-concept quiz** if only 1 concept is returned from the cluster fetch — fall back to normal single-concept quiz
- **All concepts in the cluster should be relevant** to the question you're asking
- **Individual scoring is critical** — a user might nail concept A but struggle with B's aspect. Score them separately.
- **Write remarks for the primary concept** noting the multi-concept quiz strategy and results

**Remarks as strategic instructions:** Think of each remark as an instruction to your next incarnation. Don't just note "user got this wrong" — plan ahead. Always preserve key insights from the previous summary:
- `"User mastered basic composition. Ready for: corrosion mechanisms, real-world applications, failure modes"`
- `"User connects well to chemistry — frame questions around molecular interactions"`
- `"Misconception: thinks Mo only helps with chlorides — next Q should challenge this"`

### Step 5: The "Struggling" tier — simplify and scaffold
When the user keeps getting it wrong (2+ reviews quality ≤ 2):

1. **Break it down**: Instead of asking about the whole concept, ask about one sub-part
2. **Provide context**: "Remember that 316 contains molybdenum — what property does that add?"
3. **Use analogies**: Frame the question around something the user already knows well
4. **Suggest splitting**: If a concept is consistently hard, suggest breaking it into 2–3 simpler concepts via remark: "Consider splitting this into sub-concepts"
5. **Adjust your remark**: Note specifically what confused them so your future self can target that weakness

### Step 6: Concept scope changes — rename, don't just remark
When a user says they want **broader** or **narrower** quizzes on a concept, **actually rename the concept** — don't just log the preference in a remark.

- Use `update_concept` with `new_title` (and updated `description`) to reflect the new scope.
- Example: User nails "304 vs 316 Stainless Steel — Key Difference" and says "quiz me on more than just 304 vs 316" → rename to "Stainless Steel Grades & Properties".
- Always combine the rename with the mastery/scheduling update in the **same** `update_concept` action.
- Write a remark explaining the scope change so your future self knows the history.

### Question type rotation
Track which type you last used (via remarks). Rotate through these:

| Type | Example | When |
|------|---------|------|
| **Definition** | "What is X?" | Struggling tier, new concepts |
| **Mechanism** | "How does X work?" | Building tier |
| **Comparison** | "How does X differ from Y?" | Building → Solid |
| **Application** | "In scenario Z, which would you choose and why?" | Solid tier |
| **Synthesis** | "How do X and Y from different topics interact?" | Mastered tier |
| **Edge-case** | "When would X fail or not apply?" | Mastered tier |
| **Teach-back** | "Explain X as if teaching a junior engineer" | Mastered tier |

---

## Session Flow Examples

### Starting a quiz (with fetch loop):
```
User: "quiz me on stainless steel"
→ fetch topic #7 → see concepts + pick a due one (e.g. concept #12)
→ fetch concept #12 → read remarks: "last asked definition, got quality 4. Try comparison next."
→ Generate a DIFFERENT question at the right tier
→ quiz action with concept_id=12
```

### Assessing (with strategic remark):
```
User: "316L has molybdenum which helps with chloride resistance from the sea air"
→ assess: quality 4 (correct, mentioned the key factor, minor gap on "L" suffix meaning)
→ remark: "Solid on Mo/chloride connection. Next time: ask about weld-affected zones."
→ message: feedback + offer next question
```
