# AI Recommendation System - Methodology

## Overview

The LEAF DSS AI Recommendation System uses Retrieval-Augmented Generation (RAG) to provide policy-grounded recommendations for agricultural interventions. Instead of generic advice, the system retrieves relevant information from official government guidelines and policy documents to generate contextual, actionable recommendations.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Policy PDFs    │────▶│  Text Extraction │────▶│  Text Chunks    │
│  (5 documents)  │     │  & Chunking      │     │  (1000 chars)   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  ChromaDB       │◀────│  OpenAI          │◀────│  Embedding      │
│  Vector Store   │     │  Embeddings      │     │  Generation     │
└────────┬────────┘     └──────────────────┘     └─────────────────┘
         │
         │  (Similarity Search)
         ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Retrieved      │────▶│  GPT-4o-mini     │────▶│  AI             │
│  Context        │     │  LLM             │     │  Recommendation │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Components

### 1. Document Processing

**Source Documents:** every `*.pdf` file dropped into `leaf_flask/ai-docs/` is picked up automatically (LEAF-57, 2026-05-29). The current set covers:

- `Advisory_organic_village_clusters 1.pdf` - Guidelines for organic village clusters
- `Farm Livelihoods Interventions Under DAY NRLM.pdf` - DAY-NRLM farm livelihood schemes (covers livestock SHGs)
- `Guidelines_on_promotion_IFC_under_DAY_NRLM 1.pdf` - Integrated Farming Cluster guidelines
- `Natural_farming_training_combined.pdf` - Natural farming training materials
- `National_Livestock_Mission_Guidelines_Jan2025.pdf` - National Livestock Mission (NLM) operational guidelines, Jan 2025 (cross-cutting livestock: dairy, goatery, piggery, poultry, fishery)

**Adding new docs** (e.g. livestock-specific guidance for dairy / goatery / piggery / poultry / fishery): drop the PDF into `leaf_flask/ai-docs/`, delete `leaf_flask/data/vectorstore/`, and the next `/api/ai-recommendation` call rebuilds the index with the new doc included. Filename appears as the citation source in the response.

**Livestock-specific retrieval:** when the selected intervention is `Livestock`, `Dairy`, `Goatery`, `Piggery`, `Backyard_Poultry`, `Duckery`, or `Fishery_Activity`, the retrieval query is augmented with animal-husbandry vocabulary (veterinary clinics, fodder, milk collection, Pashu Sakhi support, SHG livestock activities, convergence with DAY-NRLM livestock schemes) so chunks about livestock surface alongside the general intervention text.

**Processing Steps:**
1. PDFs are loaded using PyPDF loader
2. Text is extracted page by page
3. Documents are split into chunks (1000 characters with 200 character overlap)
4. Source metadata is preserved for citation

### 2. Vector Store (ChromaDB)

- Local, file-based vector database
- Stores document chunks with their embeddings
- Enables fast similarity search
- Persisted to `leaf_flask/data/vectorstore/`
- Created on first request, reused subsequently

### 3. Embedding Generation

- Uses OpenAI's embedding model (`text-embedding-ada-002`)
- Converts text chunks into high-dimensional vectors
- Enables semantic similarity matching

### 4. Context Retrieval

When a recommendation is requested:
1. Build a query from block characteristics and intervention type
2. Search vector store for top 5 most relevant chunks
3. Include chunks from multiple source documents
4. Pass retrieved context to the LLM

### 5. Recommendation Generation

**Input to LLM:**
- Block name and district
- Selected intervention type
- Feasibility score (0-100%)
- Current indicator values and their status (in/out of range)
- Retrieved policy context

**LLM Configuration:**
- Model: GPT-4o-mini (cost-effective, fast)
- Temperature: 0.3 (focused, consistent outputs)
- System prompt constrains responses to policy documents

**Output:**
- Assessment of block readiness
- 3-5 actionable recommendations
- Priority actions for gaps
- Source document citations

## API Endpoint

```
POST /api/ai-recommendation

Request Body:
{
    "block_name": "Digboi",
    "district_name": "Tinsukia",
    "intervention": "Organic Farming",
    "feasibility_score": 65.5,
    "metrics": [
        {
            "label": "Agricultural Land %",
            "value": 45.2,
            "in_range": true,
            "min": 30,
            "max": 70
        }
    ],
    "filters": [...]
}

Response:
{
    "recommendation": "...",
    "sources": ["Advisory_organic_village_clusters 1.pdf", ...],
    "feasibility_score": 65.5,
    "metrics_analyzed": 5,
    "gaps_identified": 2,
    "retrieved_context": [
        {"content": "...", "source": "Advisory_organic_village_clusters 1.pdf"},
        ...
    ]
}
```

## User Interface

### AI Insights Button
- Gradient button (teal to dark blue) with white robot icon
- Located on the right side of the recommendation line in block detail view
- Displays: `🤖 AI Insights`

### AI Recommendation Modal

The modal popup includes:

