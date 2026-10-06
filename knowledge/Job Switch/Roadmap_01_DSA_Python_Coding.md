# Job Switch Roadmap 01 — DSA & Python Coding (16 weeks)

> **Goal:** Walk into a Google/Microsoft Online Assessment and a live coding round and solve a LeetCode-Medium-tier problem cold, in Python, while narrating your reasoning — then handle the DE-flavored follow-up ("now do it on a 40GB file that doesn't fit in memory").
>
> **Why this matters:** This is the only track you are starting from **zero** on. Everything else in this folder builds on production experience you already have; this one doesn't. It is also the round that eliminates most candidates before a human ever reads their resume — the OA is automated and unforgiving. Google runs a generalist SWE-style coding bar even for data-titled roles; Microsoft is close behind; Adobe and Cisco are lighter but still expect solid Medium-level coding.
>
> **Prerequisites:** Python syntax at a working level. You write PySpark daily, so this is covered — but see Phase 0, which is not optional.
>
> **Outcome:** ~120–150 problems solved, a notebook series in this folder as the durable artifact, and the ability to talk through a solution out loud without freezing.
>
> **Time budget:** ~5–7 hrs/week × 16 weeks. **Daily, not weekend-blocked** — 45–60 min/day beats one 5-hour Sunday, because pattern recognition is a spaced-repetition skill.

---

## Phase 0 (Week 1) — Python fluency, the actual blocker

**Read this section even if it looks beneath you.** It is here because of measured evidence, not caution.

On 2026-08-05, working `two_sum` — the single most standard warm-up problem in existence — produced **five consecutive failed attempts**. Not one of the five failed on the algorithm. Every failure was Python surface:

| Attempt | What broke | Root cause |
|---|---|---|
| 1 | `for i, j in nums:` | tuple-unpacking a list of plain ints |
| 2 | `sort(list(enumerate(nums)))` | `sort` isn't a function; `sorted` is |
| 3 | `nums[i]+nums[j]` after enumerate | elements became tuples, not ints |
| 4 | sorting `(index, value)` with no `key=` | sorted by index, so nothing reordered |
| 5 | commented the sort out | two-pointer silently requires sorted input |

The algorithm — two pointers converging, move `j` left when the sum is too big — was **correct from attempt 1**. Sixteen weeks of algorithm practice will not fix a Python-surface gap; it will just make every problem take 4× longer and feel like a DSA failure when it isn't one.

**What you'll learn**
- **Iteration:** `enumerate`, `zip`, `range` with step, iterating dicts (`.items()`, `.keys()`, `.values()`)
- **Tuple unpacking:** `a, b = pair`, `for k, v in dict.items()`, when it works and when it raises `cannot unpack non-iterable`
- **Sorting:** `sorted()` vs `list.sort()`, the `key=` parameter, `reverse=`, sorting tuples/dicts, stability
- **Lambda:** only as much as `key=lambda x: x[1]` requires — nothing more
- **Comprehensions:** list, dict, set; with condition; nested (read-only fluency is enough)
- **`collections`:** `Counter` (frequency in one line), `defaultdict` (no more `if k not in d`), `deque` (O(1) both ends)
- **`heapq`:** `heappush`, `heappop`, `nlargest`, `nsmallest` — the top-K primitive
- **Generators:** `yield`, generator expressions, why they matter for the GB-scale round
- **Slicing:** `s[::-1]`, `s[a:b]`, negative indices
- **Strings:** `split`, `join`, `strip`, `isalnum`, `lower` — the parsing toolkit

**Why it matters**
Every one of these appears in the standard solution to some problem you will meet in weeks 2–16. Learning them *now*, isolated, costs one week. Learning them *ambushed mid-problem* costs you the problem, plus the false belief that you're bad at algorithms.

