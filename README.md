# 🧠 Aether Cognitive Second Brain Agent

> A zero-dependency, persistent relational graph memory and autonomous ReAct reasoning agent served locally inside a gorgeous, modern dark-mode dashboard.

---

Aether is a personal cognitive companion designed to combat digital information fragmentation and cognitive overload. It acts as a centralized "Second Brain" that continuously captures notes, tasks, habits, and decisions, maps them into a relational **Knowledge Graph**, and retrieves them through step-by-step natural language reasoning loops.

![Holographic Graph Core](ai_core_art.png)

---

## 🚀 Key Capabilities

1. **Persistent SQLite Knowledge Graph**
   * Persists all thoughts, tasks, and structures inside a local `second_brain.db` database.
   * Links nodes semantically (e.g. connecting Gmail notes to active Notion wikis and goals) to map complex contextual ideas.
2. **Autonomous ReAct Agent Loop**
   * Uses the **Reasoning and Acting (ReAct)** paradigm to answer queries.
   * Step-by-step streams thoughts (Thought 💭), executes local database and calculation tools (Action 🛠️), analyzes real database outputs (Observation 👁️), and outputs responses.
3. **Multi-API Platform Sync Simulators**
   * Simulates active sync integrations with **Gmail**, **Google Calendar**, **Notion**, and **Cloud Files**, instantly parsing mock schedules and documents into memory.
4. **Structured Decisions Ledger**
   * Structured form to log problem statements, options comparisons, weighted Pros/Cons, finalized choices, and reflections to combat decision fatigue.
5. **Productivity Metrics command**
   * **timeline Goals**: Interactive completion percentage trackers.
   * **Habits Streaks**: Increment active daily practices with calendar streak triggers.
6. **Proactive Diagnostics & Predictions**
   * background engine that scans database density and generates contextual warning alerts (e.g., reminding you to set goals for active projects).

---

## 🛡️ Secure Coding Guarantees

Built strictly in compliance with the **Principle of Least Privilege** and enterprise security guidelines:

* **0% Unsafe DOM Rendering (XSS Immunity)**: Absolutely no usage of `innerHTML` or `outerHTML`. Every dynamic component on the frontend is created through explicit `document.createElement` nodes, cleared using `replaceChildren()`, and text-encoded using `textContent`.
* **SQL Injection Proof**: Every database query uses parameterized statements (`?`) to guarantee absolute memory safety.
* **127.0.0.1 Confinement Sandbox**: The zero-dependency server binds strictly to the local loopback address `127.0.0.1:8000` (blocking `0.0.0.0`) to keep your data completely private.
* **Temporary Session Key Storage**: API secret keys are stored strictly in client-side `sessionStorage`. They exist only during the active browser tab session and are never logged or saved to your disk.
* **Overridden SSL context**: Bypasses classic macOS certificate issues natively, preventing connection failures during external model requests.

---

## ⚙️ Quick Start

### Prerequisites
Aether is engineered to run on **pure Python 3** with **zero external dependencies**. No `npm`, `pip`, or complex frameworks required.

### Launching the Dashboard
1. Clone or copy this directory to your machine.
2. Open your terminal in the directory and launch the web playground:
   ```bash
   python3 agent.py --web
   ```
3. Your browser will automatically open the dashboard served securely at:
   **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### Reasoning Engines Supported
* **🧪 Simulation Mode**: Works out-of-the-box with no keys using seeded mock datasets.
* **⚡ Groq Developer API**: Blazing-fast inference using Llama 3.1 (`llama-3.1-8b-instant`).
* **✨ Gemini Developer API**: Generous free-tier integration using Gemini 2.5 Flash.
* **🤖 OpenAI API**: Advanced reasoning using GPT-4o-mini.