```
┌─────────────────────────────────────────────────────────────────┐
│  🤖 AI Recommendation                    [📋] [⬇️] [✕]         │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────┐  ┌─────────────────────┐  │
│  │ Block Name, District            │  │    Mini Map         │  │
│  │ 🌱 Intervention    📊 Feasibility│  │   (Location)        │  │
│  └─────────────────────────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  ┌─ Assessment ─────────────────────────────────────────────┐  │
│  │ Block readiness analysis with citations [1][2]           │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌─ Recommendations ────────────────────────────────────────┐  │
│  │ ① First recommendation with citation [1]                 │  │
│  │ ② Second recommendation with citation [2]                │  │
│  │ ③ Third recommendation with citation [1]                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌─ Priority Actions ───────────────────────────────────────┐  │
│  │ • Immediate action items highlighted                     │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  📊 Indicators Analyzed                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Indicator      │ Current │ Target Range │ Status         │  │
│  │────────────────┼─────────┼──────────────┼────────────────│  │
│  │ Agri Land %    │  45.20  │   30 - 70    │ ✓ Pass         │  │
│  │ Irrigation %   │  15.00  │   33 - 100   │ ✗ Fail         │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  📄 Retrieved Context from Documents  [▼]                      │
│  (Collapsible - shows actual text chunks from PDFs)            │
├─────────────────────────────────────────────────────────────────┤
│  📚 References: [1] Advisory_organic... ↗  [2] Farm_Live... ↗  │
└─────────────────────────────────────────────────────────────────┘
```

### Modal Features

| Feature | Description |
|---------|-------------|
| **Header** | Block name, intervention type, feasibility score with mini location map |
| **Mini Map** | 150x100px map showing block boundary (non-interactive) |
| **Section Titles** | Assessment, Recommendations, Priority Actions with icons |
| **Numbered Items** | Recommendations displayed as numbered cards with citations |
| **Citations** | Inline `[1]`, `[2]` badges linking to source documents |
| **Indicators Table** | 4-column table with pass/fail status badges |
| **Retrieved Context** | Collapsible section showing actual text chunks from PDFs (for verification) |
| **Reference Documents** | Compact inline list with clickable links to view PDFs |
| **Copy Button** | Copies recommendation text to clipboard (shows checkmark on success) |
| **Download Button** | Opens print dialog to save as PDF with full report |
| **Loading Animation** | Shaking robot icon while fetching recommendation |

### PDF Export Contents

The downloaded PDF includes:
1. Header with location, intervention, feasibility, and generation date
2. Full AI recommendation text
3. Indicators table with pass/fail status
4. Reference documents list
5. Retrieved context from documents
6. LEAF DSS / IWMI footer branding

## File Structure

```
leaf_flask/
├── rag_utils.py          # RAG pipeline implementation
├── app.py                # Flask API endpoints
├── .env                  # OpenAI API key (not committed)
├── data/
│   └── vectorstore/      # ChromaDB persistence
├── templates/
│   └── index.html        # AI modal HTML structure
└── static/
    ├── js/app.js         # AI modal logic, map, copy, download functions
    └── css/style.css     # AI modal styling, animations

ai-docs/
├── Advisory_organic_village_clusters 1.pdf
├── Farm Livelihoods Interventions Under DAY NRLM.pdf
├── Guidelines_on_promotion_IFC_under_DAY_NRLM 1.pdf
├── Natural_farming_training_combined.pdf
├── National_Livestock_Mission_Guidelines_Jan2025.pdf
└── methodology.md        # This document
```

## Dependencies

```
openai>=1.0.0              # OpenAI API client
chromadb>=0.4.0            # Vector database
langchain>=0.3.0           # LLM orchestration
langchain-core>=0.3.0      # Core LangChain components
langchain-openai>=0.2.0    # OpenAI integration
langchain-community>=0.3.0 # Document loaders
langchain-chroma>=0.1.0    # ChromaDB integration
langchain-text-splitters   # Text chunking
pypdf>=3.17.0              # PDF processing
python-dotenv>=1.0.0       # Environment variables
```

## Configuration

Environment variables (`.env` file):
```
OPENAI_API_KEY=sk-proj-...
```

## Performance Considerations

1. **First Request**: Slower (~30-60 seconds) as it processes PDFs and builds vector store
2. **Subsequent Requests**: Fast (~2-5 seconds) using cached vector store

## Cost

- **Infrastructure**: Free (all components are open-source and run locally)
  - ChromaDB: Free, local vector database
  - LangChain: Free, open-source framework
  - PyPDF: Free, open-source PDF processing
  - Leaflet: Free, open-source mapping
- **Only Cost**: OpenAI API usage (~$0.001-0.002 per recommendation with GPT-4o-mini)

## Verification

The system provides transparency through:
1. **Retrieved Context Section**: Shows exact text chunks pulled from PDFs
2. **Source Citations**: Inline `[1]`, `[2]` references in recommendation text
3. **Reference Links**: Direct links to view original PDF documents
4. **PDF Export**: Full report with all sources for audit trail

## Limitations

1. Recommendations are constrained to the 5 loaded policy documents
2. Requires internet connection for OpenAI API
3. Quality depends on relevance of retrieved chunks
4. No real-time policy updates (requires manual document refresh)

## Future Enhancements

1. Add more policy documents as they become available
2. Implement document versioning and refresh
3. Add feedback mechanism to improve recommendations
4. Cache frequent recommendations for faster response
5. Support offline mode with local LLM (Ollama)
6. Add recommendation history/comparison feature
7. Enable multi-language support for regional users
