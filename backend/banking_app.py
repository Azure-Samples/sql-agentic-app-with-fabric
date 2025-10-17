# import urllib.parse
import uuid
from datetime import datetime
import json
import time
from dateutil.relativedelta import relativedelta
# from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from langchain_openai import AzureOpenAIEmbeddings, AzureChatOpenAI
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_sqlserver import SQLServer_VectorStore
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.store.memory import InMemoryStore

from shared.db_connect import fabricsql_connection_bank_db
from shared.utils import get_user_id
import requests  # For calling analytics service
from langgraph.prebuilt import create_react_agent
from shared.utils import _serialize_messages

# Load Environment variables and initialize app
import os
load_dotenv(override=True)

app = Flask(__name__)
CORS(app)
global fixed_user_id
fixed_user_id = get_user_id()  # For simplicity, using a fixed user ID

# --- Azure OpenAI Configuration ---
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

# Analytics service URL
ANALYTICS_SERVICE_URL = "http://127.0.0.1:5002"

if not all([AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_EMBEDDING_DEPLOYMENT]):
    print("⚠️  Warning: One or more Azure OpenAI environment variables are not set.")
    ai_client = None
    embeddings_client = None
else:
    ai_client = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version="2024-10-21",
        api_key=AZURE_OPENAI_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT 
    )
    embeddings_client = AzureOpenAIEmbeddings(
        azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        openai_api_version="2024-10-21",
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
    )

# Database configuration for Azure SQL (banking data)
app.config['SQLALCHEMY_DATABASE_URI'] = "mssql+pyodbc://"
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'creator': fabricsql_connection_bank_db,
    'poolclass': QueuePool,
    'pool_size': 5,
    'max_overflow': 10,
    'pool_pre_ping': True,
    'pool_recycle': 3600,
    'pool_reset_on_return': 'rollback'
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Vector Store Initialization
server = os.getenv('DB_SERVER')
database = os.getenv('DB_DATABASE')
driver = os.getenv('DB_DRIVER', 'ODBC Driver 18 for SQL Server')

connection_string = os.getenv('FABRIC_SQL_CONNECTION_URL_BANK_DATA')

connection_url = f"mssql+pyodbc:///?odbc_connect={connection_string}"

vector_store = None
if embeddings_client:
    vector_store = SQLServer_VectorStore(
        connection_string=connection_url,
        table_name="DocsChunks_Embeddings",
        embedding_function=embeddings_client,
        embedding_length=1536,
        distance_strategy=DistanceStrategy.COSINE,
    )

def to_dict_helper(instance):
    d = {}
    for column in instance.__table__.columns:
        value = getattr(instance, column.name)
        if isinstance(value, datetime):
            d[column.name] = value.isoformat()
        else:
            d[column.name] = value
    return d

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from collections import defaultdict

def reconstruct_messages_from_history(history_data):
    """Converts DB history into LangChain message objects, sorted by trace_id and message order."""
    messages = []
    print("Reconstructing messages from history data:", history_data)
    
    if not history_data:
        return MemorySaver(), []
    
    # Group messages by trace_id
    traces = defaultdict(list)
    for msg_data in history_data:
        trace_id = msg_data.get('trace_id')
        if trace_id:
            traces[trace_id].append(msg_data)
    
    # Sort trace_ids chronologically
    sorted_trace_ids = sorted(traces.keys())
    
    # Process each trace in chronological order
    for trace_id in sorted_trace_ids:
        trace_messages = traces[trace_id]
        
        # Sort messages within each trace by message type priority
        message_priority = {
            'human': 1,
            'ai': 2
        }
        
        trace_messages.sort(key=lambda x: (
            message_priority.get(x.get('message_type'), 5),
            x.get('trace_end', ''),
        ))
        
        # Convert to LangChain message objects
        for msg_data in trace_messages:
            try:
                message_type = msg_data.get('message_type')
                content = msg_data.get('content', '')
                
                if message_type == 'human':
                    messages.append(HumanMessage(content=content))
                elif message_type == 'ai':
                    messages.append(AIMessage(content=content))
                
            except Exception as e:
                print(f"Error processing message in trace {trace_id}: {e}")
                continue
    
    print(f"Reconstructed {len(messages)} messages from {len(sorted_trace_ids)} traces")
    
    # Return both the memory saver and the historical messages
    return MemorySaver(), messages

