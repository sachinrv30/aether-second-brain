#!/usr/bin/env python3
"""
Digital Second Brain Agent Backend
A zero-dependency local API server and autonomous ReAct agent loop with SQLite persistence.
Serves a highly interactive, premium web dashboard.
"""

import os
import sys
import re
import ast
import math
import time
import datetime
import urllib.request
import urllib.error
import json
import operator
import threading
import http.server
import socketserver
import webbrowser
import argparse
import sqlite3
import ssl
from typing import Dict, Any, Callable, Tuple, List, Optional

# Override default HTTPS context to resolve macOS missing root certificate issues
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# ==============================================================================
# Database Schema and Setup
# ==============================================================================
def get_db_connection():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "second_brain.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Memories Table (Notes, Ideas, Decisions, Conversations)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        type TEXT NOT NULL, -- 'note', 'task', 'decision', 'conversation'
        category TEXT NOT NULL, -- 'personal', 'work', 'study', 'finance'
        tags TEXT, -- comma-separated tags
        created_at TEXT NOT NULL,
        metadata TEXT -- JSON string for rich fields (e.g. email sender, pros/cons)
    )
    """)
    
    # 2. Connections Table (Knowledge Graph Links)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        relation_type TEXT NOT NULL, -- 'relates_to', 'blocks', 'created_by', 'decision_for'
        created_at TEXT NOT NULL,
        FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
        FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE,
        UNIQUE(source_id, target_id, relation_type)
    )
    """)
    
    # 3. Goals Table (Productivity Goals)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0, -- 0 to 100
        deadline TEXT,
        status TEXT NOT NULL DEFAULT 'active', -- 'active', 'completed', 'abandoned'
        created_at TEXT NOT NULL
    )
    """)
    
    # 4. Habits Table (Habit streak tracker)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        streak INTEGER NOT NULL DEFAULT 0,
        last_completed TEXT, -- Date string YYYY-MM-DD
        created_at TEXT NOT NULL
    )
    """)
    
    # 5. Integrations Table (External Service Status)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS integrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT UNIQUE NOT NULL, -- 'gmail', 'calendar', 'notion', 'cloud_storage'
        connected INTEGER NOT NULL DEFAULT 0, -- 0 or 1
        last_synced_at TEXT
    )
    """)
    
    # Seed default integrations if not present
    for service in ['gmail', 'calendar', 'notion', 'cloud_storage']:
        cursor.execute("INSERT OR IGNORE INTO integrations (service_name, connected, last_synced_at) VALUES (?, 0, NULL)", (service,))
        
    # Seed initial sample data to make dashboard immediately engaging if empty
    cursor.execute("SELECT COUNT(*) as count FROM memories")
    if cursor.fetchone()['count'] == 0:
        now = datetime.datetime.now().isoformat()
        today = datetime.date.today().isoformat()
        
        # Add basic memories
        cursor.execute("""
        INSERT INTO memories (content, type, category, tags, created_at, metadata) 
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "Idea: Solar-powered eco-friendly bluetooth headphones prototype. Build with bio-degradable casing.",
            "note", "personal", "idea,sustainability,audio", now, "{}"
        ))
        headphone_id = cursor.lastrowid
        
        cursor.execute("""
        INSERT INTO memories (content, type, category, tags, created_at, metadata) 
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "Research and compile market analysis details for wearable clean energy technologies.",
            "task", "work", "research,market,sustainability", now, "{}"
        ))
        research_id = cursor.lastrowid
        
        # Link them
        cursor.execute("""
        INSERT INTO connections (source_id, target_id, relation_type, created_at) 
        VALUES (?, ?, ?, ?)
        """, (headphone_id, research_id, "relates_to", now))
        
        # Add goals and habits
        cursor.execute("INSERT INTO goals (title, progress, deadline, status, created_at) VALUES (?, ?, ?, ?, ?)",
                       ("Complete Wearable Tech Prototypes", 35, "2026-06-15", "active", now))
        cursor.execute("INSERT INTO habits (name, streak, last_completed, created_at) VALUES (?, ?, ?, ?)",
                       ("Daily Coding Practice", 4, today, now))
        cursor.execute("INSERT INTO habits (name, streak, last_completed, created_at) VALUES (?, ?, ?, ?)",
                       ("Evening Review and Reflection", 1, today, now))
        
    conn.commit()
    conn.close()

# ==============================================================================
# Safe AST-Based Mathematical Calculator
# ==============================================================================
class SafeEvalError(Exception):
    pass

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}

SAFE_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

def safe_eval(node) -> float:
    if isinstance(node, ast.Num):  # Python < 3.8 fallback
        return node.n
    elif isinstance(node, ast.Constant):  # Python >= 3.8
        if isinstance(node.value, (int, float)):
            return node.value
        raise SafeEvalError(f"Unsupported constant type: {type(node.value).__name__}")
    elif isinstance(node, ast.BinOp):
        left = safe_eval(node.left)
        right = safe_eval(node.right)
        op_type = type(node.op)
        if op_type in SAFE_OPERATORS:
            if op_type == ast.Pow:
                if left > 10000 or right > 100:
                    raise SafeEvalError("Operation values too large (preventing overflow)")
            try:
                return SAFE_OPERATORS[op_type](left, right)
            except ZeroDivisionError:
                raise SafeEvalError("Division by zero is undefined")
            except Exception as e:
                raise SafeEvalError(f"Error evaluating operator {op_type.__name__}: {str(e)}")
        raise SafeEvalError(f"Unsupported binary operator: {op_type.__name__}")
    elif isinstance(node, ast.UnaryOp):
        operand = safe_eval(node.operand)
        op_type = type(node.op)
        if op_type in SAFE_UNARY_OPERATORS:
            return SAFE_UNARY_OPERATORS[op_type](operand)
        raise SafeEvalError(f"Unsupported unary operator: {op_type.__name__}")
    
    raise SafeEvalError(f"Unsupported mathematical syntax: {type(node).__name__}")

def calculate(expression: str) -> str:
    try:
        clean_expr = expression.strip()
        if not clean_expr:
            return "Error: Expression is empty"
        parsed = ast.parse(clean_expr, mode='eval')
        result = safe_eval(parsed.body)
        return str(result)
    except SafeEvalError as se:
        return f"Error: {str(se)}"
    except SyntaxError:
        return "Error: Invalid syntax in mathematical expression"
    except Exception as e:
        return f"Error: Failed to evaluate expression: {str(e)}"

# ==============================================================================
# Second Brain Mock Sync Data
# ==============================================================================
MOCK_SYNC_DATA = {
    "gmail": [
        {
            "content": "Subject: Project Branding Review - Let's schedule the project branding decision by Friday afternoon. We need to decide on colors and typography assets.",
            "type": "conversation", "category": "work", "tags": "email,branding,decision",
            "metadata": {"sender": "sarah.design@company.com", "channel": "Gmail Sync"}
        },
        {
            "content": "Subject: Syllabus Machine Learning - Dear Sachin, here is the syllabus for the Advanced Machine Learning course you asked for. In particular, we will cover deep neural networks next week.",
            "type": "note", "category": "study", "tags": "email,ml,learning",
            "metadata": {"sender": "professor.adams@university.edu", "channel": "Gmail Sync"}
        },
        {
            "content": "Subject: Flight Confirmation TX892 - Confirmation details for your upcoming vacation to Tokyo on July 10th. Departure: 10:45 AM from SFO.",
            "type": "note", "category": "personal", "tags": "email,travel,tokyo",
            "metadata": {"sender": "reservations@airline.com", "channel": "Gmail Sync"}
        }
    ],
    "calendar": [
        {
            "content": "Calendar Event: Weekly Team Status Sync. Friday, May 29th at 10:00 AM. Agenda: review milestones and resolve project bottlenecks.",
            "type": "note", "category": "work", "tags": "calendar,meeting",
            "metadata": {"organizer": "manager.mark@company.com", "channel": "Google Calendar Sync"}
        },
        {
            "content": "Calendar Event: Dentist appointment checkup. June 2nd at 3:00 PM. Address: 450 Health Ave Suite 12.",
            "type": "note", "category": "personal", "tags": "calendar,health,dentist",
            "metadata": {"organizer": "reception@dentistry.com", "channel": "Google Calendar Sync"}
        }
    ],
    "notion": [
        {
            "content": "Notion Page: Solar-powered bluetooth headphones with integrated eco-friendly charging case. Target retail price: $149. Battery target: 45 hours.",
            "type": "note", "category": "personal", "tags": "notion,idea,sustainability",
            "metadata": {"workspace": "Personal Projects", "channel": "Notion Sync"}
        },
        {
            "content": "Notion Page: Neural Network Architectures summary. Feedforward networks pass info in one direction. Backpropagation computes gradients using chain rule.",
            "type": "note", "category": "study", "tags": "notion,notes,ml",
            "metadata": {"workspace": "Academic Studies", "channel": "Notion Sync"}
        }
    ],
    "cloud_storage": [
        {
            "content": "Document: Career Milestones & Reflections 2026. Transition to Senior AI Engineer. Lead production rollout of intelligent workflows, mentor 2 juniors.",
            "type": "note", "category": "work", "tags": "cloud,career,reflections",
            "metadata": {"filename": "Career_Reflections_2026.txt", "channel": "Cloud Storage Sync"}
        },
        {
            "content": "Document: Personal Financial Plan 2026. Target allocation: 40% index funds, 20% emergency savings, 30% household expenses, 10% self-education budget.",
            "type": "note", "category": "finance", "tags": "cloud,finance,budget",
            "metadata": {"filename": "Personal_Finance_2026.txt", "channel": "Cloud Storage Sync"}
        }
    ]
}

# ==============================================================================
# ReAct Cognitive Tools Implementation
# ==============================================================================
class SecondBrainTools:
    @staticmethod
    def search_brain(query: str) -> str:
        """Search the SQLite memory vault by keyword. Use: search_brain('branding')"""
        clean_query = query.strip().lower().strip("'\"")
        if not clean_query:
            return "Error: Search query is empty."
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Direct SQL search with parameterized query to prevent SQLi
        search_pattern = f"%{clean_query}%"
        cursor.execute("""
            SELECT id, content, type, category, tags, created_at 
            FROM memories 
            WHERE lower(content) LIKE ? OR lower(tags) LIKE ? OR lower(category) LIKE ?
            ORDER BY created_at DESC
        """, (search_pattern, search_pattern, search_pattern))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return f"No memories found matching keyword '{clean_query}'."
            
        result = [f"Found {len(rows)} memories matching '{clean_query}':"]
        for row in rows:
            result.append(f" - [ID {row['id']}] [{row['type'].upper()}] ({row['category']}) tags:[{row['tags']}]: {row['content']}")
        return "\n".join(result)

    @staticmethod
    def add_memory(params_json: str) -> str:
        """Add a new memory node to the vault. Provide details in JSON string format:
        add_memory('{"content": "Draft paper summary", "type": "note", "category": "work", "tags": "research,draft"}')
        """
        try:
            data = json.loads(params_json)
            content = data.get("content", "").strip()
            mem_type = data.get("type", "note").strip().lower()
            category = data.get("category", "personal").strip().lower()
            tags = data.get("tags", "").strip()
            
            if not content:
                return "Error: Memory content cannot be empty."
                
            now = datetime.datetime.now().isoformat()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO memories (content, type, category, tags, created_at, metadata) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (content, mem_type, category, tags, now, "{}"))
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return f"Success: Memory successfully captured and saved under ID {new_id}!"
        except Exception as e:
            return f"Error: Failed to add memory. Check JSON parameter format. Detail: {str(e)}"

    @staticmethod
    def link_memories(params_json: str) -> str:
        """Create a semantic link in the knowledge graph between two memory nodes. Use:
        link_memories('{"source_id": 1, "target_id": 2, "relation": "relates_to"}')
        """
        try:
            data = json.loads(params_json)
            source_id = int(data.get("source_id"))
            target_id = int(data.get("target_id"))
            relation = data.get("relation", "relates_to").strip().lower()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Verify source and target exist
            cursor.execute("SELECT id FROM memories WHERE id = ?", (source_id,))
            if not cursor.fetchone():
                conn.close()
                return f"Error: Source memory ID {source_id} does not exist."
                
            cursor.execute("SELECT id FROM memories WHERE id = ?", (target_id,))
            if not cursor.fetchone():
                conn.close()
                return f"Error: Target memory ID {target_id} does not exist."
                
            now = datetime.datetime.now().isoformat()
            cursor.execute("""
                INSERT OR IGNORE INTO connections (source_id, target_id, relation_type, created_at)
                VALUES (?, ?, ?, ?)
            """, (source_id, target_id, relation, now))
            
            conn.commit()
            conn.close()
            return f"Success: Created semantic link: Memory {source_id} --({relation})--> Memory {target_id}."
        except Exception as e:
            return f"Error: Failed to create connection. Detail: {str(e)}"

    @staticmethod
    def get_goals_habits(arg: str = "") -> str:
        """Retrieve current goals, tasks, and habits to track active streaks. Use: get_goals_habits('')"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, title, progress, deadline, status FROM goals")
        goals = cursor.fetchall()
        
        cursor.execute("SELECT id, name, streak, last_completed FROM habits")
        habits = cursor.fetchall()
        
        conn.close()
        
        result = ["Productivity Tracker Status:"]
        
        result.append("\nGoals:")
        if not goals:
            result.append(" - No active goals established.")
        for g in goals:
            result.append(f" - [ID {g['id']}] '{g['title']}' | Progress: {g['progress']}% | Deadline: {g['deadline']} | Status: {g['status'].upper()}")
            
        result.append("\nHabits:")
        if not habits:
            result.append(" - No habits established.")
        for h in habits:
            result.append(f" - [ID {h['id']}] '{h['name']}' | Streak: {h['streak']} days | Last Done: {h['last_completed']}")
            
        return "\n".join(result)

    @staticmethod
    def sync_external_data(service_name: str) -> str:
        """Simulate syncing sample datasets from external productivity platforms. Use: sync_external_data('gmail')"""
        service = service_name.strip().lower().strip("'\"")
        if service not in MOCK_SYNC_DATA:
            return f"Error: Unknown integration '{service}'. Supported: {list(MOCK_SYNC_DATA.keys())}"
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        records = MOCK_SYNC_DATA[service]
        now = datetime.datetime.now().isoformat()
        added_count = 0
        
        for rec in records:
            # Check if this content is already present to prevent duplicate syncing
            cursor.execute("SELECT id FROM memories WHERE content = ?", (rec["content"],))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO memories (content, type, category, tags, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (rec["content"], rec["type"], rec["category"], rec["tags"], now, json.dumps(rec["metadata"])))
                added_count += 1
                
        cursor.execute("""
            UPDATE integrations 
            SET connected = 1, last_synced_at = ? 
            WHERE service_name = ?
        """, (now, service))
        
        # Proactively link items of related topics to demonstrate knowledge graphs
        if service == "gmail" or service == "notion":
            cursor.execute("SELECT id, content FROM memories WHERE tags LIKE '%ml%' OR tags LIKE '%learning%'")
            ml_rows = cursor.fetchall()
            if len(ml_rows) >= 2:
                # Link first two ML nodes semantically
                cursor.execute("""
                    INSERT OR IGNORE INTO connections (source_id, target_id, relation_type, created_at)
                    VALUES (?, ?, ?, ?)
                """, (ml_rows[0]['id'], ml_rows[1]['id'], "relates_to", now))
                
        conn.commit()
        conn.close()
        
        return f"Integration Ingestor Complete: Sync status updated for '{service}'. Ingested {added_count} new memory cards into the SQLite Second Brain Database."

    @staticmethod
    def get_proactive_insights(arg: str = "") -> str:
        """Generates proactive cognitive insights, scanning the knowledge graph and predicting user contexts. Use: get_proactive_insights('')"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM memories")
        total_memories = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM connections")
        total_links = cursor.fetchone()['count']
        
        cursor.execute("SELECT title, deadline FROM goals WHERE progress < 100 AND status = 'active' ORDER BY deadline ASC LIMIT 2")
        upcoming_goals = cursor.fetchall()
        
        cursor.execute("SELECT name, streak FROM habits ORDER BY streak DESC LIMIT 1")
        top_habit = cursor.fetchone()
        
        # Custom logic searches for specific keywords to generate proactive warnings
        cursor.execute("SELECT id, content FROM memories WHERE lower(content) LIKE '%branding%' OR lower(content) LIKE '%decision%'")
        branding_decisions = cursor.fetchall()
        
        conn.close()
        
        insights = [
            f"🧠 AETHER SECOND BRAIN COGNITIVE DIAGNOSTIC:",
            f" - Memory Vault Density: {total_memories} nodes indexed.",
            f" - Semantic Graph Connections: {total_links} active relational links.",
        ]
        
        if top_habit:
            insights.append(f" - Top Performing Habit: '{top_habit['name']}' is on a {top_habit['streak']}-day active streak! Keep it up.")
            
        if upcoming_goals:
            insights.append(" - Urgent Goals Timeline:")
            for g in upcoming_goals:
                insights.append(f"    * Goal: '{g['title']}' | Deadline Target: {g['deadline']}.")
                
        # Proactive contextual warning prediction
        if branding_decisions:
            insights.append("\n⚠️ PROACTIVE WARNING PREDICTION:")
            insights.append(" - Context: We detected active notes regarding a 'branding decision' scheduled for Friday.")
            insights.append(" - Actionable Suggestion: You have not defined a structured Goal for 'Branding Selection' yet. Would you like me to formulate one and schedule an AST decision log session?")
            
        return "\n".join(insights)

# ==============================================================================
# ReAct Reasoning Agent Engine
# ==============================================================================
class ReActAgent:
    def __init__(self):
        self.tools = {
            "search_brain": SecondBrainTools.search_brain,
            "add_memory": SecondBrainTools.add_memory,
            "link_memories": SecondBrainTools.link_memories,
            "get_goals_habits": SecondBrainTools.get_goals_habits,
            "sync_external_data": SecondBrainTools.sync_external_data,
            "get_proactive_insights": SecondBrainTools.get_proactive_insights,
            "calculate": calculate
        }
        
    def get_system_prompt(self) -> str:
        tool_descriptions = "\n".join([f"- {name}: {func.__doc__}" for name, func in self.tools.items()])
        return f"""You are an autonomous Aether "Digital Second Brain" agent assisting human memory and decision support.
