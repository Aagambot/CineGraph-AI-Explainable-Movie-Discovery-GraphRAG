import os
import re
try:
    from langchain_community.chains.graph_qa.cypher import GraphCypherQAChain
except ImportError:
    from langchain.chains import GraphCypherQAChain
try:
    from langchain_community.chains.graph_qa.cypher import GraphCypherQAChain
except ImportError:
    from langchain.chains import GraphCypherQAChain

# 2. Prompts (import from langchain_core)
try:
    from langchain_core.prompts import PromptTemplate
except ImportError:
    from langchain.prompts import PromptTemplate

# 3. Neo4j Graph & LLM
from langchain_community.graphs import Neo4jGraph
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

# 1. Connect to Local Neo4j Desktop
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

graph = Neo4jGraph(
    url=NEO4J_URI,
    username=NEO4J_USER,
    password=NEO4J_PASSWORD,
    enhanced_schema=True,
)
graph.refresh_schema()

# 2. Schema Enrichment Prompt with Few-Shot Cypher Examples
CYPHER_GENERATION_TEMPLATE = """Task: Generate a Cypher statement to query a movie graph database.
Instructions:
- Use only the provided labels: (:Movie), (:Person), (:Genre), (:Keyword), (:Company).
- Use relationship types: [:ACTED_IN], [:DIRECTED], [:BELONGS_TO], [:TAGGED_WITH], [:PRODUCED_BY].
- Always use case-insensitive matching for names: toLower(n.name) CONTAINS toLower('...').
- Always add a LIMIT clause (maximum 10).
- Return ONLY the executable Cypher query. Do not wrap in markdown or backticks.
- Do NOT generate any queries containing CREATE, MERGE, SET, or DELETE.

Schema:
{schema}

Few-shot Examples:
Q: Which movies did Christopher Nolan direct?
Cypher: MATCH (p:Person)-[:DIRECTED]->(m:Movie) WHERE toLower(p.name) CONTAINS 'christopher nolan' RETURN m.title, m.release_date LIMIT 10;

Q: Which actors starred in movies directed by Quentin Tarantino?
Cypher: MATCH (d:Person)-[:DIRECTED]->(m:Movie)<-[r:ACTED_IN]-(a:Person) WHERE toLower(d.name) CONTAINS 'tarantino' RETURN DISTINCT a.name, m.title LIMIT 10;

Q: Find top Action movies with high ratings.
Cypher: MATCH (m:Movie)-[:BELONGS_TO]->(g:Genre) WHERE toLower(g.name) = 'action' RETURN m.title, m.vote_average ORDER BY m.vote_average DESC LIMIT 10;

Question: {question}
Cypher Query:"""

CYPHER_PROMPT = PromptTemplate(
    input_variables=["schema", "question"], template=CYPHER_GENERATION_TEMPLATE
)

# 3. Initialize Groq LLM (llama-3.3-70b-versatile with temp=0 for deterministic Cypher)
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.0,
    api_key=os.getenv("GROQ_API_KEY"),
)

# 4. Build GraphCypherQAChain
chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    cypher_prompt=CYPHER_PROMPT,
    verbose=True,
    return_intermediate_steps=True,
    allow_dangerous_requests=True,
)


# 5. Safety Guard Wrapper
def ask_graph(query: str):
    print(f"\n==========================================")
    print(f"User Query: {query}")
    try:
        response = chain.invoke({"query": query})
        generated_cypher = response["intermediate_steps"][0]["query"]
        print(f"Generated Cypher: {generated_cypher}")

        # Regex guard: Reject write operations
        if re.search(
            r"\b(CREATE|MERGE|DELETE|SET|DETACH|DROP|REMOVE)\b",
            generated_cypher,
            re.IGNORECASE,
        ):
            return "Security Alert: Modifying query rejected by safety rail."

        return response["result"]
    except Exception as e:
        return f"Graceful Error: {str(e)}"


if __name__ == "__main__":
    # Test Question 1: Actor-Director Collaboration
    print("Answer:", ask_graph("Which movies did Martin Scorsese direct?"))

    # Test Question 2: Multi-Hop Filter
    print(
        "Answer:",
        ask_graph(
            "Which movies did Tom Hanks act in that belong to the Drama genre?"
        ),
    )