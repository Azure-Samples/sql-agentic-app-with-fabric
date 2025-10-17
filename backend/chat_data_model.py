import uuid
from datetime import datetime
import json
from flask import jsonify
from shared.utils import _to_json_primitive
from shared.utils import get_user_id
# Global variables that will be set by the main app
db = None
ChatHistory = None
ChatSession = None
ToolUsage = None
ToolDefinition = None
ChatHistoryManager = None

def init_chat_db(database):
    """Initialize the database reference and create models"""
    global db, ChatHistory, ChatSession, ToolUsage, ToolDefinition, ChatHistoryManager, AgentDefinition
    db = database

    # Helper function to convert model instances to dictionaries
    def to_dict_helper(instance):
        d = {}
        for column in instance.__table__.columns:
            value = getattr(instance, column.name)
            if isinstance(value, datetime):
                d[column.name] = value.isoformat()
            else:
                d[column.name] = value
        return d
    
    class AgentDefinition(db.Model):
        __tablename__ = 'agent_definitions'
        agent_id = db.Column(db.String(255), primary_key=True, default=lambda: f"agent_{uuid.uuid4()}")
        name = db.Column(db.String(255), unique=True, nullable=False)
        description = db.Column(db.Text)
        llm_config = db.Column(db.JSON, nullable=False)
        prompt_template = db.Column(db.Text, nullable=False)

        def to_dict(self):
            return to_dict_helper(self)

    class ChatSession(db.Model):
        __tablename__ = 'chat_sessions'
        session_id = db.Column(db.String(255), primary_key=True, default=lambda: f"session_{uuid.uuid4()}")
        user_id = db.Column(db.String(255), nullable=False)
        title = db.Column(db.String(500))
        created_at = db.Column(db.DateTime, default=datetime.now())
        updated_at = db.Column(db.DateTime, default=datetime.now(), onupdate=datetime.now())

        def to_dict(self):
            return to_dict_helper(self)
        
    class ToolDefinition(db.Model):
        __tablename__ = 'tool_definitions'
        tool_id = db.Column(db.String(255), primary_key=True, default=lambda: f"tooldef_{uuid.uuid4()}")
        name = db.Column(db.String(255), unique=True, nullable=False)
        description = db.Column(db.Text)
        input_schema = db.Column(db.JSON, nullable=False)
        version = db.Column(db.String(50), default='1.0.0')
        is_active = db.Column(db.Boolean, default=True)
        cost_per_call_cents = db.Column(db.Integer, default=0) 
        created_at = db.Column(db.DateTime, default=datetime.now())
        updated_at = db.Column(db.DateTime, default=datetime.now(), onupdate=datetime.now())

        def to_dict(self):
            return to_dict_helper(self)
        
    class ToolUsage(db.Model):
        __tablename__ = 'tool_usage'
        tool_call_id = db.Column(db.String(255), primary_key=True, default=lambda: f"tool_{uuid.uuid4()}")
        session_id = db.Column(db.String(255), nullable=False)
        trace_id = db.Column(db.String(255), db.ForeignKey('chat_history.trace_id'))
        tool_id = db.Column(db.String(255), db.ForeignKey('tool_definitions.tool_id'), nullable=False)
        tool_name = db.Column(db.String(255), nullable=False)
        tool_input = db.Column(db.JSON, nullable=False)
        tool_output = db.Column(db.JSON)
        tool_message = db.Column(db.Text)
        status = db.Column(db.String(50))
        
        # Additional tracking fields
        tokens_used = db.Column(db.Integer)

        def to_dict(self):
            return to_dict_helper(self)

    class ChatHistory(db.Model):
        __tablename__ = 'chat_history'
        message_id = db.Column(db.String(255), primary_key=True, default=lambda: f"msg_{uuid.uuid4()}")
        session_id = db.Column(db.String(255), db.ForeignKey('chat_sessions.session_id'))
        trace_id = db.Column(db.String(255), nullable=False)
        user_id = db.Column(db.String(255), nullable=False)
        agent_id = db.Column(db.String(255), nullable=True)
        message_type = db.Column(db.String(50), nullable=False)  # 'human', 'ai', 'system', 'tool_call', 'tool_result'
        content = db.Column(db.Text)

        model_name = db.Column(db.String(255))
        content_filter_results = db.Column(db.JSON)
        total_tokens = db.Column(db.Integer)
        completion_tokens = db.Column(db.Integer)
        prompt_tokens = db.Column(db.Integer)

        tool_id = db.Column(db.String(255))
        tool_name = db.Column(db.String(255))
        tool_input = db.Column(db.JSON)
        tool_output = db.Column(db.JSON) 
        tool_call_id = db.Column(db.String(255))
    
        finish_reason = db.Column(db.String(255))
        response_time_ms = db.Column(db.Integer)
        trace_end = db.Column(db.DateTime, default=datetime.now())

        def to_dict(self):
            return to_dict_helper(self)

    # --- Chat History Management Class ---
    class ChatHistoryManager:
        def __init__(self, session_id: str, user_id: str = 'user_1'):
            self.session_id = session_id
            self.user_id = user_id
            self._ensure_session_exists()

        def _ensure_session_exists(self):
            """Ensure the chat session exists in the database"""
            session = ChatSession.query.filter_by(session_id=self.session_id).first()
            if not session:
                session = ChatSession(
                    session_id=self.session_id,
                    title= "New Session",
                    user_id=self.user_id,
                )
                print("-----------------> New chat session created: ", session.session_id)
                db.session.add(session)
                db.session.commit()
        def add_trace_messages(self, serialized_messages: str, 
                               trace_duration: int):
            """Add all messages in a trace to the chat history"""
            trace_id = str(uuid.uuid4())
            message_list= _to_json_primitive(serialized_messages)
            print("New trace_id generated. Adding all messages for trace_id:", trace_id)
            for msg in message_list:
                if msg['type'] == 'human':
                    print("Adding human message to chat history")
                    _ = self.add_human_message(msg, trace_id)
                if msg['type'] == 'ai':
                    print("Adding AI message to chat history")
                    if msg.get("response_metadata", {}).get("finish_reason") != "tool_calls":
                        _ = self.add_ai_message(msg, trace_id, trace_duration)
                    elif msg.get("response_metadata", {}).get("finish_reason") == "tool_calls":
                        tool_call_dict = self.add_tool_call_message(msg, trace_id)
                if msg['type'] == "tool":
                    print("Adding tool message to chat history")
                    tool_result_dict = self.add_tool_result_message(msg, trace_id)
                    tool_call_dict.update(tool_result_dict)
                    _ = self.log_tool_usage(tool_call_dict, trace_id)
            res = "All trace messages added..."
            self.update_session_timestamp()
            return res
        def add_human_message(self, message: dict, trace_id: str):
            """Add the human message to chat history"""
            entry_message = ChatHistory(
                session_id=self.session_id,
                user_id=self.user_id,
                trace_id=trace_id,
                message_id = str(uuid.uuid4()),
                message_type="human",
                content=message['content'],
            )
            db.session.add(entry_message)
            db.session.commit()
            print("Human message added to chat history:", message["id"])
            return entry_message

        def add_ai_message(self, message: dict, trace_id: str, trace_duration: int):
            """Add the AI agent message to chat history"""
            agent_id = None
            if "name" in message:
                agent_id = db.session.query(AgentDefinition.agent_id).filter_by(name=message["name"]).scalar()
            entry_message = ChatHistory(
                session_id=self.session_id,
                user_id=self.user_id,
                agent_id = agent_id,
                message_id = message["id"],
                trace_id=trace_id,
                message_type="ai",
                content=message["content"],
                total_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('total_tokens'),
                completion_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('completion_tokens'),
                prompt_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('prompt_tokens'),
                model_name=message.get("response_metadata", {}).get('model_name'),
                content_filter_results=message.get("response_metadata", {}).get("prompt_filter_results", [{}])[0].get("content_filter_results"),
                finish_reason=message.get("response_metadata", {}).get("finish_reason"),
                response_time_ms=trace_duration,
            )
            db.session.add(entry_message)
            db.session.commit()
            print("AI message added to chat history:", message["id"])
            return entry_message

        def add_tool_call_message(self, message: dict, trace_id: str):
            """Log a tool call"""
            agent_id = None
            if "name" in message:
                agent_id = db.session.query(AgentDefinition.agent_id).filter_by(name=message["name"]).scalar()
            tool_name = message.get("additional_kwargs", {}).get('tool_calls', [{}])[0].get('function', {}).get("name")
            tool_id = db.session.query(ToolDefinition.tool_id).filter_by(name=tool_name).scalar()

            entry_message = ChatHistory(
                session_id=self.session_id,
                user_id=self.user_id,
                agent_id=agent_id,
                trace_id=trace_id,
                message_type='tool_call',
                tool_id = tool_id,
                tool_call_id=message.get("additional_kwargs", {}).get('tool_calls', [{}])[0].get('id'),
                tool_name=tool_name,
                total_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('total_tokens'),
                completion_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('completion_tokens'),
                prompt_tokens=message.get("response_metadata", {}).get("token_usage", {}).get('prompt_tokens'),
                tool_input=message.get("additional_kwargs", {}).get('tool_calls', [{}])[0].get('function', {}).get("arguments"),
                model_name=message.get("response_metadata", {}).get('model_name'),
                content_filter_results=message.get("response_metadata", {}).get("prompt_filter_results", [{}])[0].get("content_filter_results"),
                finish_reason=message.get("response_metadata", {}).get("finish_reason"),
            )
            db.session.add(entry_message)
            db.session.commit()
            print("Tool call message added to chat history:", message["id"])
            return {"tool_call_id": message.get("additional_kwargs", {}).get('tool_calls', [{}])[0].get('id'),
                    "tool_id": tool_id, "tool_name": tool_name,
                    "tool_input": message.get("additional_kwargs", {}).get('tool_calls', [{}])[0].get('function', {}).get("arguments"),
                    "total_tokens": message.get("response_metadata", {}).get("token_usage", {}).get('total_tokens')}

        def add_tool_result_message(self, message: dict, trace_id: str):
            """Log a tool result"""
            tool_name = message["name"]
            tool_id = db.session.query(ToolDefinition.tool_id).filter_by(name=tool_name).scalar()
            entry_message = ChatHistory(
                session_id=self.session_id,
                user_id=self.user_id,
                message_id=message["id"],
                tool_id=tool_id,
                tool_call_id=message["tool_call_id"],
                trace_id=trace_id,
                tool_name=message["name"],
                message_type='tool_result',
                content="",
                tool_output=message["content"],
            )
            db.session.add(entry_message)
            db.session.commit()
            print("Tool result message added to chat history:", message["id"])
            return {"tool_output": message["content"], "status": message["status"]}
        
        def update_session_timestamp(self):
            """Update the session's updated_at timestamp"""
            session = ChatSession.query.filter_by(session_id=self.session_id).first()
            if session:
                session.updated_at = datetime.now()
                db.session.commit()
                print("Session timestamp updated:", self.session_id)
     
        def log_tool_usage(self, tool_info: dict, trace_id: str):
            """Log detailed tool usage metrics"""
            existing = ToolUsage.query.filter_by(tool_call_id=tool_info.get("tool_call_id")).first()
            tool_msg = ''
            if(type(tool_info.get("tool_output")) is dict):
                tool_msg = tool_info.get("tool_output").get('message', '')
            else:
                tool_msg = str(tool_info.get("tool_output"))
            if("error" in str(tool_info.get("tool_output")).lower()):
                tool_call_status = "Errored"
            else:
                tool_call_status = "Healthy"

            if existing:
                existing.tool_output = tool_info.get("tool_output")
                existing.trace_id = trace_id
                existing.session_id = self.session_id
                existing.tool_id = tool_info.get("tool_id") 
                existing.tool_name = tool_info.get("tool_name") 
                existing.tool_input = tool_info.get("tool_input") 
                existing.tool_output = tool_info.get("tool_output") 
                existing.tool_message = tool_msg
                existing.status = tool_call_status
                existing.tokens_used = tool_info.get("total_tokens")
                db.session.commit()
            else:
                tool_usage = ToolUsage(
                    session_id=self.session_id,
                    trace_id=trace_id,
                    tool_call_id=tool_info.get("tool_call_id"),
                    tool_id=tool_info.get("tool_id"),
                    tool_name=tool_info.get("tool_name"),
                    tool_input=tool_info.get("tool_input"),
                    tool_output=tool_info.get("tool_output"),
                    tool_message=tool_msg,
                    status=tool_call_status,
                    tokens_used=tool_info.get("total_tokens")
                )
                db.session.add(tool_usage)
                db.session.commit()
            return 

        def get_conversation_history(self, limit: int = 50):
            """Retrieve conversation history for this session"""
            messages = db.session.query(ChatHistory.trace_id, ChatHistory.message_type, ChatHistory.content, ChatHistory.trace_end).filter_by(
                session_id=self.session_id
            ).order_by(ChatHistory.trace_end.desc()).limit(limit).all()
            
            # Note: messages will be tuples, not model objects, so you'll need to handle differently
            return [{"trace_id": msg[0], "message_type": msg[1], "content": msg[2], "trace_end": msg[3]} for msg in reversed(messages)]

    # Make classes available globally in this module
    globals()['ChatHistory'] = ChatHistory
    globals()['ChatSession'] = ChatSession
    globals()['ToolUsage'] = ToolUsage
    globals()['ToolDefinition'] = ToolDefinition
    globals()['ChatHistoryManager'] = ChatHistoryManager