You possess semantic search tools, database persistence, external account sync status engines, and goal trackers.

You have access to the following tools:
{tool_descriptions}

Use the following strict format for your reasoning loop:

Thought: Describe what you need to do next, what tools you need to use, or if you have enough information to answer.
Action: [tool_name]
Action Input: [exact argument for the tool: either a raw keyword, empty string, or complete JSON string depending on the tool documentation, without outer quotes]

The user will execute the tool and provide you with:
Observation: [tool output]

This loop of Thought -> Action -> Action Input -> Observation can repeat multiple times. When you are ready to give the final response to the user, format it as follows:

Thought: I now have all the necessary information.
Final Answer: [your detailed final answer summarizing findings, making intelligent suggestions, or presenting insights clearly]

RULES:
1. Output EXACTLY one Thought followed by EXACTLY one Action and Action Input, OR one Thought followed by EXACTLY one Final Answer.
2. Action Input must be a raw string. JSON strings should use double quotes inside the JSON e.g. {{"source_id": 1, "target_id": 2, "relation": "relates_to"}}.
3. Never hallucinate observations; wait for the next turn.
"""

    def parse_response(self, text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        thought = None
        action = None
        action_input = None
        final_answer = None
        
        thought_match = re.search(r"Thought:\s*(.*)", text, re.IGNORECASE)
        action_match = re.search(r"Action:\s*\[?([a-zA-Z0-9_]+)\]?", text, re.IGNORECASE)
        action_input_match = re.search(r"Action Input:\s*\[?(.*?)\]?$", text, re.IGNORECASE | re.MULTILINE)
        final_answer_match = re.search(r"Final Answer:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
        
        if thought_match:
            thought = thought_match.group(1).strip()
        if action_match:
            action = action_match.group(1).strip()
        if action_input_match:
            action_input = action_input_match.group(1).strip().strip("'\"")
        if final_answer_match:
            final_answer = final_answer_match.group(1).strip()
            
        return thought, action, action_input, final_answer

# ==============================================================================
# Live HTTP API Communication via Urllib
# ==============================================================================
def call_gemini(prompt: str, api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1000
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=15) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        return res_data["candidates"][0]["content"]["parts"][0]["text"]

def call_openai(prompt: str, api_key: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=15) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        return res_data["choices"][0]["message"]["content"]

def call_groq(prompt: str, api_key: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=15) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        return res_data["choices"][0]["message"]["content"]

# ==============================================================================
# Simulation / Demonstration Script Scenarios
# ==============================================================================
SIMULATED_SCENARIOS = {
    "sync_gmail_proactive": {
        "keywords": ["sync", "gmail", "branding", "insight"],
        "steps": [
            {
                "thought": "I need to sync the user's Gmail data to ingest the latest branding conversations, and then request proactive context insights.",
                "action": "sync_external_data",
                "action_input": "gmail",
                "observation": "Integration Ingestor Complete: Sync status updated for 'gmail'. Ingested 3 new memory cards into the SQLite Second Brain Database."
            },
            {
                "thought": "Gmail data successfully ingested. Now, I will compute current proactive insights using our diagnostic scanning tool.",
                "action": "get_proactive_insights",
                "action_input": "",
                "observation": "🧠 AETHER SECOND BRAIN COGNITIVE DIAGNOSTIC:\n - Memory Vault Density: 5 nodes indexed.\n - Semantic Graph Connections: 2 active relational links.\n\n⚠️ PROACTIVE WARNING PREDICTION:\n - Context: We detected active notes regarding a 'branding decision' scheduled for Friday.\n - Actionable Suggestion: You have not defined a structured Goal for 'Branding Selection' yet. Would you like me to formulate one?"
            },
            {
                "thought": "I now have all the necessary information to formulate the cognitive analysis response.",
                "final_answer": "Excellent! I have triggered a full Gmail sync and ingested your recent communication threads. I discovered a thread regarding a **Branding Decision** scheduled for Friday. Based on this, I've predicted your needs and proactively suggest setting up a goal for 'Branding Selection' and scheduling a decision log review session."
            }
        ]
    },
    "search_headphones_math": {
        "keywords": ["headphone", "divided by 5"],
        "steps": [
            {
                "thought": "I need to search the memory vault for information regarding headphones.",
                "action": "search_brain",
                "action_input": "headphones",
                "observation": "Found 1 memories matching 'headphones':\n - [ID 1] [NOTE] (personal) tags:[idea,sustainability,audio]: Idea: Solar-powered eco-friendly bluetooth headphones prototype. Build with bio-degradable casing."
            },
            {
                "thought": "I found the headphone idea memory card. Now, I need to evaluate the math equation (e.g. 525 divided by 5).",
                "action": "calculate",
                "action_input": "525 / 5",
                "observation": "105.0"
            },
            {
                "thought": "I have the memory details and arithmetic computation completed.",
                "final_answer": "I retrieved your Solar-Powered Headphones Idea (ID 1) from the vault, categorized under Personal, which details building a prototype with bio-degradable casing. Additionally, 525 divided by 5 computes securely to 105.0."
            }
        ]
    }
}

def find_simulated_scenario(query: str) -> Optional[str]:
    query_lower = query.lower()
    for scenario_name, data in SIMULATED_SCENARIOS.items():
        if all(kw in query_lower for kw in data["keywords"]):
            return scenario_name
    return None

# ==============================================================================
# Unified Agent Execution Engine
# ==============================================================================
def run_agent_backend(query: str, engine: str, api_key: str = None) -> List[Dict[str, str]]:
    if engine == "simulation":
        scenario_name = find_simulated_scenario(query)
        if scenario_name:
            return SIMULATED_SCENARIOS[scenario_name]["steps"]
        else:
            return [
                {
                    "thought": "The user entered a general query. I will guide them to trigger one of my integrated cognitive tools.",
                    "final_answer": "Welcome! I am running in **Simulation Mode** because no API key is specified.\n\nTo enable live, fully autonomous AI reasoning, configure your Developer Key in the Settings Panel.\n\nIn the meantime, you can experience my ReAct reasoning cycles by asking one of these configured tasks:\n1. *\"Sync my Gmail account and search for branding insights proactively!\"*\n2. *\"Search my memories for my headphone idea, and calculate what is 525 divided by 5?\"*\n\nTry entering one to see my reasoning loop query SQLite, run tools, and evaluate answers!"
                }
            ]
            
    agent = ReActAgent()
    system_prompt = agent.get_system_prompt()
    max_steps = 6
    step_count = 0
    
    current_prompt = f"{system_prompt}\nUser Query: {query}\n"
    steps_history = []
    
    while step_count < max_steps:
        step_count += 1
        
        try:
            if engine == "gemini":
                llm_response = call_gemini(current_prompt, api_key)
            elif engine == "openai":
                llm_response = call_openai(current_prompt, api_key)
            else: # engine == "groq"
                llm_response = call_groq(current_prompt, api_key)
        except Exception as e:
            steps_history.append({
                "thought": "I encountered an error trying to connect to the language model API.",
                "final_answer": f"API Connection Error: {str(e)}. Please verify your secret key."
            })
            break
            
        thought, action, action_input, final_answer = agent.parse_response(llm_response)
        
        step_data = {}
        if thought:
            step_data["thought"] = thought
        else:
            step_data["thought"] = "I am processing the query."
            
        if final_answer:
            step_data["final_answer"] = final_answer
            steps_history.append(step_data)
            break
            
        if action and action_input is not None:
            step_data["action"] = action
            step_data["action_input"] = action_input
            
            if action in agent.tools:
                try:
                    # Special check for empty string inputs
                    if action in ["get_goals_habits", "get_proactive_insights"] and not action_input:
                        observation = agent.tools[action]("")
                    else:
                        observation = agent.tools[action](action_input)
                except Exception as ex:
                    observation = f"Error: Tool execution failed with exception: {str(ex)}"
            else:
                observation = f"Error: Tool '{action}' is not supported. Choose from: {list(agent.tools.keys())}"
                
            step_data["observation"] = observation
            steps_history.append(step_data)
            
            current_prompt += f"\nThought: {thought or ''}\nAction: {action}\nAction Input: {action_input}\nObservation: {observation}\n"
        else:
            correction = "Error: Your response did not follow the strict format. You must output 'Thought: ...' followed by either 'Action: ...' and 'Action Input: ...' OR 'Final Answer: ...'."
            step_data["observation"] = "Format Error: Attempting auto-correction..."
            steps_history.append(step_data)
            current_prompt += f"\nObservation: {correction}\n"
            
    else:
        steps_history.append({
            "thought": "I reached the maximum step limit without arriving at a final answer.",
            "final_answer": "Error: Maximum reasoning depth exceeded."
        })
        
    return steps_history

# ==============================================================================
# Pure-Python Web Server
# ==============================================================================
class AgentHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Keep console clean
        
    def do_GET(self):
        # Prevent Path Traversal by normalizing paths
        normalized_path = os.path.normpath(self.path)
        
        if normalized_path == "/" or normalized_path == "/index.html" or normalized_path == ".":
            try:
                target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
                with open(target_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error serving webpage: {str(e)}".encode("utf-8"))
        elif normalized_path == "/ai_core_art.png":
            try:
                target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_core_art.png")
                with open(target_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        # Standard API endpoints
        if self.path == "/api/run":
            try:
                data = json.loads(post_data.decode("utf-8"))
                query = data.get("query", "")
                engine = data.get("engine", "simulation")
                api_key = data.get("api_key", None)
                
                if engine != "simulation" and not api_key:
                    if engine == "gemini":
                        api_key = os.environ.get("GEMINI_API_KEY")
                    elif engine == "openai":
                        api_key = os.environ.get("OPENAI_API_KEY")
                    else: # engine == "groq"
                        api_key = os.environ.get("GROQ_API_KEY")
                        
                steps = run_agent_backend(query, engine, api_key)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"steps": steps}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/dashboard":
            # Fetches SQLite data for frontend tables
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM memories ORDER BY created_at DESC")
                memories = [dict(row) for row in cursor.fetchall()]
                
                cursor.execute("""
                    SELECT c.id, c.source_id, c.target_id, c.relation_type, 
                           m1.content as source_content, m2.content as target_content
                    FROM connections c
                    JOIN memories m1 ON c.source_id = m1.id
                    JOIN memories m2 ON c.target_id = m2.id
                """)
                connections = [dict(row) for row in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM goals ORDER BY created_at DESC")
                goals = [dict(row) for row in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM habits ORDER BY name ASC")
                habits = [dict(row) for row in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM integrations")
                integrations = [dict(row) for row in cursor.fetchall()]
                
                conn.close()
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "memories": memories,
                    "connections": connections,
                    "goals": goals,
                    "habits": habits,
                    "integrations": integrations
                }).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Failed to retrieve dashboard stats: {str(e)}"}).encode("utf-8"))
                
        elif self.path == "/api/memory":
            # Direct addition of a memory note from the frontend form
            try:
                data = json.loads(post_data.decode("utf-8"))
                content = data.get("content", "").strip()
                mem_type = data.get("type", "note").strip().lower()
                category = data.get("category", "personal").strip().lower()
                tags = data.get("tags", "").strip()
                
                if not content:
                    raise ValueError("Content cannot be empty.")
                    
                now = datetime.datetime.now().isoformat()
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO memories (content, type, category, tags, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (content, mem_type, category, tags, now, "{}"))
                new_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "id": new_id}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/sync":
            # Sync trigger
            try:
                data = json.loads(post_data.decode("utf-8"))
                service = data.get("service", "").strip()
                res = SecondBrainTools.sync_external_data(service)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": res}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/habit/complete":
            try:
                data = json.loads(post_data.decode("utf-8"))
                habit_id = int(data.get("id"))
                today = datetime.date.today().isoformat()
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT streak, last_completed FROM habits WHERE id = ?", (habit_id,))
                row = cursor.fetchone()
                
                if row:
                    last_completed = row['last_completed']
                    current_streak = row['streak']
                    
                    if last_completed == today:
                        # Already done today, don't double count
                        message = "Habit check-in already recorded for today!"
                    else:
                        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
                        if last_completed == yesterday:
                            new_streak = current_streak + 1
                        else:
                            new_streak = 1 # Streak reset
                            
                        cursor.execute("UPDATE habits SET streak = ?, last_completed = ? WHERE id = ?", (new_streak, today, habit_id))
                        conn.commit()
                        message = f"Habit updated successfully! Streak is now {new_streak} days."
                else:
                    raise ValueError(f"Habit with ID {habit_id} not found.")
                    
                conn.close()
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": message}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/goal/update":
            try:
                data = json.loads(post_data.decode("utf-8"))
                goal_id = int(data.get("id"))
                progress = int(data.get("progress"))
                
                if progress < 0 or progress > 100:
                    raise ValueError("Progress must be between 0 and 100.")
                    
                status = "completed" if progress == 100 else "active"
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE goals SET progress = ?, status = ? WHERE id = ?", (progress, status, goal_id))
                conn.commit()
                conn.close()
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/decision":
            # Saves a highly structured Decision Log as a rich memory node
            try:
                data = json.loads(post_data.decode("utf-8"))
                problem = data.get("problem", "").strip()
                option_a = data.get("option_a", "").strip()
                option_b = data.get("option_b", "").strip()
                pros_cons = data.get("pros_cons", "").strip()
                choice = data.get("choice", "").strip()
                reflections = data.get("reflections", "").strip()
                
                if not problem or not choice:
                    raise ValueError("Decision problem and finalized choice cannot be empty.")
                    
                content = f"Decision Log: '{problem}' | Finalized Choice: {choice}."
                tags = "decision,logs"
                
                metadata = {
                    "problem": problem,
                    "option_a": option_a,
                    "option_b": option_b,
                    "pros_cons": pros_cons,
                    "chosen_choice": choice,
                    "reflections": reflections
                }
                
                now = datetime.datetime.now().isoformat()
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO memories (content, type, category, tags, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (content, "decision", "personal", tags, now, json.dumps(metadata)))
                new_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "id": new_id}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/clear":
            try:
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "second_brain.db")
                if os.path.exists(db_path):
                    os.remove(db_path)
                init_db()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/connect":
            try:
                data = json.loads(post_data.decode("utf-8"))
                source_id = int(data.get("source_id"))
                target_id = int(data.get("target_id"))
                relation = data.get("relation", "relates_to").strip().lower()
                
                res = SecondBrainTools.link_memories(json.dumps({
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation": relation
                }))
                
                if "Error" in res:
                    raise ValueError(res)
                    
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": res}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def start_web_server():
    host = "127.0.0.1"
    port = 8000
    
    init_db()
    handler = AgentHTTPRequestHandler
    
    print("====================================================")
    print("   🧠 AETHER DIGITAL SECOND BRAIN ACTIVE 🧠         ")
    print("====================================================")
    print(f"📡 Web Dashboard Serving at: http://{host}:{port}")
    print("🔒 Security Sandbox: Bind bound exclusively to localhost.")
    print("Press Ctrl+C to terminate.")
    
    try:
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer((host, port), handler) as httpd:
            def launch_browser():
                time.sleep(1.0)
                webbrowser.open(f"http://{host}:{port}")
                
            threading.Thread(target=launch_browser, daemon=True).start()
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Server. Goodbye!\n")
    except Exception as e:
        print(f"\nServer error: {str(e)}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digital Second Brain Agent Runner")
    parser.add_argument("--web", "-w", action="store_true", help="Launch interactive web dashboard")
    args = parser.parse_args()
    
    if args.web:
        start_web_server()
    else:
        # CLI execution backup
        init_db()
        print("Backend Server setup complete.")
        print("Run with '--web' flag to launch the premium dashboard!")
