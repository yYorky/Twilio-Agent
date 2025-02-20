# voice_assistant/response_generation.py

import logging

from openai import OpenAI
from groq import Groq
import ollama

from voice_assistant.config import Config


def generate_response(model: str, api_key: str, chat_history: list, retriever=None):
    """
    Generate a response using the specified model and incorporate document context if available.
    
    Args:
    - model (str): The model to use ('openai', 'groq', 'ollama', 'local').
    - api_key (str): The API key for the model.
    - chat_history (list): The chat history as a list of messages.
    - retriever (FAISS retriever, optional): A retriever for fetching document context.

    Returns:
    - str: The generated response text.
    """
    try:
        # Extract latest user message
        user_input = chat_history[-1]["content"]

        # Retrieve relevant context from PDF if available
        document_context = ""
        if retriever:
            relevant_chunks = retriever.get_relevant_documents(user_input)
            document_context = "\n".join([doc.page_content for doc in relevant_chunks])
        
        # Add context to chat history
        if document_context:
            chat_history.append({"role": "system", "content": f"Use this document context:\n{document_context}"})

        # Generate response based on model type
        if model == "openai":
            return _generate_openai_response(api_key, chat_history)
        elif model == "groq":
            return _generate_groq_response(api_key, chat_history)
        elif model == "ollama":
            return _generate_ollama_response(chat_history)
        elif model == "local":
            return "Generated response from local model"
        else:
            raise ValueError("Unsupported response generation model")

    except Exception as e:
        logging.error(f"Failed to generate response: {e}")
        return "Error in generating response"


def _generate_openai_response(api_key, chat_history):
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=Config.OPENAI_LLM,
        messages=chat_history
    )
    return response.choices[0].message.content


def _generate_groq_response(api_key, chat_history):
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=Config.GROQ_LLM,
        messages=chat_history
    )
    return response.choices[0].message.content


def _generate_ollama_response(chat_history):
    response = ollama.chat(
        model=Config.OLLAMA_LLM,
        messages=chat_history,
    )
    return response['message']['content']