def handle_chat_sessions(request):
    """Handle chat sessions GET and POST requests"""
    user_id = get_user_id()  # In production, get from auth
    
    if request.method == 'GET':
        sessions = ChatSession.query.filter_by(user_id=user_id).order_by(ChatSession.updated_at.desc()).all()
        return jsonify([session.to_dict() for session in sessions])
    
    if request.method == 'POST':
        data = request.json
        session = ChatSession(
            session_id = data.get('session_id'),
            user_id=user_id,
            title=data.get('title', 'New Chat Session'),
        )
        db.session.add(session)
        db.session.commit()
        return jsonify(session.to_dict()), 201



def clear_chat_history():
    """Clear all chat history data - USE WITH CAUTION"""
    try:
        # Delete in order to respect foreign key constraints
        ToolUsage.query.delete()
        ChatHistory.query.delete()
        ChatSession.query.delete()

        db.session.commit()
        return jsonify({"message": "All chat history cleared successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to clear chat history: {str(e)}"}), 500

def clear_session_data(session_id):
    """Clear chat history for a specific session"""
    try:
        # Delete in order to respect foreign key constraints
        ToolUsage.query.filter_by(session_id=session_id).delete()
        ChatHistory.query.filter_by(session_id=session_id).delete()
        ChatSession.query.filter_by(session_id=session_id).delete()
        
        db.session.commit()
        return jsonify({"message": f"Session {session_id} data cleared successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to clear session data: {str(e)}"}), 500
