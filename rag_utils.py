"""
RAG (Retrieval-Augmented Generation) Utilities
Handles document processing and AI-powered recommendations
"""

import os
from pathlib import Path
from functools import lru_cache
import json

# Load environment variables from .env file (if exists)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not required if env vars are set directly (e.g., on Render)

# LangChain imports
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage, SystemMessage

# Directory paths
AI_DOCS_DIR = Path(__file__).parent / "ai-docs"
VECTORSTORE_DIR = Path(__file__).parent / "data" / "vectorstore"


def get_openai_api_key():
    """Get OpenAI API key from environment."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    return api_key


@lru_cache(maxsize=1)
def load_vectorstore():
    """Load or create the vector store from PDF documents."""

    api_key = get_openai_api_key()
    embeddings = OpenAIEmbeddings(openai_api_key=api_key)

    # Check if vectorstore already exists
    if VECTORSTORE_DIR.exists() and any(VECTORSTORE_DIR.iterdir()):
        print("Loading existing vector store...")
        vectorstore = Chroma(
            persist_directory=str(VECTORSTORE_DIR),
            embedding_function=embeddings
        )
        return vectorstore

    # Create new vectorstore from PDFs
    print("Creating new vector store from PDFs...")
    documents = []

    pdf_files = [
        "Advisory_organic_village_clusters 1.pdf",
        "Farm Livelihoods Interventions Under DAY NRLM.pdf",
        "Guidelines_on_promotion_IFC_under_DAY_NRLM 1.pdf",
        "Natural_farming_training_combined.pdf"
    ]

    for pdf_file in pdf_files:
        pdf_path = AI_DOCS_DIR / pdf_file
        if pdf_path.exists():
            print(f"  Loading: {pdf_file}")
            try:
                loader = PyPDFLoader(str(pdf_path))
                docs = loader.load()
                # Add source metadata
                for doc in docs:
                    doc.metadata["source_file"] = pdf_file
                documents.extend(docs)
            except Exception as e:
                print(f"  Error loading {pdf_file}: {e}")

    if not documents:
        raise ValueError("No documents could be loaded from PDFs")

    # Split documents into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    splits = text_splitter.split_documents(documents)
    print(f"  Created {len(splits)} document chunks")

    # Create vectorstore
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=str(VECTORSTORE_DIR)
    )

    print("Vector store created and persisted.")
    return vectorstore


def get_relevant_context(query: str, k: int = 5) -> list:
    """Retrieve relevant document chunks for a query."""
    try:
        vectorstore = load_vectorstore()
        docs = vectorstore.similarity_search(query, k=k)
        return [{"content": doc.page_content, "source": doc.metadata.get("source_file", "Unknown")} for doc in docs]
    except Exception as e:
        print(f"Error retrieving context: {e}")
        return []


def generate_recommendation(
    block_name: str,
    district_name: str,
    intervention: str,
    feasibility_score: float,
    metrics: list,
    filters: list
) -> dict:
    """
    Generate AI-powered recommendation based on block data and policy documents.

    Args:
        block_name: Name of the block
        district_name: Name of the district
        intervention: Selected intervention type
        feasibility_score: Calculated feasibility score (0-100)
        metrics: List of metric dicts with {label, value, in_range, min, max}
        filters: List of active filter configurations

    Returns:
        dict with 'recommendation' text and 'sources' list
    """

    try:
        api_key = get_openai_api_key()
    except ValueError as e:
        return {
            "recommendation": "AI recommendations require OpenAI API key configuration.",
            "sources": [],
            "error": str(e)
        }

    # Build query for context retrieval
    failing_metrics = [m for m in metrics if not m.get("in_range", True)]
    passing_metrics = [m for m in metrics if m.get("in_range", True)]

    context_query = f"""
    {intervention} intervention in {district_name}, Assam
    Key challenges: {', '.join([m['label'] for m in failing_metrics[:3]]) if failing_metrics else 'none identified'}
    Strengths: {', '.join([m['label'] for m in passing_metrics[:3]]) if passing_metrics else 'none identified'}
    """

    # Retrieve relevant policy context
    context_docs = get_relevant_context(context_query, k=5)
    context_text = "\n\n".join([f"[{doc['source']}]: {doc['content']}" for doc in context_docs])

    # Build the metrics summary
    metrics_summary = []
    for m in metrics:
        status = "✓ Within range" if m.get("in_range", True) else "✗ Outside range"
        metrics_summary.append(f"- {m['label']}: {m.get('value', 'N/A')} ({status}, target: {m.get('min', 'N/A')}-{m.get('max', 'N/A')})")

    metrics_text = "\n".join(metrics_summary) if metrics_summary else "No metrics data available"

    # Create the prompt
    system_prompt = """You are an agricultural development advisor for IWMI (International Water Management Institute)
working on the LEAF DSS (Landscape Evaluation & Assessment Framework) in Assam, India.

Your role is to provide actionable recommendations for agricultural interventions based on:
1. The block/area's current indicators and feasibility assessment
2. Official government guidelines and policies (provided as context)

IMPORTANT GUIDELINES:
- Base your recommendations ONLY on the policy documents provided in the context
- Be specific and actionable - mention concrete steps from the guidelines
- Reference which policy/guideline supports each recommendation
- Keep recommendations concise (3-5 key points)
- Focus on the most critical gaps that need to be addressed
- If feasibility is high, suggest next steps for implementation
- If feasibility is low, prioritize which parameters to improve first
- Use simple language suitable for field officers and panchayat members"""

    user_prompt = f"""Generate a recommendation for implementing {intervention} in {block_name} block, {district_name} district, Assam.

FEASIBILITY ASSESSMENT:
- Overall Feasibility Score: {feasibility_score:.1f}%
- Category: {"High" if feasibility_score >= 75 else "Moderate" if feasibility_score >= 50 else "Low" if feasibility_score >= 25 else "Not Recommended"}

CURRENT INDICATORS:
{metrics_text}

RELEVANT POLICY CONTEXT:
{context_text}

Please provide:
1. A brief assessment of the block's readiness for this intervention
2. 3-5 specific, actionable recommendations based on the policy guidelines
3. Priority actions to address any gaps identified

Keep the response under 300 words and practical for field implementation."""

    # Call OpenAI
    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.3,
            openai_api_key=api_key
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = llm.invoke(messages)

        # Extract unique sources
        sources = list(set([doc["source"] for doc in context_docs]))

        return {
            "recommendation": response.content,
            "sources": sources,
            "feasibility_score": feasibility_score,
            "metrics_analyzed": len(metrics),
            "gaps_identified": len(failing_metrics),
            "retrieved_context": context_docs  # Include the actual retrieved chunks for verification
        }

    except Exception as e:
        return {
            "recommendation": f"Unable to generate AI recommendation: {str(e)}",
            "sources": [],
            "error": str(e)
        }


def initialize_vectorstore():
    """Initialize the vector store on startup (can be called manually)."""
    try:
        load_vectorstore()
        return True
    except Exception as e:
        print(f"Failed to initialize vector store: {e}")
        return False
