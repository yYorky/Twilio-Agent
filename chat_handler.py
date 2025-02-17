from langchain.chains import ConversationalRetrievalChain
from langchain.chains.conversation.memory import ConversationBufferMemory
from langchain_groq import ChatGroq
from voice_assistant.config import Config

groq_api_key = Config.GROQ_API_KEY

# Memory for conversation
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    output_key="answer",
    human_prefix="User",
    ai_prefix="Verbi",
)

# 📢 Default greeting message when call starts
DEFAULT_MESSAGE = "Hello! This is Verbi, your AI assistant. How can I assist you with your document today?"

def process_voice_query(user_input=None, retriever=None, is_first_message=False):
    """
    Takes voice input from Twilio WebSocket and generates an LLM response.

    Args:
        user_input (str): The user’s voice input.
        retriever: The document retriever for answering questions.
        is_first_message (bool): If True, sends a greeting message instead of processing input.

    Returns:
        str: The generated response text.
    """
    llm = ChatGroq(groq_api_key=groq_api_key, model_name="llama3-8b-8192")

    if is_first_message:
        return DEFAULT_MESSAGE  # Send greeting if first message

    if retriever:
        conversation_chain = ConversationalRetrievalChain.from_llm(
            llm=llm,
            retriever=retriever,
            memory=memory,
            return_source_documents=True,
            output_key="answer",
        )
        response = conversation_chain.invoke({"question": user_input})
        return response["answer"]
    else:
        return "I need a document to answer this. Please upload a PDF."
