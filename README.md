# 🎬 CineGraph-AI: Explainable Movie Discovery via GraphRAG

CineGraph-AI is an explainable movie recommendation and discovery system. Most modern recommenders rely on black-box vector search or collaborative filtering, which suggest items based on opaque similarity scores without explaining *why*.

CineGraph solves this by combining **Knowledge Graphs** with **Retrieval-Augmented Generation (GraphRAG)**. It maps cinematic entities—actors, directors, genres, keywords, and production companies—into an interconnected graph, executes relational multi-hop queries, and synthesizes natural-language explanations grounded in concrete graph connections.

---

## 💡 What We Built

- **Multi-Entity Knowledge Graph**: A rich property graph modeling films, cast hierarchies, crew roles, genre taxonomies, production studios, and thematic plot keywords.
- **Relational Multi-Hop Discovery**: The ability to surface films connected through meaningful narrative or production bridges (e.g., shared directors, recurring cast collaborations, thematic keyword clusters).
- **Explainable Recommendations**: Instead of just outputting arbitrary titles, the system reveals the explicit reasoning path and Cypher query linking the user's intent to each recommendation.
- **Production-Ready Data Ingestion**: Robust batch ingestion with uniqueness constraints, range indexes, and full data provenance tracking (`source_file`, `source_record_id`, `ingested_at`).
- **GraphRAG with Security Rails**: An automated Cypher generation pipeline powered by LangChain and Groq LLMs, guarded by regex-based write-operation safety rails to prevent database mutations.

---

## ⚙️ How It Works (Step-by-Step)

```text
Raw TMDb Data (Movies & Credits)
             │
             ▼
JSON Parsing & Provenance Tagging
             │
             ▼
Neo4j Knowledge Graph Ingestion (Constraints & Indexes)
             │
             ▼
User Natural Language Query ──> Few-Shot Schema Prompting
                                         │
                                         ▼
                             Cypher Query Generation (Groq LLM)
                                         │
                                         ▼
                             Regex Safety Guardrail Check
                                         │
                                         ▼
                             Graph Traversal & Retrieval (Neo4j)
                                         │
                                         ▼
                     Explainable Natural Language Response
```

### 1. Data Processing & Entity Extraction
The ingestion pipeline processes metadata from two primary TMDb datasets:
- **`dataset/tmdb_5000_movies.csv`**: Extracts movie titles, release dates, budgets, revenues, vote averages, genres, and thematic keywords.
- **`dataset/tmdb_5000_credits.csv`**: Unpacks stringified JSON payloads containing cast hierarchies (top 8 billing) and crew roles (directors).

### 2. Knowledge Graph Schema (`Neo4j`)
The data is mapped into a heterogeneous property graph with strict uniqueness constraints and range indexes on `release_date` and `vote_average`:

- **Node Types**:
  - `(:Movie)`: `title`, `movieId`, `release_date`, `budget`, `revenue`, `vote_average`
  - `(:Person)`: `name`, `personId`, `gender`
  - `(:Genre)`: `name`, `genreId`
  - `(:Keyword)`: `name`, `keywordId`
  - `(:Company)`: `name`, `companyId`

- **Relationship Types**:
  - `(:Person)-[:DIRECTED {job, department}]->(:Movie)`
  - `(:Person)-[:ACTED_IN {character, cast_order}]->(:Movie)`
  - `(:Movie)-[:BELONGS_TO]->(:Genre)`
  - `(:Movie)-[:TAGGED_WITH]->(:Keyword)`
  - `(:Movie)-[:PRODUCED_BY]->(:Company)`

### 3. GraphRAG Traversal & Cypher Synthesis
When a user asks a natural-language question:
1. **Schema-Aware Prompting**: The graph schema and curated few-shot Cypher examples are injected into the context.
2. **Deterministic Query Generation**: High-throughput LLMs via Groq translate user intent into precise read-only Cypher queries.
3. **Safety Guardrails**: A regex-based security rail validates that the generated query contains no mutation keywords (`CREATE`, `MERGE`, `DELETE`, `SET`, `DETACH`, `DROP`, `REMOVE`).
4. **Graph Execution**: The validated Cypher statement runs against Neo4j to retrieve the exact subgraph.

### 4. Explanation Synthesis
The traversal extracts relational evidence connecting entities (e.g., shared directors, genre pairings, co-stars). The LLM formats this structured evidence into a clear, natural-language explanation showing users *why* each movie matches their criteria.

---

## 📁 Project Structure

```text
CineGraph/
├── dataset/
│   ├── tmdb_5000_movies.csv     # Movie metadata, budgets, genres, and keywords
│   └── tmdb_5000_credits.csv    # Cast hierarchies and crew information
├── .env.example                 # Template for environment credentials
├── .gitignore                   # Excluded files and environments
├── graphrag.py                  # GraphRAG QA chain, schema prompt, and safety guards
├── script_capstone.py           # Neo4j schema setup, batch ingestion, and verification
├── requirements.txt             # Python dependencies
└── README.md                    # Project documentation
```

---

## 🚀 How to Run the Project

### 1. Prerequisites
- **Python 3.9+**
- **Neo4j Desktop or Neo4j Community Server** (running locally on `bolt://localhost:7687`)
- **Groq API Key** (obtainable from [Groq Console](https://console.groq.com/))

### 2. Clone and Setup Environment

```bash
# Clone the repository
git clone https://github.com/Aagambot/CineGraph-AI-Explainable-Movie-Discovery-GraphRAG.git
cd CineGraph-AI-Explainable-Movie-Discovery-GraphRAG

# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

*(Alternatively: `pip install pandas neo4j langchain langchain-community langchain-groq python-dotenv`)*

### 4. Configure Environment Variables
Create a `.env` file in the root directory:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
GROQ_API_KEY=your_groq_api_key
```

### 5. Ingest Data into Neo4j
Ensure your Neo4j database is started, then run the batch ingestion script:

```bash
python script_capstone.py
```
This script will:
1. Apply uniqueness constraints (`movieId`, `personId`, `genreId`, etc.) and range indexes.
2. Ingest 4,800+ movies, cast, directors, genres, keywords, and production companies in batches of 200.
3. Validate data provenance (`source_file`, `ingested_at`).

### 6. Run the GraphRAG Query Engine
Execute the GraphRAG interface to ask natural-language questions and inspect generated Cypher and explanations:

```bash
python graphrag.py
```

#### Example Queries:
- *"Which movies did Martin Scorsese direct?"*
- *"Which movies did Tom Hanks act in that belong to the Drama genre?"*
- *"Find top Action movies with high ratings."*
- *"Which actors frequently collaborate with Quentin Tarantino?"*
