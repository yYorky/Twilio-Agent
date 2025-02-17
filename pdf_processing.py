from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS

def process_pdf(pdf_path):
    """
    Extracts text from the uploaded PDF and creates a FAISS vector store.
    
    Args:
        pdf_path (str): Path to the uploaded PDF file.

    Returns:
        retriever: FAISS retriever for querying the document.
    """
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    final_documents = text_splitter.split_documents(docs)

    texts = [doc.page_content for doc in final_documents]
    
    # Generate embeddings
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vectors = FAISS.from_texts(texts, embeddings)
    
    return vectors.as_retriever(search_kwargs={"k": 5})
