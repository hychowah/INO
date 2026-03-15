# PLAN.md — Solo-First Mobile App Conversion

> **Strategy**: Build a solo mobile app first (you as the only user), then scale to multi-user public release. The architecture is designed so nothing needs rewriting when you go public — only additions.

## Architecture Overview

```
SOLO (Phase 1 — what we build now):
  Phone (React Native) → HTTP → FastAPI (api.py) → pipeline.py → LLM → SQLite
  All on your local machine / home network

PUBLIC (Phase 2 — later):
  Phone → HTTPS → Cloud Run (api.py) → pipeline.py → LLM → PostgreSQL
                      ↑ Firebase Auth          ↑ RevenueCat
                      ↑ FCM Push Notifications
```

The inner pipeline (`pipeline.py → LLM → tools.py → DB`) stays identical in both phases. Only the outer shell changes (transport + auth + DB engine).

---

## Phase 0: Setup & Foundations (3–5 days)

### 0.1 Install Tools
- [ ] Node.js 20+ — https://nodejs.org
- [ ] Expo CLI — `npm install -g expo-cli`
- [ ] Android Studio (for emulator) OR use Expo Go app on your physical phone
- [ ] VS Code extensions: "React Native Tools", "ES7+ React/Redux/React-Native snippets"
- [ ] Python packages: `pip install fastapi uvicorn`

### 0.2 Learn the Basics (with AI assistance)
- [ ] JavaScript/TypeScript crash course (2 hrs) — arrow functions, async/await, destructuring, imports
- [ ] React fundamentals (2 hrs) — components, props, `useState`, `useEffect`
- [ ] REST API concepts (1 hr) — GET/POST, JSON bodies, status codes, headers

> You don't need to master these — just enough to read and debug AI-generated code.

---

## Phase 1: FastAPI Backend (3–5 days)

Replace Discord with an HTTP API. The pipeline is already Discord-free — this is a thin wrapper.

### 1.1 Create `api.py` (new file, ~100 lines)

**Endpoints:**

| Method | Route | What it does | Wraps |
|--------|-------|-------------|-------|
| `POST` | `/api/chat` | Send message, get LLM response | `pipeline.call_with_fetch_loop()` → `execute_llm_response()` → `process_output()` |
| `GET` | `/api/topics` | Topic tree with mastery stats | `db.get_hierarchical_topic_map()` |
| `GET` | `/api/topics/{id}` | Topic detail + concepts | `db.get_topic_detail()` |
| `GET` | `/api/concepts/{id}` | Concept + remarks + reviews | `db.get_concept_detail()` |
| `GET` | `/api/due` | Due review concepts | `db.get_due_concepts()` |
| `GET` | `/api/stats` | Aggregate review stats | `db.get_review_stats()` |

**Core `/api/chat` logic** (replaces `bot.py._handle_user_message()`):
```python
@app.post("/api/chat")
async def chat(req: ChatRequest):
    llm_response = await pipeline.call_with_fetch_loop("command", req.message, "solo_user")
    result = await pipeline.execute_llm_response(req.message, llm_response, "command")
    msg_type, message = process_output(result)
    return {"type": msg_type, "message": message}
```

### 1.2 Add CORS Middleware
One line — required for React Native to talk to the API:
```python
app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

### 1.3 Simple Token Auth (prep for multi-user)
- Add `API_SECRET_KEY` to `config.py`
- App sends `Authorization: Bearer <key>` header
- API validates it (static check for solo; becomes Firebase token check later)

### 1.4 Update `config.py`
- Add `API_HOST = "0.0.0.0"`, `API_PORT = 8080`
- Make `BOT_TOKEN` optional (not needed for API mode)

### 1.5 Update `requirements.txt`
- Add `fastapi>=0.100`, `uvicorn>=0.20`

### 1.6 Skip Background Scheduler (for now)
- No push notifications in solo mode
- `GET /api/due` replaces the scheduler — app checks on launch and shows a "You have N concepts due" badge
- User taps "Review" → app sends "quiz me" to `/api/chat` → existing pipeline handles the rest

### 1.7 Create `start_api.bat`
```batch
uvicorn api:app --host 0.0.0.0 --port 8080 --reload
```

### 1.8 Verification
```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_KEY" \
  -d '{"message": "what is stainless steel?"}'
# Should return: {"type": "reply", "message": "Stainless steel is..."}
```

---

## Phase 2: Prep DB for Multi-User (1 day)

Add `user_id` columns now so you never need to migrate data later.

### 2.1 Add Migration 5 in `db/core.py`
```python
if current < 5:
    for table in ('topics', 'concepts', 'review_log'):
        if not _has_column(conn, table, 'user_id'):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT DEFAULT 'default'")
    # chat_history.db too
