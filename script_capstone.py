import json
import os
from datetime import datetime, timezone
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# 1. Connection configuration
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
AUTH = (USER, PASSWORD)
driver = GraphDatabase.driver(URI, auth=AUTH)


def parse_json_field(val):
    if pd.isna(val) or not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


# ==========================================
# PHASE 2: SCHEMA & CONSTRAINTS SETUP
# ==========================================
def setup_schema(tx):
    print("Applying constraints and range indexes...")
    constraints = [
        "CREATE CONSTRAINT movie_id_unique IF NOT EXISTS FOR (m:Movie) REQUIRE m.movieId IS UNIQUE;",
        "CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (p:Person) REQUIRE p.personId IS UNIQUE;",
        "CREATE CONSTRAINT genre_id_unique IF NOT EXISTS FOR (g:Genre) REQUIRE g.genreId IS UNIQUE;",
        "CREATE CONSTRAINT keyword_id_unique IF NOT EXISTS FOR (k:Keyword) REQUIRE k.keywordId IS UNIQUE;",
        "CREATE CONSTRAINT company_id_unique IF NOT EXISTS FOR (c:Company) REQUIRE c.companyId IS UNIQUE;",
    ]
    for c in constraints:
        tx.run(c)

    # Range index on vote_average and release_date
    tx.run(
        "CREATE INDEX movie_release_date_range IF NOT EXISTS FOR (m:Movie) ON (m.release_date);"
    )
    tx.run(
        "CREATE INDEX movie_vote_range IF NOT EXISTS FOR (m:Movie) ON (m.vote_average);"
    )


# ==========================================
# PHASE 2: BATCH LOADERS WITH PROVENANCE
# ==========================================
def load_movies_batch(tx, batch, load_time):
    query = """
    UNWIND $batch AS row
    MERGE (m:Movie {movieId: row.id})
    ON CREATE SET
        m.title = row.title,
        m.release_date = date(row.release_date),
        m.budget = row.budget,
        m.revenue = row.revenue,
        m.vote_average = row.vote_average,
        m.source_file = 'tmdb_5000_movies.csv',
        m.source_record_id = toString(row.id),
        m.ingested_at = $load_time

    // Genres
    FOREACH (g IN row.genres |
        MERGE (gen:Genre {genreId: g.id})
        ON CREATE SET 
            gen.name = g.name,
            gen.source_file = 'tmdb_5000_movies.csv',
            gen.source_record_id = toString(g.id),
            gen.ingested_at = $load_time
        MERGE (m)-[:BELONGS_TO]->(gen)
    )

    // Keywords
    FOREACH (k IN row.keywords |
        MERGE (key:Keyword {keywordId: k.id})
        ON CREATE SET 
            key.name = k.name,
            key.source_file = 'tmdb_5000_movies.csv',
            key.source_record_id = toString(k.id),
            key.ingested_at = $load_time
        MERGE (m)-[:TAGGED_WITH]->(key)
    )

    // Production Companies
    FOREACH (c IN row.companies |
        MERGE (comp:Company {companyId: c.id})
        ON CREATE SET 
            comp.name = c.name,
            comp.source_file = 'tmdb_5000_movies.csv',
            comp.source_record_id = toString(c.id),
            comp.ingested_at = $load_time
        MERGE (m)-[:PRODUCED_BY]->(comp)
    )
    """
    tx.run(query, batch=batch, load_time=load_time)


def load_credits_batch(tx, batch, load_time):
    query = """
    UNWIND $batch AS row
    MATCH (m:Movie {movieId: row.movie_id})

    // Cast members (:ACTED_IN with character and cast_order properties)
    FOREACH (actor IN row.cast |
        MERGE (p:Person {personId: actor.id})
        ON CREATE SET
            p.name = actor.name,
            p.gender = actor.gender,
            p.source_file = 'tmdb_5000_credits.csv',
            p.source_record_id = toString(actor.id),
            p.ingested_at = $load_time
        MERGE (p)-[r:ACTED_IN]->(m)
        ON CREATE SET
            r.character = actor.character,
            r.cast_order = actor.order
    )

    // Crew: Directors (:DIRECTED)
    FOREACH (dir IN row.directors |
        MERGE (d:Person {personId: dir.id})
        ON CREATE SET
            d.name = dir.name,
            d.gender = dir.gender,
            d.source_file = 'tmdb_5000_credits.csv',
            d.source_record_id = toString(dir.id),
            d.ingested_at = $load_time
        MERGE (d)-[r:DIRECTED]->(m)
        ON CREATE SET
            r.job = dir.job,
            r.department = dir.department
    )
    """
    tx.run(query, batch=batch, load_time=load_time)


# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    load_time = datetime.now(timezone.utc).isoformat()

    with driver.session() as session:
        # Step 1: Run Constraints and await index completion
        session.execute_write(setup_schema)
        session.run("CALL db.awaitIndexes();")
        print("Schema and constraints are ONLINE.")

        # Step 2: Load Movies CSV (subset or full)
        movies_path = "dataset/tmdb_5000_movies.csv" if os.path.exists("dataset/tmdb_5000_movies.csv") else "tmdb_5000_movies.csv"
        print(f"Reading {movies_path}...")
        df_movies = pd.read_csv(movies_path)

        # Clean null dates or format numbers
        df_movies["release_date"] = df_movies["release_date"].fillna(
            "1900-01-01"
        )
        df_movies["budget"] = (
            pd.to_numeric(df_movies["budget"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        df_movies["revenue"] = (
            pd.to_numeric(df_movies["revenue"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        df_movies["vote_average"] = (
            pd.to_numeric(df_movies["vote_average"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )

        movie_records = []
        for _, row in df_movies.iterrows():
            movie_records.append(
                {
                    "id": int(row["id"]),
                    "title": str(row["title"]),
                    "release_date": str(row["release_date"]),
                    "budget": int(row["budget"]),
                    "revenue": int(row["revenue"]),
                    "vote_average": float(row["vote_average"]),
                    "genres": parse_json_field(row["genres"]),
                    "keywords": parse_json_field(row["keywords"]),
                    "companies": parse_json_field(
                        row["production_companies"]
                    ),
                }
            )

        # Ingest movies in batches of 200
        batch_size = 200
        print(f"Ingesting {len(movie_records)} movies...")
        for i in range(0, len(movie_records), batch_size):
            session.execute_write(
                load_movies_batch,
                movie_records[i : i + batch_size],
                load_time,
            )

        # Step 3: Load Credits CSV
        credits_path = "dataset/tmdb_5000_credits.csv" if os.path.exists("dataset/tmdb_5000_credits.csv") else "tmdb_5000_credits.csv"
        print(f"Reading {credits_path}...")
        df_credits = pd.read_csv(credits_path)

        credits_records = []
        for _, row in df_credits.iterrows():
            cast_raw = parse_json_field(row["cast"])
            crew_raw = parse_json_field(row["crew"])

            # Filter top 8 cast members to prevent bloating
            top_cast = [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "gender": c.get("gender", 0),
                    "character": c.get("character", ""),
                    "order": c.get("order", 99),
                }
                for c in cast_raw[:8]
                if c.get("id")
            ]

            # Filter only directors from crew
            directors = [
                {
                    "id": cr.get("id"),
                    "name": cr.get("name"),
                    "gender": cr.get("gender", 0),
                    "job": cr.get("job"),
                    "department": cr.get("department"),
                }
                for cr in crew_raw
                if cr.get("job") == "Director" and cr.get("id")
            ]

            credits_records.append(
                {
                    "movie_id": int(row["movie_id"]),
                    "cast": top_cast,
                    "directors": directors,
                }
            )

        print(f"Ingesting credits for {len(credits_records)} movies...")
        for i in range(0, len(credits_records), batch_size):
            session.execute_write(
                load_credits_batch,
                credits_records[i : i + batch_size],
                load_time,
            )

        # Step 4: Capstone Post-Load Validation Query
        val_result = session.run(
            """
            MATCH (n)
            WHERE n.source_file IS NULL OR n.ingested_at IS NULL
            RETURN count(n) AS unverified_count
        """
        ).single()
        print(
            f"Validation Check: {val_result['unverified_count']} unverified nodes (Should be 0)."
        )

    driver.close()
    print("Data ingestion complete!")


if __name__ == "__main__":
    main()