**A note on how to pick solutions.** When two approaches both work, prefer the one with the **smallest new-concept surface** for you right now — even if it's less idiomatic. The hashmap `two_sum` (one loop, one dict, no sorting, no lambda) is both simpler *and* faster than sorted-two-pointer. Reaching for the clever construct you half-know is how interviews get lost. Idiom is a Week-10 concern; correctness under pressure is a Week-1 concern.

**Deliverable**
A scratch notebook — `Python_00_Fluency.ipynb` — with a worked one-liner for each bullet above. Not copied: typed by hand, run, output eyeballed. Then re-solve `two_sum` from the blank stub in `DSA_01`, both ways (hashmap and sorted-two-pointer), and get both passing.

**Topics to ask about** *(paste any into chat and I'll explain)*
- "When does tuple unpacking fail, and what's the exact error?"
- "`sorted()` vs `.sort()` — what's the actual difference and when does it matter?"
- "Explain `key=` without lambda first, then with it"
- "`Counter` vs `defaultdict(int)` vs a plain dict — when is each right?"
- "What is a generator and why does it matter for a 40GB file?"
- "`heapq` — how do I get top-K without sorting everything?"

---

## Phase 1 (Weeks 2–4) — Arrays, Strings, Binary Search

**What you'll learn**
- **Scanning:** single pass, running state, tracking max/min/count as you go
- **Two pointers:** converging (from both ends), same-direction (fast/slow), partition-in-place
- **In-place mutation:** swapping, the write-pointer idiom, why `O(1)` extra space gets asked for
- **Basic transformations:** reverse, rotate, dedup a sorted array, merge two sorted arrays
- **Binary search:** the exact loop (`while lo <= hi`), the off-by-one traps, `bisect_left`/`bisect_right`
- **Binary search on the answer:** the pattern where the array isn't what you search — you binary-search a candidate *value* and test feasibility
- **String parsing:** splitting log lines, tokenizing, character classification, building results with `join` not `+=`

**Why it matters**
This is the substrate everything else sits on. Also the most DE-adjacent family on the list — "parse these log lines and extract X" is a real DE screen question, not a toy. Binary search specifically has the highest ratio of *asked* to *practiced*: candidates skip it because it looks easy, then fail on the boundary conditions.

**Deliverable**
- `DSA_01_Arrays_Strings.ipynb` — **already built, 10 questions.** Solve all 10 cold. Anything you can't do in 20 minutes gets re-attempted in 3 days.
- `DSA_02_Binary_Search.ipynb` — 8 questions: classic search, first/last occurrence, search in rotated array, find peak, sqrt via binary search, binary-search-on-answer (e.g. minimum capacity to ship in D days), `bisect` usage, search a 2D matrix.

**Topics to ask about**
- "Write the binary search loop and explain every boundary choice"
- "When do I use `lo <= hi` vs `lo < hi`?"
- "What is binary search on the answer? Give me 3 examples"
- "Two-pointer converging vs fast/slow — how do I recognize which one a problem wants?"
- "Why is building a string with `+=` in a loop bad, and what do I do instead?"
- "How do I do this in O(1) extra space?"

---

## Phase 2 (Weeks 4–6) — Hashmaps & Sets

**What you'll learn**
- **Frequency counting:** `Counter`, manual dict counting, comparing two frequency maps
- **Membership testing:** set vs list lookup and why one is O(1) and the other O(n)
- **Deduplication:** preserving order vs not, dedup by a derived key
- **Grouping by key:** `defaultdict(list)`, choosing a canonical key (sorted string, tuple of counts, normalized form)
- **Complement pattern:** "have I already seen the thing that completes this?" — the `two_sum` insight, generalized
- **Prefix-state hashing:** storing a running value in a map to answer range questions in one pass
- **Hash collisions and when dicts degrade** — enough to answer "what's the worst case for a dict lookup?"

**Why it matters**
The source material calls this out explicitly: **DE interviews love these patterns.** That's not accidental — dedup, grouping, frequency counting, and join-by-key *are* the daily work of data engineering, and interviewers know a DE candidate should be fluent here specifically. Expect this family to be over-represented relative to a generic SWE loop.

**Deliverable**
`DSA_03_Hashmaps_Sets.ipynb` — 10 questions: top-K frequent elements, group anagrams (revisit from DSA_01 with a different key strategy), first unique character, intersection of two arrays, contains-duplicate-within-K, subarray sum equals K (prefix-state hashing), longest consecutive sequence, isomorphic strings, valid Sudoku (set-based validation), and one log-dedup problem.

**Topics to ask about**
- "Why is set lookup O(1) and list lookup O(n)?"
- "How do I choose a canonical key for grouping?"
- "Explain the prefix-sum-in-a-hashmap pattern with a hand trace"
- "When is a dict lookup NOT O(1)?"
- "How would I dedup 10M log lines that don't fit in memory?" *(bridges to Phase 5)*

---

## Phase 3 (Weeks 6–8) — Stacks & Queues

**What you'll learn**
- **Stack:** LIFO, using a plain list, when the "keep a stack of pending things" shape applies
- **Monotonic stack:** the next-greater-element family — the one genuinely non-obvious stack pattern, and the one that gets asked
- **Queue:** FIFO, `deque` for O(1) popleft, why `list.pop(0)` is O(n) and therefore wrong
- **Practical framings:** undo history, task queues, bracket matching, expression evaluation, backspace-string-compare
- **Conceptual fluency:** be able to explain stack vs queue and give a real system where each appears — this gets asked verbally even when it isn't coded

**Why it matters**
Lower frequency than hashmaps in a DE loop, but the conceptual question ("where would you use a queue in a data pipeline?") is common — and the answer connects directly to work you already do: message queues, task scheduling, retry buffers, DAG execution order. That connection is a differentiator when a generic candidate gives a textbook answer and you give a production one.

**Deliverable**
`DSA_04_Stacks_Queues.ipynb` — 8 questions: valid parentheses, min stack, evaluate reverse Polish notation, daily temperatures (monotonic stack), next greater element, implement queue using stacks, sliding-window maximum with a deque, and simplify-path.

**Topics to ask about**
- "What is a monotonic stack and how do I recognize when to use one?"
- "Why is `list.pop(0)` O(n)? What does `deque` do differently?"
- "Where do stacks and queues show up in a real data pipeline?"
- "Walk me through the daily-temperatures problem with a hand trace"

---

## Phase 4 (Weeks 8–11) — Sliding Window & Prefix Sums

**What you'll learn**
- **Fixed-size window:** running aggregate, add-one/remove-one as the window slides
- **Variable-size window:** expand right until invalid, contract left until valid again — the two-phase loop
- **Window state:** maintaining a Counter/set inside the window and updating it incrementally rather than recomputing
- **Recognizing the shape:** "longest/shortest/count of subarrays or substrings satisfying X" is almost always a window
- **Prefix sums:** build once, answer any range query in O(1)
- **Prefix sums + hashmap:** count subarrays summing to K, handling negatives
- **2D prefix sums:** enough to recognize the pattern

**Why it matters**
**The Google OA's DSA question was a sliding-window problem.** Not a hypothetical — that's from the actual loop teardown. This phase and Phase 2 together cover the majority of what a data-role OA throws at you, because both patterns are about efficient single-pass aggregation, which is what data engineers are assumed to think in.

**Deliverable**
`DSA_05_Window_Prefix.ipynb` — 10 questions: max sum subarray of size K, longest substring without repeating characters (revisit from DSA_01, now with the pattern named), longest substring with at most K distinct chars, minimum window substring (the hard one — attempt it, don't skip it), permutation in string, fruit into baskets, subarray sum equals K, range sum query, product of array except self (revisit as a prefix/suffix problem), and count-subarrays-with-sum-divisible-by-K.

**Topics to ask about**
- "Give me the variable-size sliding-window template and explain each line"
- "How do I know if a problem is a sliding window vs two pointers vs prefix sum?"
- "Hand-trace minimum window substring"
- "Why do prefix sums break with negative numbers in some problems but not others?"
- "How do I maintain window state without recomputing it every step?"

---

## Phase 5 (Weeks 11–16) — DE-Flavored Python (the differentiator)

**This phase is why a DE candidate beats a generic SWE candidate in a DE loop.** Everything above is table stakes; this is the round where your actual job experience should show.

**What you'll learn**
- **Generators and lazy evaluation:** `yield`, generator pipelines, `itertools` (`islice`, `chain`, `groupby`), processing a file line-by-line so memory stays flat regardless of file size
- **Top-K without sorting:** `heapq.nlargest`, maintaining a bounded min-heap of size K while streaming — O(n log K) with O(K) memory instead of O(n log n) with O(n) memory
- **External sorting / merge:** chunk → sort each chunk → write to disk → k-way merge with `heapq.merge`. The canonical "doesn't fit in memory" answer
- **Streaming aggregation:** counting per key over a stream with a bounded-memory strategy; when you need approximate structures (HyperLogLog, Count-Min Sketch) and how to *name* them even if you don't implement them
- **Log parsing at scale:** robust field extraction, malformed-line handling, encoding issues
- **Schema anomaly detection:** infer expected schema, detect drift, decide policy (reject / quarantine / evolve) — this was literally the Google OA's Python question
- **Mid-stream schema change:** the follow-up. Handle a file where line 5,000,000 has a new column. Versioned parsing, union schema, quarantine lane
- **Chunked processing:** `pandas` `chunksize`, or plain generators — and knowing when *not* to reach for pandas at all
- **File formats:** why line-delimited JSON and CSV stream but a single giant JSON array does not

**Why it matters**
Google's Round 3 was exactly this: *process GBs of a log file to get the top 10 users, streaming — then handle a schema change midway.* The tips flagged in the teardown were **generators** and **external sorting**. This is the most predictable round in the entire loop, and the one where a candidate who has only done LeetCode will visibly flounder.

The senior move in this round is stating the memory bound out loud before you write code: *"I'll keep a heap of size 10 and a dict of user counts — memory is O(unique users), not O(file size). If unique users also doesn't fit, I'd shard by hash of user_id and merge."* That single sentence is the whole round.

**Deliverable**
`DSA_06_DE_Coding.ipynb` — 8 problems, all with a generated multi-hundred-MB test file so the memory constraint is real and not hypothetical:
1. Stream a log file and count events per user (bounded memory)
2. Top-10 users by event count via a bounded heap
3. External sort a file larger than memory, then k-way merge
4. Detect schema anomalies in a JSONL log stream
5. Handle a mid-file schema change without crashing or dropping data
6. Deduplicate a stream by event ID with a memory budget
7. Compute a rolling aggregate over a time-ordered stream
8. Parse malformed lines with a quarantine lane and a summary report

**Topics to ask about**
- "Write the bounded-heap top-K pattern and explain the memory bound"
- "How does external sort actually work, step by step?"
- "What do I say when the unique-key cardinality also doesn't fit in memory?"
- "What is HyperLogLog and when would I name it in an interview?"
- "How do I handle a schema change midway through a file — what are the 3 policy options?"
- "When should I NOT use pandas for this?"
- "Generator pipeline vs reading into a list — show me the memory difference concretely"

---

## Cross-cutting habits (practice these from Week 1, not Week 15)

The blueprint's success factor for coding rounds is **"narrate reasoning, not just syntax."** Three of the five red-flag categories are about communication, not correctness. Build these as habits while you practice, because you cannot bolt them on during a real interview.

**Every single practice problem, do all four:**

1. **Ask clarifying questions first — out loud, before writing anything.** Can the input be empty? Are there duplicates? Is it sorted? Can values be negative? What's the expected size? *Not asking clarifying questions* is a named red flag, and it costs nothing to fix.
2. **State the approach before coding it.** "I'll use a hashmap of value to index, single pass, O(n) time O(n) space." If the interviewer objects, you've lost 15 seconds instead of 15 minutes. This directly counters the *jumping to solutions* red flag.
3. **State complexity unprompted** — time and space, at the end, every time.
4. **Enumerate edge cases out loud** — empty input, single element, all duplicates, all negative, target not present. *Missing edge cases* is a named red flag in two separate categories.

**Practice protocol:**
- Set a 25-minute timer. If unsolved, read the *approach* only (not the code), then implement it yourself.
- Any problem you couldn't solve goes into a re-attempt queue for 3 days later, then 10 days later.
- Once a week, solve one problem **talking out loud the entire time**, recording yourself. Play it back. This is uncomfortable and it is the highest-value 30 minutes in the week.

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| LeetCode — Top Interview 150 | The core problem set. Filter to Medium once Phase 1 is done. |
| NeetCode 150 (roadmap view) | Pattern-grouped ordering — matches this roadmap's phase structure closely |
| Python `collections` docs | `Counter`, `defaultdict`, `deque` — read the whole page once |
| Python `heapq` and `itertools` docs | Phase 5 primitives. `heapq.merge` and `itertools.islice` specifically |
| *Fluent Python* (Ramalho), Ch. 2, 3, 14 | Sequences, dicts, iterables/generators — only these three chapters |
| HackerRank SQL track | For the OA's SQL leg — see [Roadmap_02](Roadmap_02_Advanced_SQL.md) |

**Deliberately excluded:** *Cracking the Coding Interview* (dated, Java-centric), competitive-programming sites (wrong difficulty distribution), and advanced graph/DP theory. Trees, graphs, and DP are **not** in this roadmap — see the scope note below.

---

## What's NOT in scope (deliberately)

**Trees, graphs, and dynamic programming are excluded from these 16 weeks.** This is a real decision with a real trade-off, so here is the reasoning:

- Data-role OAs and coding rounds skew heavily toward arrays, strings, hashmaps, and windows — the patterns in this roadmap. The observed Google DE loop asked a sliding-window question and a streaming-file question. Neither needed a tree.
- Adding trees/graphs/DP properly costs another 8–10 weeks. You have 16 total, and four other roadmaps running in parallel.
- Getting the covered patterns to *cold-solve* fluency beats getting twice the surface area to *recognized-but-shaky*.

**The risk, stated plainly:** if you draw a binary-tree or graph-traversal question, you will be underprepared. That risk is highest at Google (the most generalist bar of the four targets) and lowest at Cisco/Adobe.

**Update 2026-10-05:** a DE-relevant graph layer is now IN scope, scheduled in W11–12 of the re-planned 15-week schedule (see Interview_Playbook.md): BFS/DFS on a grid, topological sort (the DAG/dependency shape; Kahn's), intervals, and basic tree traversal, ~25 problems. Still excluded: DP and anything beyond this layer. Total target is ~85–100 problems at ~4h/week DSA.

---

## LeetCode problem list (added 2026-10-06; NeetCode 150 filtered to this roadmap, ~68 problems)

Do these on LeetCode, timed, in Python. The notebooks (`DSA_01`, Phase 0, Phase 5) cover what LeetCode doesn't. Re-solve each cold at +3 and +10 days. Hard/stretch items in *italics* only if ahead of schedule. Skipped on purpose: DP, tries, backtracking, bit tricks, linked lists beyond the three listed, advanced graphs.

| Weeks | Phase | Problems |
|---|---|---|
| W2–5 | 1–2 arrays, two pointers, binary search, hashmaps (~24) | Two Sum, Contains Duplicate, Valid Anagram, Group Anagrams, Top K Frequent Elements, Product of Array Except Self, Longest Consecutive Sequence, Encode and Decode Strings, Valid Palindrome, Two Sum II, 3Sum, Container With Most Water, Maximum Subarray, Rotate Image, Set Matrix Zeroes, Binary Search, Search a 2D Matrix, Koko Eating Bananas, Search in Rotated Sorted Array, Find Minimum in Rotated Sorted Array, *Trapping Rain Water*, *Valid Sudoku*, *Time Based Key-Value Store* |
| W6–7 | 3 stacks/queues (~7) | Valid Parentheses, Min Stack, Evaluate Reverse Polish Notation, Daily Temperatures, LRU Cache, Merge Two Sorted Lists, *Car Fleet* |
| W9–10 | 4 windows, prefix sums, heaps (~12) | Best Time to Buy and Sell Stock, Longest Substring Without Repeating Characters, Longest Repeating Character Replacement, Permutation in String, Subarray Sum Equals K (not on NC150), Kth Largest Element in a Stream, Last Stone Weight, K Closest Points to Origin, Kth Largest Element in an Array, *Minimum Window Substring*, *Sliding Window Maximum*, *Find Median from Data Stream* |
| W11–12 | graph layer (~25) | Graphs: Number of Islands, Max Area of Island, Rotting Oranges, Walls and Gates, Clone Graph, Course Schedule, Course Schedule II (topological sort), Number of Connected Components, Graph Valid Tree, *Word Ladder*, *Network Delay Time*. Trees: Maximum Depth, Invert Binary Tree, Same Tree, Binary Tree Level Order Traversal, Binary Tree Right Side View, Validate BST, LCA of a BST. Intervals: Merge Intervals, Insert Interval, Meeting Rooms, Meeting Rooms II, Non-overlapping Intervals |

Source: NeetCode 150 as listed in a public GitHub copy; difficulty labels there may be off, so check on neetcode.io/leetcode.com as you go.

---

## Checkpoints (self-assess at each)

- **End of Week 1:** Re-solve `two_sum` from a blank stub, both ways, no reference, under 10 minutes total. If you can't, repeat Phase 0 — do not proceed. This checkpoint exists because of the five-failure incident above; it is the load-bearing gate of the whole roadmap.
- **End of Week 4:** All 10 `DSA_01` questions + all 8 `DSA_02` questions passing cold, 20 min each.
- **End of Week 6:** Explain the complement pattern and the prefix-state-hashing pattern out loud in under 60 seconds each, with an example.
- **End of Week 8:** ~60 problems cumulative. Recognize the correct pattern family for an unseen problem within 2 minutes, 8 times out of 10.
- **End of Week 11:** ~100 problems cumulative. Write the variable-size sliding-window template from memory, correct on the first try.
- **End of Week 16:** ~120–150 problems. Solve one unseen Medium in 25 minutes while narrating, recorded. Solve the "top 10 users from a GB-scale log file" problem end to end, and state the memory bound before writing code.

---

## How to use this file

1. **Do Phase 0 first, in full.** It is one week and it is the difference between 16 productive weeks and 16 frustrating ones. The evidence for this is in the table at the top of this file.
2. Work phases in order — they compound. Phase 4's window state uses Phase 2's hashmaps; Phase 5's top-K uses Phase 3's heap intuition.
3. Pick any **Topic to ask about** that's unfamiliar and paste it into chat.
4. **When you get a bug in your own practice code, expect the 3-line debugging format** — what's Wrong, what to Fix, and the situation where your approach *would* have been right. Not a full mechanism walkthrough. This is the agreed working format for this roadmap.
5. Do the notebooks yourself. Solutions are never pre-filled — the self-check assertion cells give you objective pass/fail, and the artifact of value is your own solved notebook.
6. Don't advance past a checkpoint you haven't passed. Coverage without internalization fails OAs.