```

All existing data gets `user_id='default'` automatically. Solo mode ignores it.

### 2.2 Add `user_id` Parameter to Pipeline (signature only)
```python
# services/pipeline.py
async def call_with_fetch_loop(mode: str, text: str, author: str, user_id: str = "default") -> str:
```
Don't thread it through yet — just make the signature ready.

### 2.3 Verification
- Existing tests in `tests/` should still pass (data unchanged, columns only added)
- WebUI should still work (reads same DB, new column is ignored)

---

## Phase 3: React Native (Expo) App (2–3 weeks)

### 3.1 Initialize
```bash
npx create-expo-app learning-coach --template blank-typescript
cd learning-coach
npx expo install @react-navigation/native @react-navigation/bottom-tabs
npx expo install react-native-markdown-display
npx expo install @react-native-async-storage/async-storage
npm install axios
```

### 3.2 Project Structure
```
learning-coach/
├── app/
│   ├── screens/
│   │   ├── ChatScreen.tsx          ← Primary screen (replaces Discord)
│   │   ├── TopicsScreen.tsx        ← Topic tree browser
│   │   ├── ReviewScreen.tsx        ← Due concepts + start review
│   │   └── SettingsScreen.tsx      ← API URL config, preferences
│   ├── components/
│   │   ├── MessageBubble.tsx       ← Chat message (markdown rendered)
│   │   ├── QuizCard.tsx            ← Highlighted quiz question card
│   │   ├── TopicSuggestCard.tsx    ← Accept/decline topic suggestion
│   │   └── TopicTree.tsx           ← Collapsible topic hierarchy
│   ├── services/
│   │   └── api.ts                  ← All HTTP calls to backend
│   ├── navigation/
│   │   └── TabNavigator.tsx        ← Bottom tabs: Chat, Topics, Review, Settings
│   └── config.ts                   ← API base URL, stored API key
├── App.tsx                         ← Entry point, navigation container
└── package.json
```

### 3.3 Build Order

#### Week 1 — Chat Screen (the core experience)

1. **`services/api.ts`** — HTTP client:
   ```typescript
   export const sendMessage = (text: string) =>
     axios.post(`${API_URL}/api/chat`, { message: text }, { headers: authHeaders });
   export const getDue = () => axios.get(`${API_URL}/api/due`, { headers: authHeaders });
   export const getTopics = () => axios.get(`${API_URL}/api/topics`, { headers: authHeaders });
   ```

2. **`ChatScreen.tsx`** — FlatList of messages + text input + send button:
   - Messages stored in React state (`useState<Message[]>([])`)
   - On send: push user message to state → call `sendMessage()` → push response to state
   - Detect `type: "quiz"` → render `QuizCard` instead of plain bubble
   - Detect `type: "suggest"` → render `TopicSuggestCard` with Accept/Decline

3. **`MessageBubble.tsx`** — renders markdown from LLM (tables, bold, code blocks, etc.)

4. **`QuizCard.tsx`** — emphasized card with question text + visual flair (🧠 emoji, colored border)

5. **`TopicSuggestCard.tsx`** — "Want to track X?" with two buttons. Accept → sends "yes" to `/api/chat`

6. **TEST**: Type a question → get answer → accept topic → quiz → answer → see feedback. This replicates 90% of the Discord experience.

#### Week 2 — Topics & Review Screens

7. **`TopicsScreen.tsx`** — fetch `/api/topics`, display as expandable tree with mastery progress bars. Tap topic → fetch `/api/topics/:id` → show concepts.

8. **`ReviewScreen.tsx`** — fetch `/api/due`, show count + list. "Start Review" button navigates to ChatScreen with pre-filled "quiz me" message.

9. **`TabNavigator.tsx`** — bottom tab bar: 💬 Chat | 📚 Topics | 🧠 Review | ⚙️ Settings

10. **Review badge**: Topics tab shows mastery %, Review tab shows due count badge.

#### Week 3 — Polish

11. **`SettingsScreen.tsx`** — configure API URL (for later cloud deployment), view stats, preferences.

12. **Persist chat locally** — `AsyncStorage` so messages survive app restart.

13. **Error handling** — network errors, LLM timeout, loading spinners.

14. **Keyboard handling** — `KeyboardAvoidingView` so the input stays visible when typing.

15. **Pull-to-refresh** on Topics and Review screens.

### 3.4 Key Libraries (minimal)

| Package | Purpose |
|---------|---------|
| `@react-navigation/native` | Screen navigation |
| `@react-navigation/bottom-tabs` | Bottom tab bar |
| `react-native-markdown-display` | Render LLM markdown |
| `@react-native-async-storage/async-storage` | Local persistence |
| `axios` | HTTP client |

### 3.5 Verification
- On phone via Expo Go (same WiFi as PC): send message, see response, complete quiz cycle
- Full flow: casual question → topic suggestion → accept → quiz → assess → check topics screen → review screen shows due count

---

## Phase 4: End-to-End Testing (2–3 days)

### 4.1 Running Everything
```bash
# Terminal 1: Backend
cd learning_agent
uvicorn api:app --host 0.0.0.0 --port 8080 --reload

