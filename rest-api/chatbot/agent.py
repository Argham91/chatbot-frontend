from typing import TypedDict, List
import logging

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from config import (
    DEPARTMENT_DESCRIPTIONS,
    FORBIDDEN_SQL,
    MAX_RETRIES,
    MAX_ROWS,
    ROLE_PERMISSIONS
)

from db_utils import get_db_for_department
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool

# ================= SETUP =================
logging.basicConfig(level=logging.INFO)
llm = ChatOpenAI(temperature=0, model="gpt-4o")

# ================= STATE =================
class AgentState(TypedDict):
    question: str
    chat_history: List[str]
    user_role: str

    # planner output
    departments: List[str]
    plan: List[str]

    # execution
    sql_query: str
    db_result: str

    final_answer: str
    retry_count: int

# ================= PLANNER =================
class Plan(BaseModel):
    departments: List[str]
    steps: List[str]

def supervisor_node(state: AgentState):
    role = state["user_role"]
    question = state["question"]

    allowed_departments = ROLE_PERMISSIONS.get(role, [])

    if "*" not in allowed_departments:
        allowed_desc = {
            k: v for k, v in DEPARTMENT_DESCRIPTIONS.items()
            if k in allowed_departments
        }
    else:
        allowed_desc = DEPARTMENT_DESCRIPTIONS

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         """You are an enterprise planning agent.

Identify ALL required departments and break into steps.

Rules:
- Only use allowed departments: {allowed_departments}
- No hallucination
- Simple question → one department
- Complex → multiple

Return:
- departments
- steps
"""),
        ("user", "{question}")
    ])

    planner = prompt | llm.with_structured_output(Plan)

    result = planner.invoke({
        "question": question,
        "allowed_departments": list(allowed_desc.keys())
    })

    filtered_departments = [
        d for d in result.departments if d in allowed_desc
    ]

    if not filtered_departments:
        filtered_departments = [list(allowed_desc.keys())[0]]

    return {
        "departments": filtered_departments,
        "plan": result.steps
    }

# ================= SQL SAFETY =================
def is_safe_sql(sql: str):
    sql_upper = sql.upper()
    return not any(keyword in sql_upper for keyword in FORBIDDEN_SQL)

# ================= DATA MASKING =================
SENSITIVE_COLUMNS = ["salary", "ssn", "bank_account"]

def apply_column_masking(sql: str, role: str):
    if role != "admin":
        for col in SENSITIVE_COLUMNS:
            sql = sql.replace(col, f"NULL as {col}")
    return sql

# ================= SQL GENERATION =================
sql_prompt = ChatPromptTemplate.from_messages([
    ("system",
     """You are an expert SQL generator.

Rules:
- ONLY SELECT queries
- NO mutation (INSERT, UPDATE, DELETE, etc.)
- LIMIT {max_rows}
- Return ONLY SQL
"""),
    ("user", "Question: {question}")
])

sql_chain = sql_prompt | llm | StrOutputParser()

# ================= MULTI-SQL NODE =================
def multi_sql_node(state: AgentState):
    question = state["question"]
    role = state["user_role"]
    departments = state.get("departments", [])

    all_results = {}

    for dept in departments:

        # RBAC enforcement
        allowed = ROLE_PERMISSIONS.get(role, [])
        if "*" not in allowed and dept not in allowed:
            continue

        db = get_db_for_department(dept)
        tool = QuerySQLDataBaseTool(db=db)

        for attempt in range(MAX_RETRIES):

            sql_query = sql_chain.invoke({
                "question": f"{question} (focus on {dept})",
                "max_rows": MAX_ROWS
            })

            sql_query = apply_column_masking(sql_query, role)

            logging.info(f"[{dept}] SQL: {sql_query}")

            if not is_safe_sql(sql_query):
                continue

            try:
                result = tool.invoke(sql_query)

                all_results[dept] = {
                    "query": sql_query,
                    "result": str(result)
                }
                break

            except Exception as e:
                logging.warning(f"[{dept}] attempt {attempt} failed: {e}")

    return {
        "db_result": str(all_results)
    }

# ================= ANSWER NODE =================
def generate_answer_node(state: AgentState):
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         """You are an enterprise analyst.

Combine results from multiple departments.
Give a clear, concise answer.
"""),
        ("user",
         "Question: {question}\n\nDepartment Results:\n{db_result}")
    ])

    chain = prompt | llm
    result = chain.invoke(state)

    return {"final_answer": result.content}

# ================= GRAPH =================
workflow = StateGraph(AgentState)

workflow.add_node("planner", supervisor_node)
workflow.add_node("multi_sql", multi_sql_node)
workflow.add_node("answer", generate_answer_node)

workflow.set_entry_point("planner")

workflow.add_edge("planner", "multi_sql")
workflow.add_edge("multi_sql", "answer")
workflow.add_edge("answer", END)

app = workflow.compile()

# ================= RUN =================
if __name__ == "__main__":
    response = app.invoke({
        "question": "What is total production cost?",
        "chat_history": [],
        "user_role": "admin"
    })

    print("\nFINAL ANSWER:\n", response["final_answer"])