# Banking Database Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.String(255), primary_key=True, default=lambda: f"user_{uuid.uuid4()}")
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    accounts = db.relationship('Account', backref='user', lazy=True)

    def to_dict(self):
        return to_dict_helper(self)

class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.String(255), primary_key=True, default=lambda: f"acc_{uuid.uuid4()}")
    user_id = db.Column(db.String(255), db.ForeignKey('users.id'), nullable=False)
    account_number = db.Column(db.String(255), unique=True, nullable=False, default=lambda: str(uuid.uuid4().int)[:12])
    account_type = db.Column(db.String(50), nullable=False)
    balance = db.Column(db.Float, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return to_dict_helper(self)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.String(255), primary_key=True, default=lambda: f"txn_{uuid.uuid4()}")
    from_account_id = db.Column(db.String(255), db.ForeignKey('accounts.id'))
    to_account_id = db.Column(db.String(255), db.ForeignKey('accounts.id'))
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    category = db.Column(db.String(255))
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return to_dict_helper(self)

# Analytics Service Integration
def call_analytics_service(endpoint, method='POST', data=None):
    """Helper function to call analytics service"""
    try:
        url = f"{ANALYTICS_SERVICE_URL}/api/{endpoint}"
        if method == 'POST':
            response = requests.post(url, json=data, timeout=5)
        else:
            response = requests.get(url, timeout=5)
        return response.json() if response.status_code < 400 else None
    except Exception as e:
        print(f"Analytics service call failed: {e}")
        return None


# AI Chatbot Tool Definitions (same as before)
def get_user_accounts(user_id: str = fixed_user_id) -> str:
    """Retrieves all accounts for a given user."""
    try:
        accounts = Account.query.filter_by(user_id=user_id).all()
        if not accounts:
            return "No accounts found for this user."
        return json.dumps([
            {"name": acc.name, "account_type": acc.account_type, "balance": acc.balance} 
            for acc in accounts
        ])
    except Exception as e:
        return f"Error retrieving accounts: {str(e)}"

def get_transactions_summary(user_id: str = fixed_user_id, time_period: str = 'this month', account_name: str = None) -> str:
    """Provides a summary of the user's spending. Can be filtered by a time period and a specific account."""
    try:
        query = db.session.query(Transaction.category, db.func.sum(Transaction.amount).label('total_spent')).filter(
            Transaction.type == 'payment'
        )
        if account_name:
            account = Account.query.filter_by(user_id=user_id, name=account_name).first()
            if not account:
                return json.dumps({"status": "error", "message": f"Account '{account_name}' not found."})
            query = query.filter(Transaction.from_account_id == account.id)
        else:
            user_accounts = Account.query.filter_by(user_id=user_id).all()
            account_ids = [acc.id for acc in user_accounts]
            query = query.filter(Transaction.from_account_id.in_(account_ids))

        end_date = datetime.utcnow()
        if 'last 6 months' in time_period.lower():
            start_date = end_date - relativedelta(months=6)
        elif 'this year' in time_period.lower():
            start_date = end_date.replace(month=1, day=1, hour=0, minute=0, second=0)
        else:
            start_date = end_date.replace(day=1, hour=0, minute=0, second=0)
        
        query = query.filter(Transaction.created_at.between(start_date, end_date))
        results = query.group_by(Transaction.category).order_by(db.func.sum(Transaction.amount).desc()).all()
        total_spending = sum(r.total_spent for r in results)
        
        summary_details = {
            "total_spending": round(total_spending, 2),
            "period": time_period,
            "account_filter": account_name or "All Accounts",
            "top_categories": [{"category": r.category, "amount": round(r.total_spent, 2)} for r in results[:3]]
        }

        if not results:
            return json.dumps({"status": "success", "summary": f"You have no spending for the period '{time_period}' in account '{account_name or 'All Accounts'}'."})

        return json.dumps({"status": "success", "summary": summary_details})
    except Exception as e:
        print(f"ERROR in get_transactions_summary: {e}")
        return json.dumps({"status": "error", "message": f"An error occurred while generating the transaction summary."})