def initialize_tool_definitions():
    """Initialize tool definitions in the database"""
    tools_data = [
        {
            "name": "get_user_accounts",
            "description": "Retrieves all accounts for a given user",
            "input_schema": {"type": "object", "properties": {}},
            "cost_per_call_cents": 0
        },
        {
            "name": "get_transactions_summary",
            "description": "Provides spending summary with time period and account filters",
            "input_schema": {
                "type": "object",
                "properties": {
                    "time_period": {"type": "string"},
                    "account_name": {"type": "string"}
                }
            },
            "cost_per_call_cents": 0
        },
        {
            "name": "search_support_documents",
            "description": "Searches knowledge base for customer support answers",
            "input_schema": {
                "type": "object",
                "properties": {"user_question": {"type": "string"}},
                "required": ["user_question"]
            },
            "cost_per_call_cents": 2
        },
        {
            "name": "create_new_account",
            "description": "Creates a new bank account for the user",
            "input_schema": {
                "type": "object",
                "properties": {
                    "account_type": {"type": "string", "enum": ["checking", "savings", "credit"]},
                    "name": {"type": "string"},
                    "balance": {"type": "number"}
                },
                "required": ["account_type", "name"]
            },
            "cost_per_call_cents": 0
        },
        {
            "name": "transfer_money",
            "description": "Transfers money between accounts or to external accounts",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_account_name": {"type": "string"},
                    "to_account_name": {"type": "string"},
                    "amount": {"type": "number"},
                    "to_external_details": {"type": "object"}
                },
                "required": ["from_account_name", "amount"]
            },
            "cost_per_call_cents": 0
        }
    ]
    
    for tool_data in tools_data:
        existing_tool = ToolDefinition.query.filter_by(name=tool_data["name"]).first()
        if not existing_tool:
            tool_def = ToolDefinition(**tool_data)
            db.session.add(tool_def)
    
    db.session.commit()

def initialize_agent_definitions():
    """Initialize agent definitions in the database"""
    agents_data = [
                {
            "name": "banking_agent_v1",
            "description": "A customer support banking agent to help answer questions about their account and other general banking inquiries.",
            "llm_config": {
                "model": "gpt-4.1",
                "rate_limit": 50,
                "token_limit": 1000
            },
            "prompt_template": "You are a banking assistant. Answer the user's questions about their bank accounts."
        }

    ]
    
    for agent in agents_data:
        existing_agent = AgentDefinition.query.filter_by(name=agent["name"]).first()
        if not existing_agent:
            agent_def = AgentDefinition(**agent)
            db.session.add(agent_def)

    db.session.commit()