from langchain_community.utilities import SQLDatabase
from config import DEPARTMENT_TABLE_MAP
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_for_department(department_name: str) -> SQLDatabase:
    allowed_tables = DEPARTMENT_TABLE_MAP.get(department_name, [])

    return SQLDatabase.from_uri(
        os.getenv("MYSQL_URI"),
        include_tables=allowed_tables
    )