def search_support_documents(user_question: str) -> str:
    """Searches the knowledge base for answers to customer support questions using vector search."""
    if not vector_store:
        return "The vector store is not configured."
    try:
        results = vector_store.similarity_search_with_score(user_question, k=3)
        relevant_docs = [doc.page_content for doc, score in results if score < 0.5]
        print("-------------> ", relevant_docs)
        if not relevant_docs:
            return "No relevant support documents found to answer this question."

        context = "\n\n---\n\n".join(relevant_docs)
        return context

    except Exception as e:
        print(f"ERROR in search_support_documents: {e}")
        return "An error occurred while searching for support documents."

def create_new_account(user_id: str = fixed_user_id, account_type: str = 'checking', name: str = None, balance: float = 0.0) -> str:
    """Creates a new bank account for the user."""
    if not name:
        return json.dumps({"status": "error", "message": "An account name is required."})
    try:
        new_account = Account(user_id=user_id, account_type=account_type, balance=balance, name=name)
        db.session.add(new_account)
        db.session.commit()
        return json.dumps({
            "status": "success", "message": f"Successfully created new {account_type} account '{name}' with balance ${balance:.2f}.",
            "account_id": new_account.id, "account_name": new_account.name
        })
    except Exception as e:
        db.session.rollback()
        return f"Error creating account: {str(e)}"

def transfer_money(user_id: str = fixed_user_id, from_account_name: str = None, to_account_name: str = None, amount: float = 0.0, to_external_details: dict = None) -> str:
    """Transfers money between user's accounts or to an external account."""
    if not from_account_name or (not to_account_name and not to_external_details) or amount <= 0:
        return json.dumps({"status": "error", "message": "Missing required transfer details."})
    try:
        from_account = Account.query.filter_by(user_id=user_id, name=from_account_name).first()
        if not from_account:
            return json.dumps({"status": "error", "message": f"Account '{from_account_name}' not found."})
        if from_account.balance < amount:
            return json.dumps({"status": "error", "message": "Insufficient funds."})
        
        to_account = None
        if to_account_name:
            to_account = Account.query.filter_by(user_id=user_id, name=to_account_name).first()
            if not to_account:
                 return json.dumps({"status": "error", "message": f"Recipient account '{to_account_name}' not found."})
        
        new_transaction = Transaction(
            from_account_id=from_account.id, to_account_id=to_account.id if to_account else None,
            amount=amount, type='transfer', description=f"Transfer to {to_account_name or to_external_details.get('name', 'External')}",
            category='Transfer', status='completed'
        )
        from_account.balance -= amount
        if to_account:
            to_account.balance += amount
        db.session.add(new_transaction)
        db.session.commit()
        return json.dumps({"status": "success", "message": f"Successfully transferred ${amount:.2f}."})
    except Exception as e:
        db.session.rollback()
        return f"Error during transfer: {str(e)}"

# Banking API Routes
@app.route('/api/accounts', methods=['GET', 'POST'])
def handle_accounts():
    user_id = fixed_user_id
    if request.method == 'GET':
        accounts = Account.query.filter_by(user_id=user_id).all()
        return jsonify([acc.to_dict() for acc in accounts])
    if request.method == 'POST':
        data = request.json
        account_str = create_new_account(user_id=user_id, account_type=data.get('account_type'), name=data.get('name'), balance=data.get('balance', 0))
        return jsonify(json.loads(account_str)), 201
    