# Terminal 2: Mobile app
cd learning-coach
npx expo start
# Scan QR with Expo Go app on phone (same WiFi)

# Terminal 3 (optional): WebUI for DB browsing
python -m webui.server
```

### 4.2 Test Scenarios
- [ ] Ask a casual question → get thorough answer
- [ ] Answer triggers topic suggestion → accept it → topic created
- [ ] Ask "quiz me on [topic]" → get quiz question → answer it → get assessment
- [ ] Check Topics screen → see topic tree with mastery levels
- [ ] Check Review screen → see due concepts count
- [ ] Tap "Start Review" → lands in chat with quiz flow
- [ ] Kill app → reopen → chat history persisted
- [ ] Disconnect WiFi → app shows meaningful error

---

## Phase 2 (Public Launch) — What Gets Added Later

None of these require rewriting solo-mode code. They're additions only.

| Addition | What changes | Effort |
|----------|-------------|--------|
| **Firebase Auth** | `api.py` middleware: static key check → Firebase token verification | ~20 lines |
| **Multi-user DB** | Add `WHERE user_id = ?` to queries in `db/` modules | Mechanical, ~2 days |
| **PostgreSQL** | Swap `sqlite3` → `asyncpg` in `db/core.py` | SQL 95% identical, ~2 days |
| **Push notifications** | Add FCM in `api.py` + notification handler in app | New code, ~3 days |
| **Subscriptions** | RevenueCat SDK in app + webhook in `api.py` | New code, ~1 week |
| **Cloud deployment** | Dockerize `api.py` → deploy to Google Cloud Run | Config only, ~1 day |
| **App store submission** | EAS Build + submit to Apple/Google | ~1 week (Apple review) |

### Public launch tech stack:
- **Auth**: Firebase Authentication (Email + Google + Apple sign-in)
- **Database**: Cloud SQL (PostgreSQL 15)
- **Hosting**: Google Cloud Run (serverless, auto-scales to zero)
- **Push**: Firebase Cloud Messaging (FCM)
- **Payments**: RevenueCat (handles both App Store + Play Store)
- **App builds**: Expo Application Services (EAS)
- **Monitoring**: Cloud Logging + Firebase Crashlytics

### Cost estimates (public, ~500 users):
- Cloud Run: ~$10–30/mo
- Cloud SQL: ~$10–30/mo  
- Firebase Auth: free (up to 10K users)
- LLM API: ~$0.02/interaction × usage (biggest variable cost)
- Apple Developer: $99/year
- Google Play: $25 one-time
- RevenueCat: free up to $2.5K revenue

---

## Files Modified (Solo Phase Summary)

| File | Change | Status |
|------|--------|--------|
| `api.py` | **NEW** — FastAPI server (~100 lines) | Create |
| `start_api.bat` | **NEW** — API startup script | Create |
| `config.py` | Add `API_HOST`, `API_PORT`, `API_SECRET_KEY`; make `BOT_TOKEN` optional | Edit |
| `requirements.txt` | Add `fastapi>=0.100`, `uvicorn>=0.20` | Edit |
| `db/core.py` | Migration 5: add `user_id` columns | Edit |
| `services/pipeline.py` | Add `user_id` param to `call_with_fetch_loop()` | Edit |
| `learning-coach/` | **NEW** — entire React Native app | Create (separate project) |

**Untouched**: `AGENTS.md`, `tools.py`, `context.py`, `services/parser.py`, `services/llm.py`, `services/repair.py`, `services/dedup.py`, `db/concepts.py`, `db/topics.py`, `db/reviews.py`, `db/chat.py`, `webui/` — all work as-is.

---

## Key Architectural Decisions

1. **Keep SQLite for solo** — no PostgreSQL until multi-user. SQLite + WAL handles one user perfectly.
2. **FastAPI over extending `webui/server.py`** — WebUI uses `http.server` with no async, no CORS, no middleware. FastAPI gives async + auto-docs + validation for 2 extra packages.
3. **Skip background scheduler for v1** — `GET /api/due` on app open replaces push notifications. Simpler, sufficient for solo.
4. **Static API key over no auth** — same `Authorization` header pattern upgrades to Firebase tokens later.
5. **`user_id` columns now, queries later** — 10 minutes of migration now saves painful data migration when going public.
6. **Separate React Native project** — `learning-coach/` lives alongside `learning_agent/`, not inside it. Clean separation of frontend and backend.
7. **Keep WebUI running** — useful for DB browsing during development. Both servers coexist on different ports.