@app.route('/api/transactions', methods=['GET', 'POST'])
def handle_transactions():
    user_id = fixed_user_id
    if request.method == 'GET':
        accounts = Account.query.filter_by(user_id=user_id).all()
        account_ids = [acc.id for acc in accounts]
        transactions = Transaction.query.filter((Transaction.from_account_id.in_(account_ids)) | (Transaction.to_account_id.in_(account_ids))).order_by(Transaction.created_at.desc()).all()
        return jsonify([t.to_dict() for t in transactions])
    if request.method == 'POST':
        data = request.json
        result_str = transfer_money(
            user_id=user_id, from_account_name=data.get('from_account_name'), to_account_name=data.get('to_account_name'),
            amount=data.get('amount'), to_external_details=data.get('to_external_details')
        )
        result = json.loads(result_str)
        status_code = 201 if result.get("status") == "success" else 400
        return jsonify(result), status_code
@app.route('/api/chatbot', methods=['POST'])
def chatbot():
    if not ai_client:
        return jsonify({"error": "Azure OpenAI client is not configured."}), 503

    data = request.json
    messages = data.get("messages", [])
    session_id = data.get("session_id")
    user_id = fixed_user_id
    # session_id_temp = "session_74a4b39c-72d9-4b30-b8b4-f317e4366e1e"
    
    # Fetch chat history from the analytics service
    history_data = call_analytics_service(f"chat/history/{session_id}", method='GET')
    
    # Reconstruct messages and session memory
    session_memory, historical_messages = reconstruct_messages_from_history(history_data)

    
    # Print debugging info
    print("\n--- Context being passed to the agent ---")
    print(f"History data received: {len(history_data) if history_data else 0} messages")
    print(f"Historical messages reconstructed: {len(historical_messages)}")
    for i, msg in enumerate(historical_messages):
        print(f"  {i+1}. [{msg.__class__.__name__}] {msg.content[:50]}...")
    print("-----------------------------------------\n")

    # Extract current user message
    user_message = messages[-1].get("content", "")
    tools = [get_user_accounts, get_transactions_summary,
            search_support_documents, create_new_account,
            transfer_money]

    # Initialize banking agent
    banking_agent = create_react_agent(
        model=ai_client,
        tools=tools,
        checkpointer=session_memory,
        prompt="""
        - You are a customer support agent.
        - You can use the provided tools to answer user questions and perform tasks.
        - If you were unable to find an answer, inform the user.
        - Do not use your general knowledge to answer questions.""",
        name = "banking_agent_v1"
    )
    
    # Thread config for session management
    thread_config = {"configurable": {"thread_id": session_id}}
    all_messages = historical_messages + [HumanMessage(content=user_message)]

    trace_start_time = time.time()
    response = banking_agent.invoke(
        {"messages": all_messages}, 
        config=thread_config
    )
    end_time = time.time()
    trace_duration = int((end_time - trace_start_time) * 1000)

    print("################### TRACE RESPONSE ######################")
    all_messages = response['messages']
    historical_count = len(historical_messages)
    final_messages = all_messages[historical_count:]

    for msg in final_messages:
        print(f"[{msg.__class__.__name__}] {msg.content}")

    analytics_data = {
        "session_id": session_id,
        "user_id": user_id,
        "messages": _serialize_messages(final_messages),
        "trace_duration": trace_duration,
    }

    # calling analytics service to capture this trace
    call_analytics_service("chat/log-trace", data=analytics_data)
    return jsonify({
        "response": final_messages[-1].content,
        "session_id": session_id,
        "tools_used": []
    })
if __name__ == '__main__':
    print("[Banking Service] Connecting to database...")
    print("You may be prompted for credentials...")
    
    with app.app_context():
        db.create_all()
        print("[Banking Service] Database initialized")

    print("Starting Banking Service on port 5001...")
    app.run(debug=False, port=5001, use_reloader=False)